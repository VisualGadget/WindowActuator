import asyncio
import gc

# Minimal HTTP/1.0 server for the actuator web UI. It replaces Microdot, which needed about 7 KB of the ~38 KB heap
# before serving anything. Requests are handled one at a time with bounded reads, and responses are streamed.

READ_TIMEOUT_S = 10
MAX_HEADERS = 32
MAX_BODY_LENGTH = 2048
TEXT_TYPE = "text/plain; charset=UTF-8"
HTML_TYPE = "text/html; charset=UTF-8"
JSON_TYPE = "application/json"
_REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


class HTTPError(Exception):
    # Abort the current request with an HTTP status and a plain text message.

    def __init__(self, status: int, message: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message


def abort(status: int, message: str = "") -> None:
    # Stop handling the request and reply with the given status.
    raise HTTPError(status, message)


class Request:
    # Parsed request: method, path without the query string, and urlencoded form fields.

    def __init__(self, method: str, path: str, form: dict):
        self.method = method
        self.path = path
        self.form = form


class Response:
    # Response with a body given as str, bytes or an iterable of str/bytes chunks streamed to the client. Give the
    # body length when it is known, so a client can tell a cut-off response from a complete one.

    def __init__(
        self,
        body="",
        status: int = 200,
        content_type: str = HTML_TYPE,
        cache_control: str = "no-store",
        length: int | None = None,
    ):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.cache_control = cache_control
        self.length = length


def unquote_plus(value: bytes) -> str:
    # Decode one application/x-www-form-urlencoded value. Malformed escapes are kept literally.
    value = value.replace(b"+", b" ")
    if b"%" not in value:
        return value.decode()

    parts = value.split(b"%")
    decoded = bytearray(parts[0])
    for part in parts[1:]:
        try:
            if len(part) < 2:
                raise ValueError

            decoded.append(int(part[:2].decode(), 16))
            decoded.extend(part[2:])
        except Exception:
            decoded.extend(b"%")
            decoded.extend(part)

    return bytes(decoded).decode()


def parse_form(body: bytes) -> dict:
    # Parse an application/x-www-form-urlencoded body into a dict of strings.
    form = {}
    try:
        for pair in body.split(b"&"):
            if not pair:
                continue

            name_value = pair.split(b"=", 1)
            form[unquote_plus(name_value[0])] = unquote_plus(name_value[1]) if len(name_value) > 1 else ""

    except UnicodeError:
        raise HTTPError(400, "Invalid form encoding") from None

    return form


async def _read_request(reader) -> Request | None:
    # Read the request line, Content-Length and the form body. Other headers are skipped without being stored.
    line = await reader.readline()
    if not line:
        return None

    parts = line.split()
    if len(parts) != 3:
        raise HTTPError(400, "Malformed request line")

    content_length = 0
    for _ in range(MAX_HEADERS):
        header = await reader.readline()
        if header in (b"\r\n", b"\n", b""):
            break

        name_value = header.split(b":", 1)
        if len(name_value) == 2 and name_value[0].strip().lower() == b"content-length":
            try:
                content_length = int(name_value[1].strip())
            except ValueError:
                raise HTTPError(400, "Invalid Content-Length") from None

    else:
        raise HTTPError(400, "Too many headers")

    if not 0 <= content_length <= MAX_BODY_LENGTH:
        raise HTTPError(413, "Request body too large")

    form = parse_form(await reader.readexactly(content_length)) if content_length else {}
    path = parts[1].split(b"?", 1)[0].decode()

    return Request(method=parts[0].decode(), path=path, form=form)


async def _send(writer, response: Response) -> None:
    # Write the status line, headers and the streamed body. Without Content-Length, closing the connection ends the
    # body (HTTP/1.0).
    reason = _REASONS.get(response.status, "Unknown")
    length = "" if response.length is None else "Content-Length: %d\r\n" % response.length
    writer.write(
        (
            "HTTP/1.0 %d %s\r\nContent-Type: %s\r\nCache-Control: %s\r\n%sConnection: close\r\n\r\n"
            % (response.status, reason, response.content_type, response.cache_control, length)
        ).encode()
    )
    await writer.drain()

    body = response.body
    if isinstance(body, (str, bytes)):
        body = (body,)
    for chunk in body:
        if isinstance(chunk, str):
            chunk = chunk.encode()
        if chunk:
            writer.write(chunk)
            await writer.drain()


class Server:
    # Route table and connection handler.

    def __init__(self):
        self._routes: dict = {}
        self._lock = asyncio.Lock()

    def route(self, path: str, methods: tuple = ("GET",)):
        # Register a coroutine handler for a path. The handler receives the Request and returns a Response, a str
        # body, or a (str body, status) tuple.
        def register(handler):
            for method in methods:
                self._routes[(method, path)] = handler
            return handler

        return register

    async def start(self, host: str = "0.0.0.0", port: int = 80) -> None:
        # Listen and serve until the server is closed.
        server = await asyncio.start_server(self._serve, host, port, backlog=8)
        await server.wait_closed()

    async def _dispatch(self, request: Request) -> Response:
        # Run the handler for the request and normalize its result into a Response.
        handler = self._routes.get((request.method, request.path))
        if handler is None:
            known = any(path == request.path for _, path in self._routes)
            raise HTTPError(405 if known else 404, "Method not allowed" if known else "Not found")

        result = await handler(request)
        if isinstance(result, Response):
            return result
        if isinstance(result, tuple):
            return Response(result[0], status=result[1], content_type=TEXT_TYPE)

        return Response(result)

    async def _serve(self, reader, writer) -> None:
        # Browsers open several connections at once; serving them one at a time bounds the heap one request needs.
        # Waiting connections stay in the listen queue. No error may escape: the event loop handler would reset the
        # board.
        async with self._lock:
            gc.collect()
            try:
                try:
                    request = await asyncio.wait_for(_read_request(reader), READ_TIMEOUT_S)
                    response = await self._dispatch(request) if request else None
                except HTTPError as ex:
                    response = Response(ex.message, status=ex.status, content_type=TEXT_TYPE)
                except (MemoryError, OSError, asyncio.TimeoutError):
                    raise
                except Exception as ex:
                    print("HTTP handler error:", repr(ex))
                    response = Response("Internal error", status=500, content_type=TEXT_TYPE)

                if response:
                    await _send(writer, response)
            except MemoryError:
                print("HTTP request dropped: out of memory")
            except Exception:
                pass  # client gone, timed out or reset: nothing left to answer

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            gc.collect()
