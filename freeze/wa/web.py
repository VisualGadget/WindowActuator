import asyncio
import gc

from microdot import Microdot, Response

HTML_ROOT = 'html/'
STATIC_ASSET_MAX_AGE_S = 365 * 24 * 60 * 60
STATIC_RESPONSE_CHUNK_SIZE = 256

web_server = Microdot()
Response.default_content_type = 'text/html'
Response.default_send_file_max_age = STATIC_ASSET_MAX_AGE_S

# One buffer for all static file chunks: each chunk is fully written before the next read, and requests run one at a
# time, so a per-chunk allocation would only fragment the small heap.
_chunk = bytearray(STATIC_RESPONSE_CHUNK_SIZE)
_chunk_view = memoryview(_chunk)
_request_lock = asyncio.Lock()
_handle_request = web_server.handle_request


async def _handle_request_serially(reader, writer):
    # A browser opens several connections at once (the start page loads three pages and their stylesheet), and each
    # request needs a few KB of heap. Serve them one at a time; waiting connections stay in the listen queue.
    async with _request_lock:
        try:
            await _handle_request(reader, writer)
        except MemoryError:
            # Microdot lets errors raised while sending escape the connection task, and the event loop handler then
            # resets the board. Drop the connection instead.
            print('HTTP request dropped: out of memory')
            try:
                await writer.aclose()
            except Exception:
                pass
        gc.collect()


web_server.handle_request = _handle_request_serially


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
                size = asset.readinto(_chunk)
                if not size:
                    break

                yield _chunk_view[:size]

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
