import io
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_decide  # noqa: E402


class FakeHandler(BaseHTTPRequestHandler):
    server_version = "FakeNewAPI/1.0"

    def log_message(self, *args):  # Keep test output clean.
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = None
        self.server.requests.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "body": body,
            }
        )

        if self.server.mode == "unauthorized":
            self.send_json(401, {"error": {"message": "Invalid token", "type": "new_api_error"}})
            return

        response = json.loads((ROOT / "assets/response-multi.json").read_text(encoding="utf-8"))
        if self.server.mode == "bad_sum":
            response["answers"]["action"]["probabilities"] = {
                "read": 0.5,
                "write": 0.4,
                "delete": 0.2,
            }
        elif self.server.mode == "bad_usage":
            response["usage"]["output_tokens"] = 1
        self.send_json(200, response)

    def send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeServer:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        self.httpd.daemon_threads = True
        self.httpd.mode = "ok"
        self.httpd.requests = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    @property
    def base_url(self):
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"


class LocalDecideTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer().start()
        self.request = json.loads(
            (ROOT / "assets/request-multi.json").read_text(encoding="utf-8")
        )

    def tearDown(self):
        self.server.stop()

    def test_choice_and_noul_success(self):
        result = local_decide.decide(
            self.request,
            base_url=self.server.base_url,
            api_key="test-token",
            timeout=5,
        )
        self.assertEqual(result["answers"]["action"]["choice"], "read")
        self.assertEqual(result["answers"]["action"]["probabilities"]["read"], 0.9997)
        self.assertEqual(result["answers"]["keep"]["noul"], 0.91)
        self.assertEqual(result["usage"]["output_tokens"], 0)

        sent = self.server.httpd.requests[-1]
        self.assertEqual(sent["path"], "/v1/systemone")
        self.assertEqual(sent["auth"], "Bearer test-token")
        self.assertEqual(sent["body"]["model"], "Piccolo-4B-Q4_K_M")

    def test_base_url_with_v1_suffix(self):
        local_decide.decide(
            self.request,
            base_url=self.server.base_url + "/v1/",
            api_key="test-token",
            timeout=5,
        )
        self.assertEqual(self.server.httpd.requests[-1]["path"], "/v1/systemone")

    def test_model_override(self):
        local_decide.decide(
            self.request,
            base_url=self.server.base_url,
            api_key="test-token",
            timeout=5,
            model="Piccolo-9B-Q8_0",
        )
        self.assertEqual(
            self.server.httpd.requests[-1]["body"]["model"], "Piccolo-9B-Q8_0"
        )

    def test_jev_model_is_accepted(self):
        self.request["model"] = "Jev-Omni-12B-Q4_K_M"
        local_decide.decide(
            self.request,
            base_url=self.server.base_url,
            api_key="test-token",
            timeout=5,
        )
        self.assertEqual(
            self.server.httpd.requests[-1]["body"]["model"], "Jev-Omni-12B-Q4_K_M"
        )

    def test_unauthorized_is_http_error(self):
        self.server.httpd.mode = "unauthorized"
        with self.assertRaises(local_decide.ClientError) as caught:
            local_decide.decide(
                self.request,
                base_url=self.server.base_url,
                api_key="wrong-token",
                timeout=5,
            )
        self.assertEqual(caught.exception.exit_code, local_decide.EXIT_HTTP)
        self.assertIn("401", str(caught.exception))

    def test_probabilities_must_sum_to_one(self):
        self.server.httpd.mode = "bad_sum"
        with self.assertRaises(local_decide.ClientError) as caught:
            local_decide.decide(
                self.request,
                base_url=self.server.base_url,
                api_key="test-token",
                timeout=5,
            )
        self.assertEqual(caught.exception.exit_code, local_decide.EXIT_RESPONSE)

    def test_output_tokens_must_be_zero(self):
        self.server.httpd.mode = "bad_usage"
        with self.assertRaises(local_decide.ClientError) as caught:
            local_decide.decide(
                self.request,
                base_url=self.server.base_url,
                api_key="test-token",
                timeout=5,
            )
        self.assertEqual(caught.exception.exit_code, local_decide.EXIT_RESPONSE)

    def test_invalid_request_is_rejected_before_http(self):
        self.request["state"] = ""
        with self.assertRaises(local_decide.ClientError) as caught:
            local_decide.decide(
                self.request,
                base_url=self.server.base_url,
                api_key="test-token",
                timeout=5,
            )
        self.assertEqual(caught.exception.exit_code, local_decide.EXIT_INPUT)
        self.assertEqual(self.server.httpd.requests, [])

    def test_cli_outputs_elapsed_ms(self):
        stdout = io.StringIO()
        with patch.dict(os.environ, {"NEW_API_KEY": "test-token"}, clear=False):
            with patch("sys.stdout", stdout):
                code = local_decide.main(
                    [
                        "--request",
                        str(ROOT / "assets/request-multi.json"),
                        "--base-url",
                        self.server.base_url,
                        "--timeout",
                        "5",
                    ]
                )
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["request_model"], "Piccolo-4B-Q4_K_M")
        self.assertIsInstance(output["elapsed_ms"], (int, float))
        self.assertGreaterEqual(output["elapsed_ms"], 0)


if __name__ == "__main__":
    unittest.main()
