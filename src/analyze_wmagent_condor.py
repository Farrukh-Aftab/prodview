#!/usr/bin/python

import os
import json
import optparse

import rrdtool
import htcondor

def parse_args():
    parser = optparse.OptionParser()
    parser.add_option("-p", "--pool", help="HTCondor pool to analyze", dest="pool")
    parser.add_option("-o", "--output", help="Top-level output dir", dest="output")
    return parser.parse_args()


def query_schedd(ad, workflows):
    schedd = htcondor.Schedd(ad)
    try:
        jobs = schedd.query("WMAgent_RequestName isnt null && WMAgent_SubTaskName isnt null && JobPrio isnt null && DESIRED_Sites isnt null", ["WMAgent_RequestName", "WMAgent_SubTaskName", "DESIRED_Sites", "MATCH_EXP_JOBGLIDEIN_CMSSite", "JobPrio", "JobStatus"])
    except Exception, e:
        print "Failed querying", ad["Name"]
        print e
        return
    for job in jobs:
        request = job['WMAgent_RequestName']
        sub_task = job['WMAgent_SubTaskName'].split("/")[-1]
        desired_sites = job['DESIRED_Sites'].split(",")
        desired_sites.sort()
        desired_sites = tuple(desired_sites)
        running_site = job.get("MATCH_EXP_JOBGLIDEIN_CMSSite")
        if job["JobStatus"] == 1:
            status = "MatchingIdle"
        elif job["JobStatus"] == 2:
            status = "Running"
        prio = job["JobPrio"]
        request_dict = workflows.setdefault(request, {})
        subtask_dict = request_dict.setdefault(sub_task, {})
        summary_dict = subtask_dict.setdefault('Summary', {})
        summary_internal = summary_dict.setdefault("Internal", {})
        jobinfo = (prio, desired_sites)
        if not running_site:
            summary_internal.setdefault(jobinfo, 0)
            summary_internal[jobinfo] += 1
        for site in desired_sites:
            site_dict = subtask_dict.setdefault(site, {})
            prio_dict = site_dict.setdefault(prio, {"Running": 0, "MatchingIdle": 0})
            prio_dict.setdefault(status, 0)
            prio_dict[status] += 1
        if running_site:
            site_dict = subtask_dict.setdefault(running_site, {})
            prio_dict = site_dict.setdefault(prio, {"Running": 0, "MatchingIdle": 0})
            prio_dict.setdefault(status, 0)
            prio_dict[status] += 1


def analyze_prios_inner(workflows, sites, prio):
    higher_idle = 0
    lower_running = 0
    sites = set(sites)
    if not sites:
        return 0, 0
    for request, request_dict in workflows.items():
        for subtask, subtask_dict in request_dict.items():
            for running_site, site_dict in subtask_dict.items():
                if running_site == "Summary" and site_dict.get("Internal"):
                    for jobinfo, jobs in site_dict["Internal"].items():
                        idle_prio, desired_sites = jobinfo
                        desired_sites = set(desired_sites)
                        if (sites.intersection(desired_sites)) and idle_prio > prio:
                            higher_idle += jobs
                elif running_site in sites:
                    for running_prio, prio_dict in site_dict.items():
                        if running_prio >= prio:
                            continue
                        for status, count in prio_dict.items():
                            if status != "Running":
                                continue
                            lower_running += count
    return higher_idle, lower_running


def analyze_prios(workflows):
    for request, request_dict in workflows.items():
        for subtask, subtask_dict in request_dict.items():
            for site, site_dict in subtask_dict.items():
                if site == "Summary":
                    continue
                for prio, prio_dict in site_dict.items():
                    higher_idle, lower_running = analyze_prios_inner(workflows, [site], prio)
                    prio_dict["LowerPrioRunning"] = lower_running
                    prio_dict["HigherPrioIdle"] = higher_idle


