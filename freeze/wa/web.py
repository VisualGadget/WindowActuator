from microdot import Microdot, Response

HTML_ROOT = 'html/'
STATIC_ASSET_MAX_AGE_S = 365 * 24 * 60 * 60
STATIC_RESPONSE_CHUNK_SIZE = 512

web_server = Microdot()
Response.default_content_type = 'text/html'
Response.default_send_file_max_age = STATIC_ASSET_MAX_AGE_S


def add_file_route(file: str, url=None):
    if url is None:
        url = '/' + file

    content_types = {
        'css': 'text/css',
        'html': 'text/html',
        'ico': 'image/x-icon'
    }
    content_type = content_types.get(file.rsplit('.', 1)[-1], 'application/octet-stream')

    async def stream_file(filename=file):
        # Yield bounded chunks so ESP8266 socket writes cannot stall on a partial send.
        with open(HTML_ROOT + filename, 'rb') as asset:
            while True:
                chunk = asset.read(STATIC_RESPONSE_CHUNK_SIZE)
                if not chunk:
                    break

                yield chunk

    @web_server.route(url)
    async def static_file(request, filename=file, mime_type=content_type):
        return Response(
            stream_file(filename=filename),
            headers={
                'Cache-Control': f'max-age={STATIC_ASSET_MAX_AGE_S}',
                'Content-Type': mime_type
            }
        )


add_file_route('index.html', '/')

for file in ('style.css', 'wa.ico'):
    add_file_route(file)
