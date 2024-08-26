from microdot import Microdot, Response


HTML_ROOT = 'html/'

web_server = Microdot()
Response.default_content_type = 'text/html'


def add_file_route(file: str, url=None):
    if url is None:
        url = '/' + file

    web_server.route(url)(
        lambda _: Response.send_file(HTML_ROOT + file)
    )


add_file_route('index.html', '/')

for file in ('style.css', 'wa.ico'):
    add_file_route(file)
