
import os
import re
import ConfigParser

import genshi.template

import rrd

_initialized = None
_loader = None
_cp = None

def check_initialized(environ):
    global _initialized
    global _loader
    global _cp
    if not _initialized:
        if 'prodview.templates' in environ:
            _loader = genshi.template.TemplateLoader(environ['prodview.templates'], auto_reload=True)
        else:
            _loader = genshi.template.TemplateLoader('/usr/share/prodview/templates', auto_reload=True)
        tmp_cp = ConfigParser.ConfigParser()
        if 'prodview.config' in environ:
            tmp_cp.read(environ['prodview.config'])
        else:
            tmp_cp.read('/etc/prodview.conf')
        _cp = tmp_cp
        _initialized = True


def static_file_server(fname):
    def static_file_server_internal(environ, start_response):
        for result in serve_static_file(fname, environ, start_response):
            yield result
    return static_file_server_internal


def serve_static_file(fname, environ, start_response):
    static_file = os.path.join(_cp.get("prodview", "basedir"), fname)

    try:
        fp = open(static_file, "r")
    except:
        raise
        yield not_found(environ, start_response)
        return

    status = '200 OK'
    headers = [('Content-type', 'application/json'),
               ('Cache-control', 'max-age=60, public')]
    start_response(status, headers)

    while True:
        buffer = fp.read(4096)
        if not buffer:
            break
        yield buffer


_totals_json_re = re.compile(r'^/*json/totals$')
totals_json = static_file_server("totals.json")


_summary_json_re = re.compile(r'^/*json/summary$')
summary_json = static_file_server("summary.json")


_site_summary_json_re = re.compile(r'^/*json/site_summary$')
site_summary_json = static_file_server("site_summary.json")


_request_totals_json_re = re.compile(r'^/*json/+([-_A-Za-z0-9]+)/+totals$')
def request_totals_json(environ, start_response):
    path = environ.get('PATH_INFO', '')
    m = _request_totals_json_re.match(path)
    request = m.groups()[0]
    fname = os.path.join(_cp.get("prodview", "basedir"), request, "totals.json")
    
    for result in serve_static_file(fname, environ, start_response):
        yield result


_request_summary_json_re = re.compile(r'^/*json/+([-_A-Za-z0-9]+)/+summary$')
def request_summary_json(environ, start_response):
    path = environ.get('PATH_INFO', '')
    m = _request_summary_json_re.match(path)
    request = m.groups()[0]
    fname = os.path.join(_cp.get("prodview", "basedir"), request, "summary.json")

    for result in serve_static_file(fname, environ, start_response):
        yield result


_request_site_summary_json_re = re.compile(r'^/*json/+([-_A-Za-z0-9]+)/+site_summary$')
def request_site_summary_json(environ, start_response):
    path = environ.get('PATH_INFO', '')
    m = _request_site_summary_json_re.match(path)
    request = m.groups()[0]
    fname = os.path.join(_cp.get("prodview", "basedir"), request, "site_summary.json")

    for result in serve_static_file(fname, environ, start_response):
        yield result


_request_graph_re = re.compile(r'^/*graphs/+([-_A-Za-z0-9]+)/?(hourly|weekly|daily|monthly|yearly)?/?$')
def request_graph(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'image/png'),
               ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = _request_graph_re.match(path)
    interval = "daily"
    request = m.groups()[0]
    if m.groups()[1]:
        interval=m.groups()[1]

    return [ rrd.request(_cp.get("prodview", "basedir"), interval, request) ]


_subtask_graph_re = re.compile(r'^/*graphs/+([-_A-Za-z0-9]+)/+([-_A-Za-z0-9]+)/?(hourly|weekly|daily|monthly|yearly)?/?$')
def subtask_graph(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'image/png'),
               ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = _subtask_graph_re.match(path)
    interval = "daily"
    request = m.groups()[0]
    subtask = m.groups()[1]
    if m.groups()[2]:
        interval=m.groups()[2]

    return [ rrd.subtask(_cp.get("prodview", "basedir"), interval, request, subtask) ]


_site_graph_re = re.compile(r'^/*graphs/(T[0-9]_[A-Z]{2,2}_[-_A-Za-z0-9]+)/?(hourly|weekly|daily|monthly|yearly)?/?$')
def site_graph(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'image/png'),
               ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = _request_graph_re.match(path)
    interval = "daily"
    site = m.groups()[0]
    if m.groups()[1]:
        interval=m.groups()[1]

    return [ rrd.site(_cp.get("prodview", "basedir"), interval, site) ]


_request_site_graph_re = re.compile(r'^/*graphs/([-_A-Za-z0-9]+)/(T[0-9]_[A-Z]{2,2}_[-_A-Za-z0-9]+)/?(hourly|weekly|daily|monthly|yearly)?/?$')
def request_site_graph(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'image/png'),
               ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = _request_site_graph_re.match(path)
    interval = "daily"
    request = m.groups()[0]
    site = m.groups()[1]
    if m.groups()[2]:
        interval=m.groups()[2]

    return [ rrd.request_site(_cp.get("prodview", "basedir"), interval, request, site) ]


_request_re = re.compile(r'^/*([-_A-Za-z0-9]+)/?$')
def request(environ, start_response):
    status = '200 OK' # HTTP Status
    headers = [('Content-type', 'text/html'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = _request_re.match(path)
    request = m.groups()[0]

    tmpl = _loader.load('request.html')

    return [tmpl.generate(request=request).render('html', doctype='html')]


def index(environ, start_response):
    status = '200 OK' # HTTP Status
    headers = [('Content-type', 'text/html'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)
    
    tmpl = _loader.load('index.html')
    
    return [tmpl.generate().render('html', doctype='html')]
    

def not_found(environ, start_response):
    status = '404 Not Found'
    headers = [('Content-type', 'text/html'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)
    path = environ.get('PATH_INFO', '').lstrip('/')
    return ["Resource %s not found" % path]


subtask = not_found
subtask_site_graph = not_found


# Add url's here for new pages
urls = [
    (re.compile(r'^/*$'), index),
    (_totals_json_re, totals_json),
    (_summary_json_re, summary_json),
    (_site_summary_json_re, site_summary_json),
    (_request_totals_json_re, request_totals_json),
    (_request_summary_json_re, request_summary_json),
    (_request_site_summary_json_re, request_site_summary_json),
    #(re.compile(r'^graphs/([-_A-Za-z0-9]+)/prio/?$'), request_prio_graph),
    (_site_graph_re, site_graph),
    (_request_graph_re, request_graph),
    (_request_site_graph_re, request_site_graph),
    (_subtask_graph_re, subtask_graph),
    (re.compile(r'^graphs/([-_A-Za-z0-9]+)/([-_A-Za-z0-9]+)/(T[0-9]_[A-Z]{2,2}_[-_A-Za-z0-9]+)/?$'), subtask_site_graph),
    (_request_re, request),
    (re.compile(r'^([-_A-Za-z0-9]+)/([-_A-Za-z0-9]+)/?$'), subtask),
]


def application(environ, start_response):
    check_initialized(environ)

    path = environ.get('PATH_INFO', '').lstrip('/')
    for regex, callback in urls:
        match = regex.match(path)
        if match:
            environ['jobview.url_args'] = match.groups()
            return callback(environ, start_response)
    return not_found(environ, start_response)


