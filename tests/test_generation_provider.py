"""Offline provider protocol tests: real loopback HTTP, fixture keys only."""

import base64
import io
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import request

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src.generation_provider as gp
from src import canvas_assets

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
}
MESSAGES = [
    {"role": "system", "content": "Return JSON."},
    {"role": "user", "content": "Explain the approved source."},
]


def png(size=(2, 2)):
    buffer = io.BytesIO()
    with Image.new("RGB", size, "red") as image:
        image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def google_response(parts=None, **extra):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": parts or [{"text": '{"title":"Google result"}'}]},
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 8,
            "candidatesTokenCount": 4,
            "totalTokenCount": 12,
        },
        "responseId": "google-response",
        **extra,
    }


def mistral_response(**extra):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"title":"Mistral result"}',
                },
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
        "id": "mistral-response",
        **extra,
    }


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.status = 200
        self.body = google_response()
        self.raw = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                owner.calls.append((self.path, dict(self.headers), json.loads(data)))
                payload = (
                    owner.raw
                    if owner.raw is not None
                    else json.dumps(owner.body).encode()
                )
                self.send_response(owner.status)
                if owner.status == 302:
                    self.send_header("Location", "/redirect-target")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 2
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.targets = []

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def transport(self, req, *, timeout):
        self.assertEqual(timeout, 60)
        self.targets.append(req.full_url)
        # The only replaced collaborator is the paid remote endpoint. urllib,
        # Request headers, JSON serialization and bounded HTTP reads remain real.
        local = request.Request(
            f"http://127.0.0.1:{self.server.server_port}/fixture",
            data=req.data,
            headers=dict(req.header_items()),
            method=req.method,
        )
        return gp._urlopen(local, timeout=timeout)

    def client(self, provider="google", model="text-model", **kwargs):
        return gp.ProviderClient(
            provider,
            model,
            transport=self.transport,
            env={
                "GOOGLE_API_KEY": "fixture-google-key",
                "MISTRAL_API_KEY": "fixture-mistral-key",
            },
            **kwargs,
        )

    def test_google_wire_schema_system_role_and_envelope(self):
        response = self.client().complete(MESSAGES, SCHEMA)
        self.assertEqual(
            response,
            {
                "output": {"title": "Google result"},
                "usage": {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
                "response_id": "google-response",
            },
        )
        self.assertEqual(
            self.targets,
            [
                "https://generativelanguage.googleapis.com/v1beta/models/text-model:generateContent"
            ],
        )
        _, headers, body = self.calls[0]
        self.assertEqual(headers["X-Goog-Api-Key"], "fixture-google-key")
        self.assertEqual(
            body,
            {
                "contents": [
                    {"role": "user", "parts": [{"text": MESSAGES[1]["content"]}]}
                ],
                "systemInstruction": {"parts": [{"text": "Return JSON."}]},
                "generationConfig": {
                    "candidateCount": 1,
                    "maxOutputTokens": 16384,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": SCHEMA,
                },
            },
        )

    def test_mistral_wire_schema_and_envelope(self):
        self.body = mistral_response()
        response = self.client("mistral").complete(MESSAGES, SCHEMA)
        self.assertEqual(
            response,
            {
                "output": {"title": "Mistral result"},
                "usage": {"input_tokens": 9, "output_tokens": 5, "total_tokens": 14},
                "response_id": "mistral-response",
            },
        )
        self.assertEqual(self.targets, ["https://api.mistral.ai/v1/chat/completions"])
        _, headers, body = self.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer fixture-mistral-key")
        self.assertEqual(
            body,
            {
                "model": "text-model",
                "messages": MESSAGES,
                "stream": False,
                "max_tokens": 16384,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "generation_output",
                        "schema": SCHEMA,
                        "strict": True,
                    },
                },
            },
        )
        self.assertEqual(MESSAGES[1]["content"], "Explain the approved source.")

    def test_vision_sends_only_passed_data_and_no_tools(self):
        src = "data:image/png;base64," + png()
        for provider in ("google", "mistral"):
            with self.subTest(provider=provider):
                self.body = (
                    google_response() if provider == "google" else mistral_response()
                )
                self.client(provider).complete(MESSAGES, SCHEMA, images=[src])
                body = self.calls[-1][2]
                if provider == "google":
                    self.assertEqual(
                        body["contents"][0]["parts"][1],
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": src.split(",")[1],
                            }
                        },
                    )
                else:
                    self.assertEqual(
                        body["messages"][1]["content"][1],
                        {"type": "image_url", "image_url": {"url": src}},
                    )
                self.assertNotIn("tools", body)
        self.assertEqual(len(self.calls), 2)

    def test_unsafe_inputs_rejected_before_network(self):
        for model in (
            "https://bad.test/a",
            "/tmp/model",
            "../model",
            "a/../b",
            "a//b",
            "a?key=secret",
            "a#fragment",
            "a\\b",
            "a\n",
            "ü",
            "a" * 101,
        ):
            with self.subTest(model=model), self.assertRaises(ValueError):
                self.client(model=model)
        # Validate slash-containing identities without accepting resource URLs.
        self.assertEqual(
            gp.validate_model("vendor/public-model"), "vendor/public-model"
        )
        for images in (
            ["https://bad.test/x.png"],
            ["/tmp/a.png"],
            ["data:image/png;base64," + base64.b64encode(b"not-image").decode()],
            ["data:image/png;base64," + png()] * 4,
        ):
            with self.subTest(images=images), self.assertRaises(ValueError):
                self.client().complete(MESSAGES, SCHEMA, images=images)
        with self.assertRaises(ValueError):
            self.client().complete(
                [{"role": "user", "content": [{"type": "image_url"}]}], SCHEMA
            )
        self.assertEqual(self.calls, [])

    def test_readiness_and_missing_key_never_expose_credentials_or_call(self):
        empty = gp.ProviderClient(
            "google", "text-model", transport=self.transport, env={}
        )
        self.assertFalse(empty.ready())
        self.assertFalse(empty.ready("vision"))
        with self.assertRaises(gp.ProviderError) as caught:
            empty.complete(MESSAGES, SCHEMA)
        self.assertEqual(caught.exception.code, "missing_key")
        alias = gp.ProviderClient(
            "google", "text-model", env={"GEMINI_API_KEY": "fixture-alias"}
        )
        self.assertTrue(alias.ready("text"))
        self.assertTrue(alias.ready("vision"))
        self.assertFalse(alias.ready("image"))
        self.assertTrue(self.client(image_model="explicit-image-model").ready("image"))
        self.assertNotIn("fixture", repr(alias))
        self.assertEqual(self.calls, [])

    def test_terminal_http_failures_and_redirect_have_no_retry_or_secret(self):
        for status, code in (
            (401, "authentication"),
            (403, "authentication"),
            (429, "quota"),
            (500, "http_error"),
            (302, "http_error"),
        ):
            with self.subTest(status=status):
                self.status = status
                self.raw = b"fixture-google-key raw private prompt"
                before = len(self.calls)
                with self.assertRaises(gp.ProviderError) as caught:
                    self.client().complete(MESSAGES, SCHEMA)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.status, status)
                self.assertNotIn("fixture", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertEqual(len(self.calls), before + 1)

    def test_bounded_response_read_and_invalid_json(self):
        for raw, code in (
            (b"x" * (gp.MAX_RESPONSE_BYTES + 1), "response_too_large"),
            (b"private not JSON", "invalid_json"),
            (b"[]", "invalid_response"),
        ):
            with self.subTest(code=code):
                self.raw = raw
                before = len(self.calls)
                with self.assertRaises(gp.ProviderError) as caught:
                    self.client().complete(MESSAGES, SCHEMA)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(len(self.calls), before + 1)

    def test_refusals_truncation_malformed_candidates_and_output_fail(self):
        cases = [
            ("google", {"promptFeedback": {"blockReason": "SAFETY"}}),
            ("google", {"candidates": [{"finishReason": "SAFETY"}]}),
            ("google", {"candidates": [{"finishReason": "MAX_TOKENS"}]}),
            ("google", {"candidates": [None]}),
            ("google", google_response(parts=[{"text": "[]"}])),
            ("google", google_response(parts=[{"text": '{"x":NaN}'}])),
            (
                "mistral",
                {"choices": [{"finish_reason": "stop", "message": {"refusal": "no"}}]},
            ),
            (
                "mistral",
                {
                    "choices": [
                        {"finish_reason": "length", "message": {"content": "{}"}}
                    ]
                },
            ),
            ("mistral", {"choices": [None]}),
            (
                "mistral",
                {
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": "not json"}}
                    ]
                },
            ),
        ]
        for provider, body in cases:
            with self.subTest(provider=provider, body=body):
                self.body = body
                before = len(self.calls)
                with self.assertRaises(gp.ProviderError):
                    self.client(provider).complete(MESSAGES, SCHEMA)
                self.assertEqual(len(self.calls), before + 1)

    def test_image_generation_uses_separate_model_and_bounded_asset(self):
        self.body = google_response(
            parts=[{"inlineData": {"mimeType": "image/png", "data": png((2000, 1000))}}]
        )
        result = self.client(image_model="explicit-image-model").generate_image(
            "Approved concept"
        )
        self.assertEqual(
            self.targets,
            [
                "https://generativelanguage.googleapis.com/v1beta/models/explicit-image-model:generateContent"
            ],
        )
        self.assertEqual(
            self.calls[0][2]["generationConfig"],
            {
                "responseModalities": ["TEXT", "IMAGE"],
                "candidateCount": 1,
                "maxOutputTokens": 16384,
            },
        )
        self.assertLessEqual(
            len(canvas_assets.image_bytes(result["output"])), 256 * 1024
        )
        with canvas_assets.decode_image(result["output"]) as image:
            self.assertEqual(image.size, (1600, 800))
        self.assertEqual(result["response_id"], "google-response")
        self.client().generate_image("Approved concept", model="server-image-model")
        self.assertEqual(
            self.targets[-1],
            "https://generativelanguage.googleapis.com/v1beta/models/server-image-model:generateContent",
        )

    def test_image_generation_requires_configuration_before_call(self):
        for client in (self.client(), self.client("mistral")):
            with self.assertRaises(gp.ProviderError) as caught:
                client.generate_image("approved")
            self.assertEqual(caught.exception.code, "image_not_configured")
        with self.assertRaises(ValueError):
            self.client("mistral", image_model="bad")
        self.assertEqual(self.calls, [])

    def test_image_generation_rejects_invalid_rasters_mime_and_dimensions(self):
        inline_cases = [
            {"mimeType": "image/png", "data": "not base64"},
            {"mimeType": "image/jpeg", "data": png()},
            {"mimeType": "image/svg+xml", "data": png()},
            {"mimeType": "image/png", "data": png((4097, 1))},
        ]
        for inline in inline_cases:
            with self.subTest(inline=inline["mimeType"]):
                self.body = google_response(parts=[{"inlineData": inline}])
                with self.assertRaises(gp.ProviderError) as caught:
                    self.client(image_model="image-model").generate_image("approved")
                self.assertEqual(caught.exception.code, "invalid_image_response")

    def test_timeout_transport_failure_is_sanitized_and_called_once(self):
        calls = []

        def transport(req, *, timeout):
            calls.append(timeout)
            raise TimeoutError("fixture-google-key private prompt")

        client = gp.ProviderClient(
            "google",
            "model",
            transport=transport,
            env={"GOOGLE_API_KEY": "fixture"},
            timeout=2,
        )
        with self.assertRaises(gp.ProviderError) as caught:
            client.complete(MESSAGES, SCHEMA)
        self.assertEqual(str(caught.exception), "Generation failed: transport_error")
        self.assertEqual(calls, [2])
        for timeout in (0, 61, float("nan"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.client(timeout=timeout)

    def test_bounded_reader_requests_only_limit_plus_one(self):
        class Response(io.BytesIO):
            def getcode(self):
                return 200

            def read(self, size: int | None = -1):
                self_size.append(size)
                return super().read(size)

        self_size = []
        client = gp.ProviderClient(
            "google",
            "model",
            env={"GOOGLE_API_KEY": "fixture"},
            transport=lambda req, timeout: Response(
                json.dumps(google_response()).encode()
            ),
        )
        client.complete(MESSAGES, SCHEMA)
        self.assertEqual(self_size, [1024 * 1024 + 1])


if __name__ == "__main__":
    unittest.main()
