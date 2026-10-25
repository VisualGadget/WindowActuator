import asyncio
import importlib.util
from pathlib import Path

module_path = Path(__file__).parents[1] / "freeze" / "wa" / "httpd.py"
spec = importlib.util.spec_from_file_location("httpd", module_path)
assert spec is not None
httpd = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(httpd)


class FakeWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def serve(server, raw):
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(raw)
        reader.feed_eof()
        writer = FakeWriter()
        await server._serve(reader, writer)
        return writer

    writer = asyncio.run(run())
    assert writer.closed is True
    head, _, body = bytes(writer.data).partition(b"\r\n\r\n")
    return head.decode(), body


def build_server():
    server = httpd.Server()

    @server.route("/page")
    async def page(request):
        def chunks():
            yield "a"
            yield b"b"
            yield ""
            yield "c"

        return httpd.Response(chunks())

    @server.route("/set", methods=("POST",))
    async def set_value(request):
        if "value" not in request.form:
            httpd.abort(400, "Missing value")
        return request.form["value"]

    @server.route("/busy")
    async def busy(request):
        return "Not ready", 503

    @server.route("/broken")
    async def broken(request):
        raise RuntimeError("boom")

    return server


def post(path, body):
    return (
        b"POST %s HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: %d\r\n\r\n%s"
        % (
            path,
            len(body),
            body,
        )
    )


def test_get_streams_generator_body():
    head, body = serve(build_server(), b"GET /page?x=1 HTTP/1.1\r\nHost: x\r\n\r\n")
    assert head.startswith("HTTP/1.0 200 OK")
    assert "Content-Type: text/html; charset=UTF-8" in head
    assert "Cache-Control: no-store" in head
    assert body == b"abc"


def test_post_form_is_url_decoded():
    head, body = serve(build_server(), post(b"/set", b"other=1&value=a+b%2Fc%25"))
    assert head.startswith("HTTP/1.0 200")
    assert body == "a b/c%".encode()


def test_unquote_keeps_malformed_escapes():
    assert httpd.unquote_plus(b"100%") == "100%"
    assert httpd.unquote_plus(b"%zz%4") == "%zz%4"
    assert httpd.unquote_plus(b"%D0%AF") == "Я"


def test_abort_returns_status_and_message():
    head, body = serve(build_server(), post(b"/set", b"other=1"))
    assert head.startswith("HTTP/1.0 400 Bad Request")
    assert body == b"Missing value"


def test_tuple_result_sets_status():
    head, body = serve(build_server(), b"GET /busy HTTP/1.1\r\n\r\n")
    assert head.startswith("HTTP/1.0 503")
    assert body == b"Not ready"


def test_unknown_path_and_wrong_method():
    assert serve(build_server(), b"GET /nope HTTP/1.1\r\n\r\n")[0].startswith("HTTP/1.0 404")
    assert serve(build_server(), b"GET /set HTTP/1.1\r\n\r\n")[0].startswith("HTTP/1.0 405")


def test_oversized_body_is_rejected_without_reading_it():
    raw = b"POST /set HTTP/1.1\r\nContent-Length: %d\r\n\r\n" % (httpd.MAX_BODY_LENGTH + 1)
    assert serve(build_server(), raw)[0].startswith("HTTP/1.0 413")


def test_malformed_request_line():
    assert serve(build_server(), b"GARBAGE\r\n\r\n")[0].startswith("HTTP/1.0 400")


def test_handler_exception_becomes_500():
    head, body = serve(build_server(), b"GET /broken HTTP/1.1\r\n\r\n")
    assert head.startswith("HTTP/1.0 500")


def test_closed_connection_without_request_is_ignored():
    head, body = serve(build_server(), b"")
    assert head == "" and body == b""


def test_memory_error_while_sending_does_not_escape():
    server = httpd.Server()

    @server.route("/")
    async def page(request):
        def chunks():
            yield "start"
            raise MemoryError

        return httpd.Response(chunks())

    head, body = serve(server, b"GET / HTTP/1.1\r\n\r\n")
    assert head.startswith("HTTP/1.0 200")
    assert body == b"start"


def test_requests_are_served_one_at_a_time():
    server = httpd.Server()
    active = []
    peak = []

    @server.route("/")
    async def page(request):
        active.append(1)
        peak.append(len(active))
        await asyncio.sleep(0.01)
        active.pop()
        return "ok"

    async def run():
        async def one():
            reader = asyncio.StreamReader()
            reader.feed_data(b"GET / HTTP/1.1\r\n\r\n")
            reader.feed_eof()
            await server._serve(reader, FakeWriter())

        await asyncio.gather(*(one() for _ in range(5)))

    asyncio.run(run())
    assert len(peak) == 5
    assert max(peak) == 1


def test_content_length_header_only_when_known():
    server = httpd.Server()

    @server.route("/sized")
    async def sized(request):
        return httpd.Response(b"12345", length=5)

    head, body = serve(server, b"GET /sized HTTP/1.1\r\n\r\n")
    assert "Content-Length: 5\r\n" in head
    assert body == b"12345"
    head, _ = serve(build_server(), b"GET /page HTTP/1.1\r\n\r\n")
    assert "Content-Length" not in head
