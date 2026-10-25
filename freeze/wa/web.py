import os

from wa.httpd import Response, Server

HTML_ROOT = 'html/'
STATIC_ASSET_MAX_AGE_S = 365 * 24 * 60 * 60
STATIC_RESPONSE_CHUNK_SIZE = 256

web_server = Server()

# One buffer for all static file chunks: each chunk is fully written before the next read, and requests run one at a
# time, so a per-chunk allocation would only fragment the small heap.
_chunk = bytearray(STATIC_RESPONSE_CHUNK_SIZE)
_chunk_view = memoryview(_chunk)


def _stream_file(filename: str):
    # Yield the file in chunks of the shared buffer.
    with open(HTML_ROOT + filename, 'rb') as asset:
        while True:
            size = asset.readinto(_chunk)
            if not size:
                break

            yield _chunk_view[:size]


def add_file_route(file: str, url=None):
    if url is None:
        url = '/' + file

    content_types = {
        'css': 'text/css',
        'html': 'text/html',
        'ico': 'image/x-icon'
    }
    content_type = content_types.get(file.rsplit('.', 1)[-1], 'application/octet-stream')

    @web_server.route(url)
    async def static_file(request, filename=file, mime_type=content_type):
        # Static files are cached for a year; Content-Length keeps a cut-off transfer from being cached as complete.
        return Response(
            _stream_file(filename),
            content_type=mime_type,
            cache_control=f'max-age={STATIC_ASSET_MAX_AGE_S}',
            length=os.stat(HTML_ROOT + filename)[6]
        )


add_file_route('index.html', '/')

for file in ('style.css', 'wa.ico'):
    add_file_route(file)
