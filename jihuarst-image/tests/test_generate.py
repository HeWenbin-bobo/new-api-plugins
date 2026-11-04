"""Offline tests: a local mock server stands in for the jihuarst gateway."""

from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
        })
        index = min(len(self.server.requests) - 1, len(self.server.statuses) - 1)
        status = self.server.statuses[index]
        if status == 200:
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
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
def fake_api(statuses):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.statuses = statuses
    server.requests = []
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
