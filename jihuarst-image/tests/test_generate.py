"""Offline tests: a local mock server stands in for the jihuarst gateway."""

from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import ssl
import tempfile
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "generate.py"
EXPECTED_URLS = [
    "http://222.211.75.198:3000",
    "https://gz-api.jihuarst.top:8443",
    "https://api.jihuarst.top",
    "https://sg-api.jihuarst.top",
]
GPT26_MODELS = [
    "gpt-image-2.6-sunburst", "gpt-image-2.6-exact", "gpt-image-2.6-flare",
]
EXPECTED_MODELS = GPT26_MODELS + [
    "gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2", "hunyuan-image-alpha",
]
EXPECTED_EDIT_MODELS = GPT26_MODELS + [
    "gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2", "hunyuan-image-alpha-edit",
]
IMAGE_BYTES = b"\x89PNG\r\n\x1a\njihuarst-test"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AF+p0hRAAAAAElFTkSuQmCC"
)


class Handler(BaseHTTPRequestHandler):
    """Records every request and replays a scripted list of HTTP statuses."""

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers["Content-Length"])
        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            payload = json.loads(raw)
            files: list[str] = []
        else:
            payload, files = self._parse_multipart(raw, content_type)
        self.server.requests.append({
            "path": self.path,
            "payload": payload,
            "files": files,
            "content_type": content_type,
            "authorization": self.headers.get("Authorization"),
        })
        if self.server.generation_redirect_target and len(self.server.requests) == 1:
            self.send_response(302)
            self.send_header("Location", self.server.generation_redirect_target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        index = min(len(self.server.requests) - 1, len(self.server.statuses) - 1)
        status = self.server.statuses[index]
        payload = self.server.payloads[index] if self.server.payloads is not None else None
        if payload is not None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        elif status == 200 and self.server.response_body is not None:
            body = self.server.response_body
        elif status == 200 and self.server.remote_image:
            image_url = f"http://127.0.0.1:{self.server.server_port}/image.png"
            body = json.dumps({
                "data": [{"url": image_url}] * self.server.image_count,
            }).encode()
        elif status == 200:
            body = json.dumps({
                "data": [{"b64_json": "data:image/png;base64,"
                          + base64.b64encode(IMAGE_BYTES).decode(),
                          "revised_prompt": "mock revised"}],
                "usage": {"charged_quota": 30},
            }).encode()
        else:
            body = b'{"error":{"message":"injected failure; sk-test-secret leaked"}}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        content_length = len(body)
        if status != 200 and self.server.truncate_error_body:
            content_length += 20
            body = body[:20]
        self.send_header("Content-Length", str(content_length))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path.startswith("/v1/images/"):
            self.server.generation_get_requests.append({
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
            })
            body = json.dumps({"data": [{"b64_json": base64.b64encode(IMAGE_BYTES).decode()}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.server.download_requests += 1
        self.server.download_authorization = self.headers.get("Authorization")
        self.server.download_headers = dict(self.headers.items())
        if self.server.redirect_target:
            self.send_response(302)
            self.send_header("Location", self.server.redirect_target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        status = self.server.download_status
        if isinstance(status, (list, tuple)):
            index = min(self.server.download_count, len(status) - 1)
            self.server.download_count += 1
            status = status[index]
        if status != 200:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(self.server.download_body)))
        self.end_headers()
        self.wfile.write(self.server.download_body)

    @staticmethod
    def _parse_multipart(raw: bytes, content_type: str) -> tuple[dict[str, str], list[str]]:
        boundary = content_type.split("boundary=", 1)[1].encode()
        fields: dict[str, str] = {}
        files: list[str] = []
        for section in raw.split(b"--" + boundary):
            if b"\r\n\r\n" not in section:
                continue
            header, body = section.split(b"\r\n\r\n", 1)
            body = body.rstrip(b"\r\n")
            disposition = header.decode("utf-8", "replace")
            name = disposition.split('name="', 1)[1].split('"', 1)[0]
            if "filename=" in disposition:
                files.append(name)
            else:
                fields[name] = body.decode()
        return fields, files

    def log_message(self, *args) -> None:  # silence the test server
        pass


class MemorySocket:
    def __init__(self, server):
        self.server = server
        self.request = io.BytesIO()
        self.response = None
        self.closed = False

    def sendall(self, data) -> None:
        if self.closed:
            raise OSError("memory socket is closed")
        self.request.write(data)

    def setsockopt(self, *args) -> None:
        pass

    def makefile(self, mode):
        if self.closed:
            raise OSError("memory socket is closed")
        self.request.seek(0)
        self.response = self.server._respond(self.request)
        self.response.seek(0)
        return self.response

    def close(self) -> None:
        self.closed = True


class MemoryHTTPServer:
    """Route real HTTP bytes through memory instead of Windows TCP ports."""

    servers = {}
    next_port = 20000

    def __init__(self, server_address, handler_class):
        host, port = server_address
        if port == 0:
            port = MemoryHTTPServer.next_port
            MemoryHTTPServer.next_port += 1
        self.server_address = (host, port)
        self.server_port = port
        self.RequestHandlerClass = handler_class
        self._requests = {}
        if self.server_address in self.servers:
            raise RuntimeError("offline fake address is already registered")
        self.servers[self.server_address] = self

    def server_close(self) -> None:
        if self.servers.get(self.server_address) is self:
            del self.servers[self.server_address]
        for streams in self._requests.values():
            for stream in streams:
                stream.close()
        self._requests.clear()

    @classmethod
    def connect(cls, address, timeout=None, source_address=None):
        server = cls.servers.get(address[:2])
        if server is None:
            raise OSError("offline fake received an unregistered host or port")
        return MemorySocket(server)

    def _respond(self, request):
        response = io.BytesIO()
        self._requests[id(request)] = (request, response)
        handler = self.RequestHandlerClass.__new__(self.RequestHandlerClass)
        handler.rfile = request
        handler.wfile = response
        handler.server = self
        handler.client_address = ("memory", 0)
        handler.close_connection = True
        handler.handle_one_request()
        return response


@contextmanager
def fake_server(handler_class=Handler):
    server = MemoryHTTPServer(("127.0.0.1", 0), handler_class)
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.server_close()


@contextmanager
def fake_api(statuses, *, remote_image=False, redirect_target=None, download_status=200,
             download_body=IMAGE_BYTES, response_body=None, payloads=None,
             truncate_error_body=False, image_count=1):
    with fake_server() as (server, url):
        server.statuses = statuses
        server.requests = []
        server.remote_image = remote_image
        server.image_count = image_count
        server.redirect_target = redirect_target
        server.generation_redirect_target = None
        server.generation_get_requests = []
        server.response_body = response_body
        server.payloads = payloads
        server.truncate_error_body = truncate_error_body
        server.download_status = download_status
        server.download_count = 0
        server.download_requests = 0
        server.download_body = download_body
        server.download_authorization = None
        yield server, url


def load_module():
    import sys

    spec = importlib.util.spec_from_file_location("jihuarst_generate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules, so the
    # module must be registered before execution.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GenerateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "jihuarst generate.py 尚未实现")
        self.module = load_module()
        self.module._IMAGE_OPENER = self.module._build_image_opener(allow_private=True)
        transport = mock.patch.object(
            self.module.socket, "create_connection", MemoryHTTPServer.connect,
        )
        transport.start()
        self.addCleanup(transport.stop)
        self.tempdir = tempfile.TemporaryDirectory()
        self.output = Path(self.tempdir.name) / "out.png"
        self.ref = Path(self.tempdir.name) / "ref.png"
        self.ref.write_bytes(PNG_1PX)
        self.mask = Path(self.tempdir.name) / "mask.png"
        self.mask.write_bytes(PNG_1PX)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_declared_priorities_match_requirements(self) -> None:
        self.assertEqual(EXPECTED_URLS, self.module.BASE_URLS)
        self.assertEqual(EXPECTED_MODELS, self.module.MODELS)

    def test_fake_http_never_opens_a_network_socket(self) -> None:
        with fake_api([200]) as (server, url), \
                mock.patch.object(self.module.socket, "socket",
                                  side_effect=AssertionError("unexpected network socket")):
            self.module.generate_image("cat", self.output, "test-key", [url], timeout=2)
        self.assertEqual(1, len(server.requests))
        with self.assertRaisesRegex(OSError, "unregistered"):
            self.module.socket.create_connection(("127.0.0.1", server.server_port), 2)

    def test_fake_http_unsupported_method_returns_501(self) -> None:
        with fake_api([200]) as (server, url):
            request = self.module.urllib.request.Request(url, data=b"{}", method="PATCH")
            with self.assertRaises(self.module.urllib.error.HTTPError) as raised:
                self.module._IMAGE_OPENER.open(request, timeout=2)
            with raised.exception:
                self.assertEqual(501, raised.exception.code)

    def test_fake_socket_rejects_use_after_close(self) -> None:
        server = MemoryHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        connection = MemoryHTTPServer.connect(server.server_address)
        connection.close()
        with self.assertRaises(OSError):
            connection.sendall(b"")
        with self.assertRaises(OSError):
            connection.makefile("rb")

    def test_default_text_chain_excludes_edit_only_model(self) -> None:
        with fake_api([500]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_image("cat", self.output, "test-key", [url], timeout=2)
        self.assertEqual(EXPECTED_MODELS,
                         [r["payload"]["model"] for r in server.requests])
        self.assertNotIn("hunyuan-image-alpha-edit",
                         [r["payload"]["model"] for r in server.requests])

    def test_default_reference_chain_uses_edit_model_last(self) -> None:
        with fake_api([500]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_image("paint it blue", self.output, "test-key",
                                           [url], timeout=2, references=[self.ref])
        self.assertEqual(EXPECTED_EDIT_MODELS,
                         [r["payload"]["model"] for r in server.requests])
        self.assertNotIn("hunyuan-image-alpha",
                         [r["payload"]["model"] for r in server.requests])

    def test_cli_reference_mode_uses_edit_chain(self) -> None:
        original_loader = self.module.load_api_key
        self.module.load_api_key = lambda: "test-key"
        self.addCleanup(setattr, self.module, "load_api_key", original_loader)
        with fake_api([500]) as (server, url):
            with self.assertLogs("jihuarst-image", level="ERROR"):
                status = self.module.main([
                    "paint it blue", "-r", str(self.ref), "--base-url", url, "--timeout", "2",
                ])
        self.assertEqual(1, status)
        self.assertEqual(EXPECTED_EDIT_MODELS,
                         [r["payload"]["model"] for r in server.requests])

    def test_cli_explicit_model_overrides_mode_chain(self) -> None:
        original_loader = self.module.load_api_key
        self.module.load_api_key = lambda: "test-key"
        self.addCleanup(setattr, self.module, "load_api_key", original_loader)
        cases = [
            ("generations", [], "hunyuan-image-alpha-edit"),
            ("edits", ["-r", str(self.ref)], "hunyuan-image-alpha"),
        ]
        for endpoint, mode_args, model in cases:
            with self.subTest(endpoint=endpoint), fake_api([200]) as (server, url):
                status = self.module.main([
                    "cat", *mode_args, "--model", model, "--base-url", url,
                    "--timeout", "2", "-o", str(self.output),
                ])
                self.assertEqual(0, status)
                self.assertEqual(1, len(server.requests))
                self.assertEqual(f"/v1/images/{endpoint}", server.requests[0]["path"])
                self.assertEqual(model, server.requests[0]["payload"]["model"])

    def test_text_mode_uses_generations_json(self) -> None:
        with fake_api([200]) as (server, url):
            result = self.module.generate_image("cat", self.output, "test-key",
                                                [url], EXPECTED_MODELS, 2)
        request = server.requests[0]
        self.assertEqual("/v1/images/generations", request["path"])
        self.assertEqual(GPT26_MODELS[0], request["payload"]["model"])
        self.assertEqual("url", request["payload"]["response_format"])
        # The Go gateway rejects a string here: `cannot unmarshal string into uint`.
        self.assertIsInstance(request["payload"]["n"], int)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual("generations", result.endpoint)

    def test_data_url_in_url_field_is_decoded(self) -> None:
        data_url = "data:image/png;base64," + base64.b64encode(IMAGE_BYTES).decode()
        images, failures = self.module._decode_images(
            {"data": [{"url": data_url}]}, 2, 1,
        )
        self.assertEqual([IMAGE_BYTES], images)
        self.assertEqual([], failures)

    def test_remote_image_url_is_downloaded_without_api_key(self) -> None:
        with fake_api([200], remote_image=True) as (server, url):
            self.module.generate_image("cat", self.output, "test-key",
                                       [url], ["hunyuan-image-alpha"], 2)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertIsNone(server.download_authorization)
        self.assertEqual("Mozilla/5.0", server.download_headers.get("User-Agent"))

    def test_private_image_url_is_rejected_before_download(self) -> None:
        self.module._IMAGE_OPENER = self.module._build_image_opener()
        with fake_api([200]) as (server, url):
            images, failures = self.module._decode_images(
                {"data": [{"url": url + "/image.png"}]}, 2, 1,
            )
        self.assertEqual([], images)
        self.assertIn("公网", failures[0])
        self.assertEqual(0, server.download_requests)

    def test_mixed_public_and_private_dns_results_are_rejected(self) -> None:
        self.module._IMAGE_OPENER = self.module._build_image_opener()
        answers = [
            (self.module.socket.AF_INET, self.module.socket.SOCK_STREAM, 6, "",
             ("127.0.0.1", 80)),
            (self.module.socket.AF_INET, self.module.socket.SOCK_STREAM, 6, "",
             ("8.8.8.8", 80)),
        ]
        with mock.patch.object(self.module.socket, "getaddrinfo", return_value=answers), \
                mock.patch.object(self.module.socket, "create_connection") as connect:
            with self.assertRaises(self.module._ImageDownloadError):
                self.module._IMAGE_OPENER.open("http://images.example/image.png", timeout=2)
        connect.assert_not_called()

    def test_multicast_image_addresses_are_rejected(self) -> None:
        self.module._IMAGE_OPENER = self.module._build_image_opener()
        for address in ("224.0.0.1", "239.255.255.255", "ff02::1", "ff0e::1"):
            family = self.module.socket.AF_INET6 if ":" in address else self.module.socket.AF_INET
            sockaddr = (address, 80, 0, 0) if ":" in address else (address, 80)
            answers = [(family, self.module.socket.SOCK_STREAM, 6, "", sockaddr)]
            with self.subTest(address=address), \
                    mock.patch.object(self.module.socket, "getaddrinfo", return_value=answers), \
                    mock.patch.object(self.module.socket, "create_connection") as connect:
                with self.assertRaises(self.module._ImageDownloadError):
                    self.module._IMAGE_OPENER.open("http://images.example/image.png", timeout=2)
                connect.assert_not_called()

    def test_private_redirect_target_is_rejected_under_production_policy(self) -> None:
        self.module._IMAGE_OPENER = self.module._build_image_opener()
        original_resolver = self.module._resolved_addresses

        def resolve_source(hostname, port, allow_private=False):
            if hostname == "public-images.example":
                return ["127.0.0.1"]
            return original_resolver(hostname, port, allow_private)

        with fake_api([200]) as (target, target_url), \
                fake_api([200], redirect_target=target_url + "/image.png") as (source, _):
            initial_url = f"http://public-images.example:{source.server_port}/image.png"
            with mock.patch.object(self.module, "_resolved_addresses", side_effect=resolve_source):
                images, failures = self.module._decode_images(
                    {"data": [{"url": initial_url}]}, 2, 1,
                )
        self.assertEqual([], images)
        self.assertTrue(failures)
        self.assertEqual(1, source.download_requests)
        self.assertEqual(0, target.download_requests)

    def test_oversized_image_download_falls_back_to_next_model(self) -> None:
        self.module.MAX_IMAGE_BYTES = len(IMAGE_BYTES)
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        with fake_api(
            [200, 200], remote_image=True, download_body=IMAGE_BYTES + b"x",
            payloads=[None, {"data": [{"b64_json": encoded}]}],
        ) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_rejected_redirect_response_is_closed(self) -> None:
        response = mock.Mock()
        request = self.module.urllib.request.Request("http://images.example/image.png")
        with self.assertRaises(self.module._ImageDownloadError):
            self.module._HTTPOnlyRedirectHandler().redirect_request(
                request, response, 302, "Found", {}, "ftp://127.0.0.1/image",
            )
        response.close.assert_called_once_with()

    def test_production_opener_disables_environment_proxies(self) -> None:
        with mock.patch.object(
            self.module.urllib.request, "getproxies",
            return_value={"http": "http://127.0.0.1:9"},
        ):
            opener = self.module._build_image_opener()
        self.assertFalse(any(
            isinstance(handler, self.module.urllib.request.ProxyHandler)
            for handler in opener.handlers
        ))

    def test_production_opener_requires_tls_certificates(self) -> None:
        opener = self.module._build_image_opener()
        handler = next(
            handler for handler in opener.handlers
            if isinstance(handler, self.module._PinnedHTTPSHandler)
        )
        self.assertTrue(handler._context.check_hostname)
        self.assertEqual(ssl.CERT_REQUIRED, handler._context.verify_mode)

    def test_https_connection_pins_address_and_preserves_sni(self) -> None:
        connection = self.module._PinnedHTTPSConnection("images.example", 443)
        plain_socket = mock.Mock()
        tls_socket = mock.Mock()
        connection._context = mock.Mock()
        connection._context.wrap_socket.return_value = tls_socket
        with mock.patch.object(self.module, "_resolved_addresses", return_value=["8.8.8.8"]), \
                mock.patch.object(self.module.socket, "create_connection",
                                  return_value=plain_socket) as connect:
            connection.connect()
        connect.assert_called_once_with(
            ("8.8.8.8", 443), connection.timeout, connection.source_address,
        )
        connection._context.wrap_socket.assert_called_once_with(
            plain_socket, server_hostname="images.example",
        )
        self.assertIs(tls_socket, connection.sock)

    def test_mixed_case_http_image_url_is_downloaded(self) -> None:
        with fake_api([200]) as (server, url):
            image_url = f"HTTP://127.0.0.1:{server.server_port}/image.png"
            images, failures = self.module._decode_images(
                {"data": [{"url": image_url}]}, 2, 1,
            )
        self.assertEqual([IMAGE_BYTES], images)
        self.assertEqual([], failures)
        self.assertIsNone(server.download_authorization)

    def test_non_http_image_redirect_is_rejected(self) -> None:
        with fake_api([200], remote_image=True,
                      redirect_target="ftp://127.0.0.1:1/image") as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image("cat", self.output, "test-key",
                                           [url], ["hunyuan-image-alpha"], 2)
        self.assertIn("图片重定向仅支持 HTTP(S)", str(raised.exception))
        self.assertFalse(self.output.exists())

    def test_http_image_redirect_is_followed_without_api_key(self) -> None:
        with fake_api([200]) as (target, target_url), \
                fake_api([200], remote_image=True,
                         redirect_target=target_url + "/image.png") as (source, url):
            self.module.generate_image("cat", self.output, "test-key",
                                       [url], ["hunyuan-image-alpha"], 2)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertIsNone(source.download_authorization)
        self.assertIsNone(target.download_authorization)

    def test_non_http_redirect_falls_back_to_next_model(self) -> None:
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        with fake_api(
            [200, 200], remote_image=True,
            redirect_target="ftp://127.0.0.1:1/image",
            payloads=[None, {"data": [{"b64_json": encoded}]}],
        ) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_non_image_download_falls_back_to_next_model(self) -> None:
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        with fake_api(
            [200, 200], remote_image=True, download_body=b"<html>upstream error</html>",
            payloads=[None, {"data": [{"b64_json": encoded}]}],
        ) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_download_error_reports_safe_status_or_exception_category(self) -> None:
        with fake_api([200], remote_image=True, download_status=403) as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image(
                    "cat", self.output, "test-key", [url], ["gpt-image-2.6-exact"], 2,
                )
        self.assertIn("图片下载失败 (HTTP 403)", str(raised.exception))
        self.assertNotIn("image.png", str(raised.exception))

        signed_url = "https://images.example/private.png?token=secret-token-value"
        module = self.module

        class FailingOpener:
            def open(self, request, timeout):
                raise module.urllib.error.URLError(
                    TimeoutError(f"handshake timed out; {signed_url}")
                )

        with mock.patch.object(self.module, "_IMAGE_OPENER", FailingOpener()):
            images, failures = self.module._decode_images(
                {"data": [{"url": signed_url}]}, 2, 1,
            )
        self.assertEqual([], images)
        self.assertIn("URLError", failures[0])
        self.assertIn("TimeoutError", failures[0])
        self.assertNotIn("private.png", failures[0])
        self.assertNotIn("secret-token-value", failures[0])

    def test_download_failure_falls_back_to_next_model(self) -> None:
        with fake_api([200, 200], remote_image=True,
                      download_status=[500, 200]) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_non_image_download_is_not_saved_as_success(self) -> None:
        with fake_api([200], remote_image=True,
                      download_body=b"<html>upstream error</html>") as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image("cat", self.output, "test-key",
                                           [url], ["hunyuan-image-alpha"], 2)
        self.assertIn("不是支持的图片", str(raised.exception))
        self.assertEqual(1, len(server.requests))
        self.assertFalse(self.output.exists())

    def test_cross_origin_generation_redirect_is_not_followed(self) -> None:
        with fake_api([200]) as (target, target_url), \
                fake_api([200]) as (fallback, fallback_url), \
                fake_api([200]) as (source, source_url):
            source.generation_redirect_target = target_url + "/v1/images/generations"
            result = self.module.generate_image(
                "cat", self.output, "test-key", [source_url, fallback_url],
                ["hunyuan-image-alpha"], 2,
            )
        self.assertEqual([], target.requests)
        self.assertEqual([], target.generation_get_requests)
        self.assertEqual(1, len(source.requests))
        self.assertEqual(1, len(fallback.requests))
        self.assertEqual(fallback_url, result.base_url)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())

    def test_same_origin_generation_redirect_is_followed(self) -> None:
        with fake_api([200]) as (server, url):
            server.generation_redirect_target = url + "/v1/images/generations"
            self.module.generate_image("cat", self.output, "test-key",
                                       [url], ["hunyuan-image-alpha"], 2)
        self.assertEqual(1, len(server.requests))
        self.assertEqual(1, len(server.generation_get_requests))
        self.assertEqual("Bearer test-key", server.requests[0]["authorization"])
        self.assertEqual("Bearer test-key",
                         server.generation_get_requests[0]["authorization"])
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())

    def test_truncated_http_error_body_tries_next_url(self) -> None:
        with fake_api([500], truncate_error_body=True) as (first, first_url), \
                fake_api([200]) as (second, second_url):
            try:
                result = self.module.generate_image(
                    "cat", self.output, "test-key", [first_url, second_url],
                    ["hunyuan-image-alpha"], 2,
                )
            except Exception as exc:
                self.fail(f"truncated error body aborted fallback: {type(exc).__name__}")
        self.assertEqual(second_url, result.base_url)
        self.assertEqual(1, len(first.requests))
        self.assertEqual(1, len(second.requests))
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())

    def test_non_image_encoded_images_fall_back_to_next_model(self) -> None:
        encoded = base64.b64encode(b"<html>not an image</html>").decode()
        cases = (
            ("base64", {"b64_json": encoded}),
            ("data_url", {"url": "data:image/png;base64," + encoded}),
        )
        for name, item in cases:
            with self.subTest(name=name), \
                    fake_api([200, 200], payloads=[{"data": [item]}, None]) as (server, url):
                self.output.unlink(missing_ok=True)
                result = self.module.generate_image(
                    "cat", self.output, "test-key", [url], ["first", "second"], 2,
                )
                self.assertEqual((self.output,), result.paths)
                self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
                self.assertEqual(2, len(server.requests))
                self.assertEqual("second", result.model)

    def test_oversized_encoded_images_fall_back_to_next_model(self) -> None:
        self.module.MAX_IMAGE_BYTES = len(IMAGE_BYTES)
        encoded = base64.b64encode(IMAGE_BYTES + b"x").decode()
        cases = (
            ("base64", {"b64_json": encoded}),
            ("data_url", {"url": "data:image/png;base64," + encoded}),
        )
        for name, item in cases:
            with self.subTest(name=name), \
                    fake_api([200, 200], payloads=[{"data": [item]}, None]) as (server, url):
                self.output.unlink(missing_ok=True)
                result = self.module.generate_image(
                    "cat", self.output, "test-key", [url], ["first", "second"], 2,
                )
                self.assertEqual((self.output,), result.paths)
                self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
                self.assertEqual(2, len(server.requests))
                self.assertEqual("second", result.model)

    def test_oversized_generation_response_tries_next_url(self) -> None:
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        second_body = json.dumps({"data": [{"b64_json": encoded}]}).encode()
        first_body = b" " * (len(second_body) + 1) + second_body
        self.module.MAX_RESPONSE_BYTES = len(second_body)
        with fake_api([200], response_body=first_body) as (first, first_url), \
                fake_api([200], response_body=second_body) as (second, second_url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [first_url, second_url],
                ["hunyuan-image-alpha"], 2,
            )
        self.assertEqual(second_url, result.base_url)
        self.assertEqual(1, len(first.requests))
        self.assertEqual(1, len(second.requests))
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())

    def test_svg_and_gif_are_saved_as_inert_bytes(self) -> None:
        cases = [
            ("svg", b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><path/></svg>'),
            ("gif", b"GIF89a" + b"test-animation"),
        ]
        for suffix, artifact in cases:
            with self.subTest(suffix=suffix), fake_api([200], payloads=[{
                "data": [{"b64_json": base64.b64encode(artifact).decode()}],
            }]) as (server, url):
                output = Path(self.tempdir.name) / f"out.{suffix}"
                result = self.module.generate_image(
                    "vector", output, "test-key", [url], ["gpt-image-2.6-exact"], 2,
                )
                self.assertEqual(artifact, output.read_bytes())
                self.assertEqual((output,), result.paths)

    def test_svg_prologs_are_recognized_without_xml_parsing(self) -> None:
        documents = [
            b'<?xml version="1.0"?><!-- comment --><svg/>',
            b'<!-- one --><!-- two --><svg/>',
            b'<!DOCTYPE svg><!-- comment --><svg/>',
            b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "value">]><svg/>',
            b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY bracket "]">]><svg/>',
        ]
        for document in documents:
            with self.subTest(document=document):
                self.module._validate_image_bytes(document)

    def test_svg_validation_rejects_non_svg_or_malformed_markup(self) -> None:
        invalid = [b"<html><svg/></html>", b"<svgx/>", b"<svg onload=alert(1)",
                   b"\xff<svg/>", b""]
        for artifact in invalid:
            with self.subTest(artifact=artifact):
                with self.assertRaises(self.module._ImageDownloadError):
                    self.module._validate_image_bytes(artifact)

    def test_reference_mode_uses_edits_multipart(self) -> None:
        with fake_api([200]) as (server, url):
            result = self.module.generate_image("paint it blue", self.output, "test-key",
                                                [url], EXPECTED_MODELS, 2,
                                                references=[self.ref])
        request = server.requests[0]
        self.assertEqual("/v1/images/edits", request["path"])
        self.assertTrue(request["content_type"].startswith("multipart/form-data"))
        self.assertEqual(["image"], request["files"])
        self.assertEqual("paint it blue", request["payload"]["prompt"])
        self.assertEqual("url", request["payload"]["response_format"])
        self.assertEqual("edits", result.endpoint)

    def test_multiple_references_use_array_field(self) -> None:
        second = Path(self.tempdir.name) / "second.png"
        second.write_bytes(PNG_1PX)
        with fake_api([200]) as (server, url):
            self.module.generate_image("combine", self.output, "test-key",
                                       [url], EXPECTED_MODELS, 2,
                                       references=[self.ref, second])
        self.assertEqual(["image[]", "image[]"], server.requests[0]["files"])

    def test_mask_is_sent_with_single_reference(self) -> None:
        with fake_api([200]) as (server, url):
            self.module.generate_image("repaint", self.output, "test-key",
                                       [url], EXPECTED_MODELS, 2,
                                       references=[self.ref], mask=self.mask)
        self.assertEqual(["image", "mask"], server.requests[0]["files"])

    def test_mask_with_multiple_references_is_rejected(self) -> None:
        second = Path(self.tempdir.name) / "second.png"
        second.write_bytes(PNG_1PX)
        with fake_api([200]) as (server, url):
            with self.assertRaises(ValueError):
                self.module.generate_image("x", self.output, "test-key",
                                           [url], EXPECTED_MODELS, 5,
                                           references=[self.ref, second], mask=self.mask)
        # The bad argument must fail before any request is attempted.
        self.assertEqual([], server.requests)

    def test_missing_reference_fails_fast_without_requests(self) -> None:
        missing = Path(self.tempdir.name) / "nope.png"
        with fake_api([200]) as (server, url):
            with self.assertRaises(ValueError) as raised:
                self.module.generate_image("x", self.output, "test-key",
                                           [url], EXPECTED_MODELS, 5,
                                           references=[missing])
        self.assertIn("参考图不存在", str(raised.exception))
        self.assertEqual([], server.requests)

    def test_output_format_is_forwarded_in_json_and_multipart(self) -> None:
        for references in ([], [self.ref]):
            with self.subTest(mode="edits" if references else "generations"), \
                    fake_api([200]) as (server, url):
                self.module.generate_image(
                    "vector", self.output, "test-key", [url],
                    ["gpt-image-2.6-exact"], 2, references=references,
                    new_fields={"output_format": "svg", "svg": {"model": "gpt-5.4-mini"}},
                )
                payload = server.requests[0]["payload"]
                self.assertEqual("svg", payload["output_format"])
                expected_svg = '{"model":"gpt-5.4-mini"}' if references else {"model": "gpt-5.4-mini"}
                self.assertEqual(expected_svg, payload["svg"])

    def test_vector_formats_select_gpt26_but_raster_format_does_not(self) -> None:
        with fake_api([500]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_image(
                    "animation", self.output, "test-key", [url], timeout=2,
                    new_fields={"output_format": "gif", "frame_count": 2},
                )
        self.assertEqual(GPT26_MODELS, [r["payload"]["model"] for r in server.requests])
        with fake_api([500]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_image(
                    "raster", self.output, "test-key", [url], timeout=2,
                    new_fields={"output_format": "jpeg"},
                )
        self.assertEqual(EXPECTED_MODELS, [r["payload"]["model"] for r in server.requests])

    def test_cli_output_format_choices_and_model_validation(self) -> None:
        original_loader = self.module.load_api_key
        self.module.load_api_key = lambda: "test-key"
        self.addCleanup(setattr, self.module, "load_api_key", original_loader)
        with fake_api([200]) as (server, url):
            status = self.module.main([
                "vector", "--model", "gpt-image-2.6-exact", "--base-url", url,
                "--output-format", "svg", "--svg", '{"model":"gpt-5.4-mini"}',
                "--timeout", "2", "-o", str(self.output),
            ])
        self.assertEqual(0, status)
        self.assertEqual("svg", server.requests[0]["payload"]["output_format"])
        for output_format, model in (("svg", "gpt-image-2.5"), ("tiff", "gpt-image-2.6-exact")):
            with self.subTest(output_format=output_format), fake_api([200]) as (server, url), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, "2"):
                    self.module.main([
                        "vector", "--model", model, "--base-url", url,
                        "--output-format", output_format,
                    ])
                self.assertEqual([], server.requests)

    def test_gpt26_fields_keep_native_json_types(self) -> None:
        fields = {
            "complexity": "low",
            "svg": {"model": "gpt-image-2.6-exact"},
            "frame_count": 2,
            "frame_duration_ms": 20,
            "markup": {"image_url": "https://example.com/markup.png"},
        }
        with fake_api([200]) as (server, url):
            self.module.generate_image("diagram", self.output, "test-key",
                                       [url], ["gpt-image-2.6-exact"], 2,
                                       new_fields=fields)
        self.assertEqual(fields, {
            key: server.requests[0]["payload"][key] for key in fields
        })

    def test_gpt26_json_values_preserve_exact_types_and_unicode(self) -> None:
        cases = [
            ("svg", True),
            ("svg", "vector"),
            ("svg", ["layer", 1]),
            ("markup", {"label": "保留图层"}),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value), fake_api([200]) as (server, url):
                self.module.generate_image(
                    "diagram", self.output, "test-key", [url],
                    ["gpt-image-2.6-exact"], 2, new_fields={name: value},
                )
                self.assertEqual(value, server.requests[0]["payload"][name])

    def test_gpt26_fields_and_local_markup_use_multipart(self) -> None:
        fields = {
            "complexity": "low", "svg": True, "frame_count": 2,
            "frame_duration_ms": 20,
        }
        with fake_api([200]) as (server, url):
            self.module.generate_image("annotate", self.output, "test-key",
                                       [url], ["gpt-image-2.6-exact"], 2,
                                       references=[self.ref], markup=self.mask,
                                       new_fields=fields)
        request = server.requests[0]
        self.assertEqual({
            "complexity": "low", "svg": "true", "frame_count": "2",
            "frame_duration_ms": "20",
        }, {key: request["payload"][key] for key in fields})
        self.assertEqual(["image", "markup"], request["files"])

    def test_markup_json_is_sent_as_markup_multipart_field(self) -> None:
        markup = {"image_url": "https://example.com/markup.png"}
        with fake_api([200]) as (server, url):
            self.module.generate_image("annotate", self.output, "test-key",
                                       [url], ["gpt-image-2.6-exact"], 2,
                                       references=[self.ref],
                                       new_fields={"markup": markup})
        self.assertEqual(json.dumps(markup, separators=(",", ":")),
                         server.requests[0]["payload"]["markup"])

    def test_gpt26_options_select_only_gpt26_models(self) -> None:
        with fake_api([500]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_image("diagram", self.output, "test-key",
                                           [url], timeout=2, new_fields={"svg": True})
        self.assertEqual(GPT26_MODELS,
                         [r["payload"]["model"] for r in server.requests])

    def test_local_markup_selects_only_gpt26_models(self) -> None:
        with fake_api([500]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_image("annotate", self.output, "test-key",
                                           [url], timeout=2, references=[self.ref],
                                           markup=self.mask)
        self.assertEqual(GPT26_MODELS,
                         [r["payload"]["model"] for r in server.requests])

    def test_markup_and_mask_are_rejected_before_requests(self) -> None:
        for options in (
            {"markup": self.mask},
            {"new_fields": {"markup": {"layer": 1}}},
        ):
            with self.subTest(options=options), fake_api([200]) as (server, url):
                with self.assertRaisesRegex(ValueError, "mask.*markup.*互斥"):
                    self.module.generate_image(
                        "annotate", self.output, "test-key", [url],
                        ["gpt-image-2.6-exact"], 2, references=[self.ref],
                        mask=self.mask, **options,
                    )
                self.assertEqual([], server.requests)

    def test_direct_markup_file_rejects_json_or_missing_reference(self) -> None:
        cases = [
            {"markup": self.mask},
            {"references": [self.ref], "markup": self.mask,
             "new_fields": {"markup": {"layer": 1}}},
        ]
        for options in cases:
            with self.subTest(options=options), fake_api([200]) as (server, url):
                with self.assertRaisesRegex(ValueError, "markup"):
                    self.module.generate_image(
                        "annotate", self.output, "test-key", [url],
                        ["gpt-image-2.6-exact"], 2, **options,
                    )
                self.assertEqual([], server.requests)

    def test_new_options_require_gpt26_model(self) -> None:
        with fake_api([200]) as (server, url):
            with self.assertRaisesRegex(ValueError, "gpt-image-2.6"):
                self.module.generate_image("diagram", self.output, "test-key",
                                           [url], ["gpt-image-2.5"], 2,
                                           new_fields={"svg": True})
        self.assertEqual([], server.requests)

    def test_cli_json_values_and_local_markup_are_forwarded(self) -> None:
        original_loader = self.module.load_api_key
        self.module.load_api_key = lambda: "test-key"
        self.addCleanup(setattr, self.module, "load_api_key", original_loader)
        cases = [
            (["--svg", '{"model":"vector"}', "--markup-json", '{"layer":1}'], "json"),
            (["--svg", "true", "--markup", str(self.mask)], "file"),
        ]
        for extra, markup_kind in cases:
            with self.subTest(markup=markup_kind), fake_api([200]) as (server, url):
                status = self.module.main([
                    "diagram", "-r", str(self.ref), "--model", "gpt-image-2.6-exact",
                    "--base-url", url, "--complexity", "low", "--frame-count", "2",
                    "--frame-duration-ms", "20", "--timeout", "2",
                    "-o", str(self.output), *extra,
                ])
                self.assertEqual(0, status)
                payload = server.requests[0]["payload"]
                self.assertEqual("low", payload["complexity"])
                self.assertEqual("2", payload["frame_count"])
                self.assertEqual("20", payload["frame_duration_ms"])
                if markup_kind == "json":
                    self.assertEqual('{"model":"vector"}', payload["svg"])
                    self.assertEqual('{"layer":1}', payload["markup"])
                else:
                    self.assertEqual("true", payload["svg"])
                    self.assertEqual(["image", "markup"], server.requests[0]["files"])

    def test_cli_markup_json_uses_generation_json_without_references(self) -> None:
        original_loader = self.module.load_api_key
        self.module.load_api_key = lambda: "test-key"
        self.addCleanup(setattr, self.module, "load_api_key", original_loader)
        markup = {"layer": 1, "label": "保留"}
        with fake_api([200]) as (server, url):
            status = self.module.main([
                "annotate", "--model", "gpt-image-2.6-exact", "--base-url", url,
                "--markup-json", json.dumps(markup, ensure_ascii=False),
                "--timeout", "2", "-o", str(self.output),
            ])
        self.assertEqual(0, status)
        self.assertEqual("/v1/images/generations", server.requests[0]["path"])
        self.assertEqual(markup, server.requests[0]["payload"]["markup"])

    def test_invalid_markup_combinations_fail_before_requests(self) -> None:
        cases = [
            (["--markup", str(self.mask)], "需要参考图"),
            (["-r", str(self.ref), "--markup", str(self.mask),
              "--markup-json", "{}"], "互斥"),
            (["-r", str(self.ref), "--mask", str(self.mask),
              "--markup-json", "{}"], "互斥"),
            (["-r", str(self.ref), "--mask", str(self.mask),
              "--markup", str(self.mask)], "互斥"),
            (["-r", str(self.ref), "--markup-json", "not-json"], "JSON"),
            (["-r", str(self.ref), "--markup-json", "null"], "null"),
            (["-r", str(self.ref), "--frame-count", "-1"], "2..16"),
            (["-r", str(self.ref), "--frame-count", "1"], "2..16"),
            (["-r", str(self.ref), "--frame-count", "17"], "2..16"),
            (["-r", str(self.ref), "--frame-duration-ms", "0"], ">= 20"),
            (["-r", str(self.ref), "--frame-duration-ms", "19"], ">= 20"),
            (["--complexity", "   "], "complexity"),
            (["--complexity", "ultra"], "complexity"),
            (["--timeout", "0"], "timeout"),
            (["--timeout", "-1"], "timeout"),
            (["--timeout", "nan"], "timeout"),
            (["--timeout", "inf"], "timeout"),
            (["--svg", "NaN"], "JSON"),
            (["--svg", '{"value":Infinity}'], "JSON"),
        ]
        for extra, message in cases:
            with self.subTest(extra=extra), fake_api([200]) as (server, url), \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                arguments = [
                    "diagram", "--model", "gpt-image-2.6-exact",
                    "--base-url", url, *extra,
                ]
                with self.assertRaisesRegex(SystemExit, "2"):
                    self.module.main(arguments)
                self.assertIn(message, stderr.getvalue())
                self.assertEqual([], server.requests)

    def test_size_quality_and_fidelity_are_forwarded(self) -> None:
        with fake_api([200]) as (server, url):
            self.module.generate_image("cat", self.output, "test-key",
                                       [url], EXPECTED_MODELS, 2,
                                       references=[self.ref], size="1536x1024",
                                       quality="high", input_fidelity="high")
        payload = server.requests[0]["payload"]
        self.assertEqual("1536x1024", payload["size"])
        self.assertEqual("high", payload["quality"])
        self.assertEqual("high", payload["input_fidelity"])

    def test_tries_every_model_on_preferred_url_before_succeeding(self) -> None:
        with fake_api([500, 500, 500, 500, 500, 500, 200]) as (server, url):
            result = self.module.generate_image("cat", self.output, "test-key",
                                               [url], EXPECTED_MODELS, 2)
        self.assertEqual(EXPECTED_MODELS, [r["payload"]["model"] for r in server.requests])
        self.assertTrue(all(r["path"] == "/v1/images/generations" for r in server.requests))
        self.assertEqual((url, "hunyuan-image-alpha"), (result.base_url, result.model))

    def test_exhausts_models_before_switching_url(self) -> None:
        with fake_api([500]) as (first, first_url), fake_api([200]) as (second, second_url):
            result = self.module.generate_image("cat", self.output, "test-key",
                                               [first_url, second_url],
                                               EXPECTED_MODELS, 2)
        self.assertEqual(EXPECTED_MODELS, [r["payload"]["model"] for r in first.requests])
        self.assertEqual([GPT26_MODELS[0]], [r["payload"]["model"] for r in second.requests])
        self.assertEqual(second_url, result.base_url)

    def test_reports_unavailable_only_after_all_combinations_fail(self) -> None:
        with fake_api([500]) as (a, a_url), fake_api([500]) as (b, b_url), \
                fake_api([500]) as (c, c_url), fake_api([500]) as (d, d_url):
            urls = [a_url, b_url, c_url, d_url]
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image("cat", self.output, "test-key",
                                           urls, EXPECTED_MODELS, 2)
        message = str(raised.exception)
        self.assertRegex(message, rf"{len(urls) * len(EXPECTED_MODELS)}.*均失败")
        self.assertIn("未能完整保存所请求的图片", message)
        self.assertIn("重复费用", message)
        self.assertNotIn("sk-test-secret", message)
        self.assertFalse(self.output.exists())

    def test_all_paid_delivery_failures_report_both_models_and_charge_risk(self) -> None:
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        with fake_api([200, 200], payloads=[
            {"data": {"b64_json": encoded}},
            {"data": [{"url": "http://[::1"}]},
        ]) as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image(
                    "cat", self.output, "test-key", [url], ["first", "second"], 2,
                )
        message = str(raised.exception)
        self.assertEqual(2, len(server.requests))
        self.assertIn("first", message)
        self.assertIn("second", message)
        self.assertIn("重复费用", message)
        self.assertNotIn("test-key", message)
        self.assertFalse(self.output.exists())

    def test_empty_entries_fall_back_without_paid_delivery_error(self) -> None:
        with fake_api([200, 200], payloads=[{"data": []}, {"data": []}]) as (server, url):
            with self.assertRaisesRegex(
                    RuntimeError, r"first: ValueError: API 未返回任何图片"):
                self.module.generate_image(
                    "cat", self.output, "test-key", [url], ["first", "second"], 2,
                )
        self.assertEqual(2, len(server.requests))
        self.assertFalse(self.output.exists())

    def test_missing_or_null_data_preserves_empty_response_fallback(self) -> None:
        for response in ({}, {"data": None}):
            with self.subTest(response=response), fake_api([200], payloads=[response]) as (server, url):
                with self.assertRaisesRegex(
                        RuntimeError, r"first: ValueError: API 未返回任何图片"):
                    self.module.generate_image(
                        "cat", self.output, "test-key", [url], ["first"], 2,
                    )
                self.assertEqual(1, len(server.requests))
                self.assertFalse(self.output.exists())
                self.assertEqual(([], []), self.module._decode_images(response, 2, 1))

    def test_falsy_non_array_data_is_a_paid_delivery_error(self) -> None:
        for value in (False, 0, "", {}):
            with self.subTest(value=value), fake_api([200], payloads=[{
                "data": value,
            }]) as (server, url):
                with self.assertRaisesRegex(RuntimeError, "data 不是数组"):
                    self.module.generate_image(
                        "cat", self.output, "test-key", [url], ["first"], 2,
                    )
                self.assertEqual(1, len(server.requests))
                self.assertFalse(self.output.exists())

    def test_empty_entries_fall_back_to_next_model(self) -> None:
        with fake_api([200, 200], payloads=[{"data": []}, None]) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_incomplete_count_falls_back_to_next_model(self) -> None:
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        with fake_api([200, 200], payloads=[
            {"data": [{"b64_json": encoded}]},
            {"data": [{"b64_json": encoded}, {"b64_json": encoded}]},
        ]) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2, count=2,
            )
        targets = tuple(self.module._output_targets(self.output, 2))
        self.assertEqual(targets, result.paths)
        self.assertTrue(all(path.read_bytes() == IMAGE_BYTES for path in targets))
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_extra_entries_fall_back_without_saving_partial_delivery(self) -> None:
        encoded = base64.b64encode(b"GIF89aanimation").decode()
        with fake_api([200, 200], payloads=[
            {"data": [{"b64_json": encoded}, {"b64_json": encoded}]},
            {"data": [{"b64_json": encoded}]},
        ]) as (server, url):
            result = self.module.generate_image(
                "animate", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)
        self.assertEqual(b"GIF89aanimation", self.output.read_bytes())

    def test_count_above_one_writes_numbered_files(self) -> None:
        module_response = [{"b64_json": base64.b64encode(IMAGE_BYTES).decode()}] * 2

        class TwoImageHandler(Handler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                body = json.dumps({"data": module_response}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = MemoryHTTPServer(("127.0.0.1", 0), TwoImageHandler)
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            result = self.module.generate_image("cat", self.output, "test-key",
                                               [url], EXPECTED_MODELS, 2, count=2)
        finally:
            server.server_close()
        self.assertEqual(2, len(result.paths))
        self.assertEqual(Path(self.tempdir.name) / "out-1.png", result.paths[0])
        self.assertEqual(Path(self.tempdir.name) / "out-2.png", result.paths[1])
        self.assertTrue(result.paths[1].is_file())

    def test_count_outside_supported_range_fails_without_requests(self) -> None:
        with fake_api([200]) as (server, url):
            for count in (0, -1, self.module.MAX_IMAGE_COUNT + 1):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    self.module.generate_image("cat", self.output, "test-key",
                                               [url], ["gpt-image-2.5"], 2, count=count)
        self.assertEqual([], server.requests)

    def test_aggregate_image_limit_rejects_later_image(self) -> None:
        response = {"data": [
            {"b64_json": base64.b64encode(IMAGE_BYTES).decode()},
            {"b64_json": base64.b64encode(IMAGE_BYTES + b"second").decode()},
        ]}
        images, failures = self.module._decode_images(
            response, 2, 2, max_total_bytes=len(IMAGE_BYTES),
        )
        self.assertEqual([IMAGE_BYTES], images)
        self.assertEqual(1, len(failures))
        self.assertIn("总大小", failures[0])

    def test_atomic_write_failure_preserves_existing_outputs(self) -> None:
        first, second = self.module._output_targets(self.output, 2)
        first.write_bytes(b"first-original")
        second.write_bytes(b"second-original")
        with mock.patch.object(self.module.os, "replace", side_effect=PermissionError("read-only")):
            with self.assertRaises(PermissionError):
                self.module._write_images_atomically([first, second], [IMAGE_BYTES, IMAGE_BYTES])
        self.assertEqual(b"first-original", first.read_bytes())
        self.assertEqual(b"second-original", second.read_bytes())
        self.assertEqual([], list(Path(self.tempdir.name).glob("*.tmp")))

    def test_generate_output_error_falls_back_to_next_model(self) -> None:
        self.output.write_bytes(b"original")
        real_replace = self.module.os.replace
        replace_calls = 0

        def fail_first_replace(source, target):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 1:
                raise PermissionError("read-only")
            return real_replace(source, target)

        with fake_api([200, 200]) as (server, url):
            with mock.patch.object(self.module.os, "replace", side_effect=fail_first_replace):
                result = self.module.generate_image(
                    "cat", self.output, "test-key", [url], ["first", "second"], 2,
                )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)
        self.assertEqual([], list(Path(self.tempdir.name).glob("*.tmp")))

    def test_non_list_data_payload_falls_back_to_next_model(self) -> None:
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        with fake_api(
            [200, 200], payloads=[{"data": {"b64_json": encoded}}, None],
        ) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_malformed_image_url_falls_back_to_next_model(self) -> None:
        with fake_api(
            [200, 200], payloads=[{"data": [{"url": "http://[::1"}]}, None],
        ) as (server, url):
            result = self.module.generate_image(
                "cat", self.output, "test-key", [url], ["first", "second"], 2,
            )
        self.assertEqual((self.output,), result.paths)
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual(2, len(server.requests))
        self.assertEqual("second", result.model)

    def test_later_replace_failure_restores_earlier_output(self) -> None:
        first, second = self.module._output_targets(self.output, 2)
        first.write_bytes(b"first-original")
        second.write_bytes(b"second-original")
        real_replace = self.module.os.replace
        replaced_sources = []
        failed_once = False

        def fail_second_replace(source, target):
            nonlocal failed_once
            if Path(target) == second and not failed_once:
                failed_once = True
                raise PermissionError("second target locked")
            replaced_sources.append(Path(source))
            return real_replace(source, target)

        with mock.patch.object(self.module.os, "replace", side_effect=fail_second_replace):
            with self.assertRaises(PermissionError):
                self.module._write_images_atomically([first, second], [IMAGE_BYTES, IMAGE_BYTES])
        self.assertEqual(b"first-original", first.read_bytes())
        self.assertEqual(b"second-original", second.read_bytes())
        restored_sources = [
            source for source in replaced_sources if ".backup-" in source.name
        ]
        self.assertEqual({first, second}, {
            source.with_name(source.name.split(".backup-", 1)[0])
            for source in restored_sources
        })
        self.assertEqual([], list(Path(self.tempdir.name).glob("*.tmp")))
        self.assertEqual([], list(Path(self.tempdir.name).glob("*.backup-*")))

    def test_successful_replacement_removes_backup(self) -> None:
        self.output.write_bytes(b"original")
        self.module._write_images_atomically([self.output], [IMAGE_BYTES])
        self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
        self.assertEqual([], list(Path(self.tempdir.name).glob("*.tmp")))

    def test_failed_rollback_preserves_original_backup(self) -> None:
        self.output.write_bytes(b"original")
        real_replace = self.module.os.replace

        def fail_target_replace(source, target):
            if Path(target) == self.output:
                raise PermissionError("target locked")
            return real_replace(source, target)

        with fake_api([200, 200]) as (server, url):
            with mock.patch.object(self.module.os, "replace", side_effect=fail_target_replace):
                with self.assertRaises(RuntimeError) as raised:
                    self.module.generate_image(
                        "cat", self.output, "test-key", [url], ["first", "second"], 2,
                    )
        backups = list(Path(self.tempdir.name).glob("*.backup-*"))
        self.assertEqual(1, len(backups))
        self.assertEqual(b"original", backups[0].read_bytes())
        self.assertIn(str(backups[0]), str(raised.exception))
        self.assertEqual(2, len(server.requests))

    def test_revised_prompt_is_surfaced(self) -> None:
        with fake_api([200]) as (server, url):
            result = self.module.generate_image("cat", self.output, "test-key",
                                               [url], EXPECTED_MODELS, 2)
        self.assertEqual("mock revised", result.revised_prompt)

    def test_load_api_key_uses_temporary_config(self) -> None:
        original_path = self.module.CONFIG_PATH
        self.module.CONFIG_PATH = Path(self.tempdir.name) / "config.json"
        self.addCleanup(setattr, self.module, "CONFIG_PATH", original_path)
        self.module.CONFIG_PATH.write_text('{"api_key": " test-fixture-key "}',
                                           encoding="utf-8")
        self.assertEqual("test-fixture-key", self.module.load_api_key())
        self.module.CONFIG_PATH.write_text('{"api_key": ""}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.module.load_api_key()


if __name__ == "__main__":
    unittest.main()