def summarize(workflows):
    for request, request_dict in workflows.items():
        for subtask, subtask_dict in request_dict.items():
            min_prio = min([min(site_dict.keys()) for site_dict in subtask_dict.values()])
            sites = subtask_dict.keys()
            higher_idle, lower_running = analyze_prios_inner(workflows, sites, min_prio)
            idle = sum(subtask_dict.get("Summary", {}).get("Internal", {}).values())
            running = 0
            for site_dict in subtask_dict.values():
                for prio_dict in site_dict.values():
                    running += prio_dict.get("Running", 0)
            subtask_dict["Summary"].update({"BasePrio": min_prio, "Running": running, "Idle": idle, "HigherPrioIdle": higher_idle, "LowerPrioRunning": lower_running})

        min_prio = min([subtask_dict["Summary"]["BasePrio"] for subtask_dict in request_dict.values()])
        min_prio = min_prio % 10000000
        sites = set()
        for subtask_dict in request_dict.values():
            for site, site_dict in subtask_dict.items():
                if min_prio in site_dict:
                    sites.add(site)
        running = sum([subtask_dict["Summary"]["Running"] for subtask_dict in request_dict.values()])
        idle = sum([subtask_dict["Summary"]["Idle"] for subtask_dict in request_dict.values()])
        higher_idle, lower_running = analyze_prios_inner(workflows, sites, min_prio)
        request_dict["Summary"] = {"BasePrio": min_prio, "Running": running, "Idle": idle, "HigherPrioIdle": higher_idle, "LowerPrioRunning": lower_running}

        request_sites = request_dict["Summary"].setdefault("Sites", {})
        for subtask, subtask_dict in request_dict.items():
            if subtask == "Summary":
                continue
            for site, site_dict in subtask_dict.items():
                if site == "Summary":
                    continue
                request_sites.setdefault(site, {"Running": 0, "MatchingIdle": 0})
                request_sites[site]["Running"] += sum([prio_dict["Running"] for prio_dict in site_dict.values()])
                request_sites[site]["MatchingIdle"] += sum([prio_dict["MatchingIdle"] for prio_dict in site_dict.values()])


def drop_obj(obj, dirname, fname):
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    fname_tmp = os.path.join(dirname, fname + ".tmp")
    fname = os.path.join(dirname, fname)
    json.dump(obj, open(fname_tmp, "w"))
    os.rename(fname_tmp, fname)


def write_json(workflows, output):

    sites = {}
    running = 0
    idle = 0
    for request_dict in workflows.values():
        for site, site_dict in request_dict["Summary"]["Sites"].items():
            sites.setdefault(site, {"Running": 0, "MatchingIdle": 0, "RequestCount": 0})
            sites[site]["Running"] += site_dict["Running"]
            sites[site]["MatchingIdle"] += site_dict["MatchingIdle"]
            sites[site]["RequestCount"] += 1
        running += request_dict["Summary"]["Running"]
        idle += request_dict["Summary"]["Idle"]
    requests = len(workflows)

    drop_obj(sites, output, "site_summary.json")
    drop_obj({"Running": running, "Idle": idle, "RequestCount": requests}, output, "totals.json")

    final_obj = {}
    for request, request_dict in workflows.items():
        final_obj[request] = dict(request_dict["Summary"])
        final_obj[request]["SiteCount"] = len(final_obj[request]["Sites"])
    drop_obj(final_obj, output, "summary.json")

    for request, request_dict in workflows.items():
        final_obj = {}
        request_sites = {}
        for subtask, subtask_dict in request_dict.items():
            if subtask == "Summary":
                continue
            final_obj[subtask] = subtask_dict["Summary"]
            sites = subtask_dict.keys()
            sites.remove("Summary")
            final_obj["SiteCount"] = len(sites)

            sites = {}
            for site, site_dict in subtask_dict.items():
                if site == "Summary":
                    continue
                sites[site] = {"Running":      sum(prio_dict["Running"] for prio_dict in site_dict.values()),
                               "MatchingIdle": sum(prio_dict["MatchingIdle"] for prio_dict in site_dict.values())}
            subtask_dir = os.path.join(output, request, subtask)
            drop_obj(sites, subtask_dir, "site_summary.json")
            for site, site_dict in sites.items():
                request_sites.setdefault(site, {"Running": 0, "MatchingIdle": 0})
                for status, count in site_dict.items():
                    request_sites[site][status] += count
            drop_obj(subtask_dict["Summary"], subtask_dir, "summary.json")
        request_dir = os.path.join(output, request)
        drop_obj(request_sites, request_dir, "site_summary.json")
        drop_obj(final_obj, request_dir, "summary.json")


