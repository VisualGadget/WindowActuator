from microdot import Microdot, Response, Request

HTML_ROOT = 'html/'

web_server = Microdot()

Response.default_content_type = 'text/html'


# def read_file(file: str) -> str:
#     with open(HTML_ROOT + file, encoding='utf8') as f:
#         return f.read()


@web_server.route('/')
def _index(request: Request):
    return Response.send_file(HTML_ROOT + 'index.html')


@web_server.route('/style.css')
def _style(request: Request):
    return Response.send_file(HTML_ROOT + 'style.css')
