"""Offline tests: a local mock server stands in for the jihuarst gateway."""

from __future__ import annotations

import base64
import importlib.util
import json
import ssl
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
EXPECTED_MODELS = [
    "gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2", "hunyuan-image-alpha",
]
EXPECTED_EDIT_MODELS = [
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
        if status == 200 and self.server.response_body is not None:
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


@contextmanager
def fake_api(statuses, *, remote_image=False, redirect_target=None, download_status=200,
             download_body=IMAGE_BYTES, response_body=None, truncate_error_body=False,
             image_count=1):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.statuses = statuses
    server.requests = []
    server.remote_image = remote_image
    server.image_count = image_count
    server.redirect_target = redirect_target
    server.generation_redirect_target = None
    server.generation_get_requests = []
    server.response_body = response_body
    server.truncate_error_body = truncate_error_body
    server.download_status = download_status
    server.download_count = 0
    server.download_requests = 0
    server.download_body = download_body
    server.download_authorization = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


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
        self.assertEqual("gpt-image-2.5", request["payload"]["model"])
        self.assertEqual("b64_json", request["payload"]["response_format"])
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

    def test_oversized_image_download_is_terminal(self) -> None:
        self.module.MAX_IMAGE_BYTES = len(IMAGE_BYTES)
        with fake_api([200], remote_image=True,
                      download_body=IMAGE_BYTES + b"x") as (first, first_url), \
                fake_api([200], remote_image=True) as (second, second_url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image(
                    "cat", self.output, "test-key", [first_url, second_url],
                    ["hunyuan-image-alpha"], 2,
                )
        self.assertIn("过大", str(raised.exception))
        self.assertEqual(1, len(first.requests))
        self.assertEqual(0, len(second.requests))
        self.assertFalse(self.output.exists())

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

    def test_non_http_redirect_is_terminal(self) -> None:
        with fake_api([200], remote_image=True,
                      redirect_target="ftp://127.0.0.1:1/image") as (first, first_url), \
                fake_api([200], remote_image=True) as (second, second_url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image(
                    "cat", self.output, "test-key", [first_url, second_url],
                    ["hunyuan-image-alpha"], 2,
                )
        self.assertIn("图片重定向仅支持 HTTP(S)", str(raised.exception))
        self.assertEqual(1, len(first.requests))
        self.assertEqual(0, len(second.requests))
        self.assertFalse(self.output.exists())

    def test_non_image_download_is_terminal(self) -> None:
        with fake_api([200], remote_image=True,
                      download_body=b"<html>upstream error</html>") as (first, first_url), \
                fake_api([200], remote_image=True) as (second, second_url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image(
                    "cat", self.output, "test-key", [first_url, second_url],
                    ["hunyuan-image-alpha"], 2,
                )
        self.assertIn("不是支持的图片", str(raised.exception))
        self.assertEqual(1, len(first.requests))
        self.assertEqual(0, len(second.requests))
        self.assertFalse(self.output.exists())

    def test_download_failure_does_not_try_next_model(self) -> None:
        with fake_api([200, 200], remote_image=True,
                      download_status=[500, 200]) as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image(
                    "cat", self.output, "test-key", [url],
                    ["hunyuan-image-alpha", "gpt-image-2"], 2,
                )
        self.assertEqual(1, len(server.requests))
        self.assertIn("计费", str(raised.exception))
        self.assertFalse(self.output.exists())

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

    def test_non_image_encoded_images_are_terminal(self) -> None:
        encoded = base64.b64encode(b"<html>not an image</html>").decode()
        cases = (
            ("base64", {"b64_json": encoded}),
            ("data_url", {"url": "data:image/png;base64," + encoded}),
        )
        for name, item in cases:
            body = json.dumps({"data": [item]}).encode()
            with self.subTest(name=name), \
                    fake_api([200], response_body=body) as (first, first_url), \
                    fake_api([200]) as (second, second_url):
                self.output.unlink(missing_ok=True)
                with self.assertRaises(RuntimeError) as raised:
                    self.module.generate_image(
                        "cat", self.output, "test-key", [first_url, second_url],
                        ["hunyuan-image-alpha"], 2,
                    )
                self.assertIn("不是支持的图片", str(raised.exception))
                self.assertEqual(1, len(first.requests))
                self.assertEqual(0, len(second.requests))
                self.assertFalse(self.output.exists())

    def test_oversized_encoded_images_are_terminal(self) -> None:
        self.module.MAX_IMAGE_BYTES = len(IMAGE_BYTES)
        encoded = base64.b64encode(IMAGE_BYTES + b"x").decode()
        cases = (
            ("base64", {"b64_json": encoded}),
            ("data_url", {"url": "data:image/png;base64," + encoded}),
        )
        for name, item in cases:
            body = json.dumps({"data": [item]}).encode()
            with self.subTest(name=name), \
                    fake_api([200], response_body=body) as (first, first_url), \
                    fake_api([200]) as (second, second_url):
                self.output.unlink(missing_ok=True)
                with self.assertRaises(RuntimeError) as raised:
                    self.module.generate_image(
                        "cat", self.output, "test-key", [first_url, second_url],
                        ["hunyuan-image-alpha"], 2,
                    )
                self.assertIn("过大", str(raised.exception))
                self.assertEqual(1, len(first.requests))
                self.assertEqual(0, len(second.requests))
                self.assertFalse(self.output.exists())

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
        with fake_api([500, 500, 500, 200]) as (server, url):
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
        self.assertEqual(["gpt-image-2.5"], [r["payload"]["model"] for r in second.requests])
        self.assertEqual(second_url, result.base_url)

    def test_reports_unavailable_only_after_all_combinations_fail(self) -> None:
        with fake_api([500]) as (a, a_url), fake_api([500]) as (b, b_url), \
                fake_api([500]) as (c, c_url), fake_api([500]) as (d, d_url):
            urls = [a_url, b_url, c_url, d_url]
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_image("cat", self.output, "test-key",
                                           urls, EXPECTED_MODELS, 2)
        self.assertRegex(str(raised.exception),
                         rf"{len(urls) * len(EXPECTED_MODELS)}.*均失败.*无法使用")
        self.assertNotIn("sk-test-secret", str(raised.exception))
        self.assertFalse(self.output.exists())

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

        server = ThreadingHTTPServer(("127.0.0.1", 0), TwoImageHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            result = self.module.generate_image("cat", self.output, "test-key",
                                               [url], EXPECTED_MODELS, 2, count=2)
        finally:
            server.shutdown()
            thread.join()
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

    def test_generate_output_error_is_terminal_and_preserves_output(self) -> None:
        self.output.write_bytes(b"original")
        with fake_api([200]) as (server, url):
            with mock.patch.object(
                self.module.os, "replace", side_effect=PermissionError("read-only"),
            ):
                with self.assertRaises(self.module._PaidDeliveryError) as raised:
                    self.module.generate_image(
                        "cat", self.output, "test-key", [url], ["gpt-image-2.5"], 2,
                    )
        self.assertIn("写入输出文件失败", str(raised.exception))
        self.assertIn(str(self.output.parent), str(raised.exception))
        self.assertEqual(1, len(server.requests))
        self.assertEqual(b"original", self.output.read_bytes())
        self.assertEqual([], list(Path(self.tempdir.name).glob("*.tmp")))

    def test_non_list_data_payload_is_terminal(self) -> None:
        encoded = base64.b64encode(IMAGE_BYTES).decode()
        body = json.dumps({"data": {"b64_json": encoded}}).encode()
        with fake_api([200], response_body=body) as (first, first_url), \
                fake_api([200]) as (second, second_url):
            with self.assertRaises(self.module._PaidDeliveryError) as raised:
                self.module.generate_image(
                    "cat", self.output, "test-key", [first_url, second_url],
                    ["hunyuan-image-alpha"], 2,
                )
        self.assertIn("已计费", str(raised.exception))
        self.assertEqual(1, len(first.requests))
        self.assertEqual(0, len(second.requests))
        self.assertFalse(self.output.exists())

    def test_malformed_image_url_is_terminal(self) -> None:
        body = json.dumps({"data": [{"url": "http://[::1"}]}).encode()
        with fake_api([200], response_body=body) as (first, first_url), \
                fake_api([200]) as (second, second_url):
            with self.assertRaises(self.module._PaidDeliveryError):
                self.module.generate_image(
                    "cat", self.output, "test-key", [first_url, second_url],
                    ["hunyuan-image-alpha"], 2,
                )
        self.assertEqual(1, len(first.requests))
        self.assertEqual(0, len(second.requests))
        self.assertFalse(self.output.exists())

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

        with fake_api([200]) as (server, url):
            with mock.patch.object(self.module.os, "replace", side_effect=fail_target_replace):
                with self.assertRaises(self.module._PaidDeliveryError) as raised:
                    self.module.generate_image(
                        "cat", self.output, "test-key", [url], ["gpt-image-2.5"], 2,
                    )
        backups = list(Path(self.tempdir.name).glob("*.backup-*"))
        self.assertEqual(1, len(backups))
        self.assertEqual(b"original", backups[0].read_bytes())
        self.assertIn(str(backups[0]), str(raised.exception))
        self.assertEqual(1, len(server.requests))

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