def write_rrds(workflows, output):

    sites = {}
    running = 0
    idle = 0
    for request_dict in workflows.values():
        for site, site_dict in request_dict["Summary"]["Sites"].items():
            sites.setdefault(site, {"Running": 0, "MatchingIdle": 0})
            sites[site]["Running"] += site_dict["Running"]
            sites[site]["MatchingIdle"] += site_dict["MatchingIdle"]
        running += request_dict["Summary"]["Running"]
        idle += request_dict["Summary"]["Idle"]
    fname = os.path.join(output, "summary.rrd")
    if not os.path.exists(fname):
        rrdtool.create(fname,
            "--step", "180",
            "DS:Running:GAUGE:360:U:U",
            "DS:Idle:GAUGE:360:U:U",
            "RRA:AVERAGE:0.5:1:1000",
            "RRA:MIN:0.5:20:8760",
            "RRA:MAX:0.5:20:8760",
            "RRA:AVERAGE:0.5:20:8760",
        )
    rrdtool.update(fname, "N:%d:%d" % (running, idle))
    for site, site_dict in sites.items():
        fname = os.path.join(output, "%s.rrd" % site)
        if not os.path.exists(fname):
            rrdtool.create(fname,
                "--step", "180",
                "DS:Running:GAUGE:360:U:U",
                "DS:MatchingIdle:GAUGE:360:U:U",
                "RRA:AVERAGE:0.5:1:1000",
                "RRA:MIN:0.5:20:8760",
                "RRA:MAX:0.5:20:8760",
                "RRA:AVERAGE:0.5:20:8760",
            )   
        rrdtool.update(fname, "N:%d:%d" % (site_dict["Running"], site_dict["MatchingIdle"]))

    for request, request_dict in workflows.items():
        request_dir = os.path.join(output, request)
        if not os.path.exists(request_dir):
            os.makedirs(request_dir)
        fname = os.path.join(request_dir, "request.rrd")
        if not os.path.exists(fname):
            rrdtool.create(fname,
                "--step", "180",
                "DS:Running:GAUGE:360:U:U",
                "DS:Idle:GAUGE:360:U:U",
                "DS:HigherPrioIdle:GAUGE:360:U:U",
                "DS:LowerPrioRunning:GAUGE:360:U:U",
                "RRA:AVERAGE:0.5:1:1000",
                "RRA:MIN:0.5:20:8760",
                "RRA:MAX:0.5:20:8760",
                "RRA:AVERAGE:0.5:20:8760",
                )
        stats = request_dict["Summary"]["Running"], request_dict["Summary"]["Idle"], request_dict["Summary"]["HigherPrioIdle"], request_dict["Summary"]["LowerPrioRunning"]
        rrdtool.update(fname, ("N:" + ":".join(["%d"]*len(stats))) % stats)

        for site, site_dict in request_dict["Summary"]["Sites"].items():
            fname = os.path.join(request_dir, "%s.rrd" % site)
            if not os.path.exists(fname):
                rrdtool.create(fname,
                    "--step", "180",
                    "DS:Running:GAUGE:360:U:U",
                    "DS:MatchingIdle:GAUGE:360:U:U",
                    "RRA:AVERAGE:0.5:1:1000",
                    "RRA:MIN:0.5:20:8760",
                    "RRA:MAX:0.5:20:8760",
                    "RRA:AVERAGE:0.5:20:8760",
                )
            rrdtool.update(fname, "N:%d:%d" % (site_dict["Running"], site_dict["MatchingIdle"]))

        for subtask, subtask_dict in request_dict.items():
            if subtask == "Summary":
                continue
            subtask_dir = os.path.join(request_dir, subtask)
            if not os.path.exists(subtask_dir):
                os.makedirs(subtask_dir)
            fname = os.path.join(subtask_dir, "subtask.rrd")
            if not os.path.exists(fname):
                rrdtool.create(fname,
                    "--step", "180",
                    "DS:Running:GAUGE:360:U:U",
                    "DS:Idle:GAUGE:360:U:U",
                    "DS:HigherPrioIdle:GAUGE:360:U:U",
                    "DS:LowerPrioRunning:GAUGE:360:U:U",
                    "RRA:AVERAGE:0.5:1:1000",
                    "RRA:MIN:0.5:20:8760",
                    "RRA:MAX:0.5:20:8760",
                    "RRA:AVERAGE:0.5:20:8760",
                    )
            stats = subtask_dict["Summary"]["Running"], subtask_dict["Summary"]["Idle"], subtask_dict["Summary"]["HigherPrioIdle"], subtask_dict["Summary"]["LowerPrioRunning"]
            rrdtool.update(fname, ("N:" + ":".join(["%d"]*len(stats))) % stats)

            for site, site_dict in subtask_dict.items():
                if site == "Summary":
                    continue
                fname = os.path.join(subtask_dir, "%s.rrd" % site)
                if not os.path.exists(fname):
                    rrdtool.create(fname,
                        "--step", "180",
                        "DS:Running:GAUGE:360:U:U",
                        "DS:MatchingIdle:GAUGE:360:U:U",
                        "DS:HigherPrioIdle:GAUGE:360:U:U",
                        "DS:LowerPrioRunning:GAUGE:360:U:U",
                        "RRA:AVERAGE:0.5:1:1000",
                        "RRA:MIN:0.5:20:8760",
                        "RRA:MAX:0.5:20:8760",
                        "RRA:AVERAGE:0.5:20:8760",
                        )
                stats = sum(prio_dict["Running"] for prio_dict in site_dict.values()), \
                        sum(prio_dict["MatchingIdle"] for prio_dict in site_dict.values()), \
                        sum(prio_dict["HigherPrioIdle"] for prio_dict in site_dict.values()), \
                        sum(prio_dict["LowerPrioRunning"] for prio_dict in site_dict.values())
                rrdtool.update(fname, ("N:" + ":".join(["%d"]*len(stats))) % stats)


def main():
    opts, args = parse_args()

    if opts.pool:
        coll = htcondor.Collector(opts.pool)
    else:
        coll = htcondor.Collector()

    schedd_ads = coll.query(htcondor.AdTypes.Schedd, 'CMSGWMS_Type=?="prodschedd"', ['Name', 'MyAddress', 'ScheddIpAddr'])

    workflows = {}
    for ad in schedd_ads:
        print "Querying schedd", ad['Name']
        query_schedd(ad, workflows)

    analyze_prios(workflows)
    summarize(workflows)

    for request, request_dict in workflows.items():
        print "- Info for request", request
        print request_dict["Summary"]
        for subtask, subtask_dict in request_dict.items():
            if subtask == "Summary":
                continue
            print "\t- Info for subtask", subtask
            del subtask_dict["Summary"]["Internal"]
            print "\t", subtask_dict["Summary"]
            for site, site_dict in subtask_dict.items():
                if site == "Summary":
                    continue
                print "\t\t- Site", site
                for prio, prio_dict in site_dict.items():
                    print "\t\t\t- Prio", prio
                    for status, count in prio_dict.items():
                        print "\t\t\t\t- %s: %d" % (status, count)

    if opts.output:
        write_json(workflows, opts.output)
        write_rrds(workflows, opts.output)

if __name__ == "__main__":
    main()

