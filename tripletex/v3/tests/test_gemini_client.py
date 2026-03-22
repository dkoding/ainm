from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import requests

from app.llm.gemini_client import GeminiClient
from app.raw.errors import RawExecutionError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, json: dict[str, object], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class GeminiClientTests(unittest.TestCase):
    def test_endpoint_mode_preserves_media_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: float):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout

            class Response:
                status_code = 200
                text = "{\"ok\": true}"

            return Response()

        with patch.dict(
            os.environ,
            {
                "GEMINI_ENDPOINT": "https://example.test/gemini",
                "GEMINI_AUTH_TOKEN": "token",
            },
            clear=False,
        ):
            with patch("app.llm.gemini_client.requests.post", side_effect=fake_post):
                client = GeminiClient()
                result = client.generate(
                    {
                        "systemInstruction": "Return JSON only.",
                        "request": {"prompt": "Ping"},
                        "context": {},
                        "responseJsonSchema": {"type": "object", "required": ["ok"]},
                        "fallbackResponseJsonSchema": {"type": "object"},
                        "referenceDocuments": [
                            {
                                "name": "openapi.json",
                                "mimeType": "application/json",
                                "content": "{\"openapi\":\"3.0.0\"}",
                            }
                        ],
                        "media": [
                            {
                                "attachmentId": "attachment_1",
                                "filename": "receipt.png",
                                "mimeType": "image/png",
                                "contentBase64": "Zm9v",
                            }
                        ],
                    }
                )

        self.assertEqual(result, "{\"ok\": true}")
        self.assertIn("media", captured["json"])  # type: ignore[operator]
        self.assertIn("referenceDocuments", captured["json"])  # type: ignore[operator]
        self.assertIn("responseJsonSchema", captured["json"])  # type: ignore[operator]
        self.assertIn("fallbackResponseJsonSchema", captured["json"])  # type: ignore[operator]

    def test_vertex_payload_includes_high_resource_generation_config_and_reference_documents(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]},
                )
            ]
        )
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLOUD_PROJECT": "demo-project",
                "GOOGLE_CLOUD_LOCATION": "europe-north1",
                "GEMINI_MODEL": "gemini-2.5-pro",
                "GEMINI_TIMEOUT_SECONDS": "240",
                "GEMINI_THINKING_BUDGET": "32768",
                "GEMINI_MAX_OUTPUT_TOKENS": "65535",
                "GEMINI_FALLBACK_MODEL": "",
            },
            clear=False,
        ):
            client = GeminiClient()
            client._vertex_session = session  # type: ignore[assignment]
            payload = {
                "systemInstruction": "Return JSON only.",
                "request": {"prompt": "Ping"},
                "context": {},
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
                "fallbackResponseJsonSchema": {
                    "type": "object",
                },
                "referenceDocuments": [
                    {
                        "name": "openapi.json",
                        "mimeType": "application/json",
                        "instruction": "Match the spec exactly.",
                        "content": "{\"openapi\":\"3.0.0\"}",
                    }
                ],
            }
            result = client.generate(payload)

        self.assertEqual(result, "{\"ok\": true}")
        self.assertEqual(len(session.calls), 1)
        call = session.calls[0]
        self.assertIn("/locations/europe-north1/publishers/google/models/gemini-2.5-pro:generateContent", call["url"])
        generation_config = call["json"]["generationConfig"]  # type: ignore[index]
        self.assertEqual(generation_config["responseMimeType"], "application/json")  # type: ignore[index]
        self.assertEqual(generation_config["responseJsonSchema"]["required"], ["ok"])  # type: ignore[index]
        self.assertEqual(generation_config["maxOutputTokens"], 65535)  # type: ignore[index]
        self.assertEqual(generation_config["thinkingConfig"]["thinkingBudget"], 32768)  # type: ignore[index]
        self.assertEqual(call["timeout"], 240.0)
        user_parts = call["json"]["contents"][0]["parts"]  # type: ignore[index]
        self.assertTrue(any(part.get("text") == "{\"openapi\":\"3.0.0\"}" for part in user_parts))

    def test_retries_timeout_with_fallback_model(self) -> None:
        session = FakeSession(
            [
                requests.ReadTimeout("primary timed out"),
                FakeResponse(
                    200,
                    {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]},
                ),
            ]
        )
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLOUD_PROJECT": "demo-project",
                "GOOGLE_CLOUD_LOCATION": "europe-north1",
                "GEMINI_MODEL": "gemini-2.5-pro",
                "GEMINI_TIMEOUT_SECONDS": "240",
                "GEMINI_THINKING_BUDGET": "32768",
                "GEMINI_MAX_OUTPUT_TOKENS": "65535",
                "GEMINI_FALLBACK_MODEL": "gemini-2.5-flash",
                "GEMINI_FALLBACK_LOCATION": "europe-north1",
                "GEMINI_FALLBACK_TIMEOUT_SECONDS": "180",
                "GEMINI_FALLBACK_THINKING_BUDGET": "32768",
            },
            clear=False,
        ):
            client = GeminiClient()
            client._vertex_session = session  # type: ignore[assignment]
            payload = {
                "systemInstruction": "Return JSON only.",
                "request": {"prompt": "Ping"},
                "context": {},
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
                "fallbackResponseJsonSchema": {"type": "object"},
            }
            result = client.generate(payload)

        self.assertEqual(result, "{\"ok\": true}")
        self.assertEqual(len(session.calls), 2)
        primary_call = session.calls[0]
        fallback_call = session.calls[1]
        self.assertIn("/models/gemini-2.5-pro:generateContent", primary_call["url"])
        self.assertIn("/models/gemini-2.5-flash:generateContent", fallback_call["url"])
        fallback_generation_config = fallback_call["json"]["generationConfig"]  # type: ignore[index]
        self.assertEqual(fallback_generation_config["thinkingConfig"]["thinkingBudget"], 32768)  # type: ignore[index]
        self.assertEqual(fallback_call["timeout"], 180.0)

    def test_retries_with_fallback_schema_on_vertex_schema_complexity_error(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    400,
                    {
                        "error": {
                            "code": 400,
                            "message": (
                                "The specified schema produces a constraint that has too many states for serving."
                            ),
                            "status": "INVALID_ARGUMENT",
                        }
                    },
                ),
                FakeResponse(
                    200,
                    {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]},
                ),
            ]
        )
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLOUD_PROJECT": "demo-project",
                "GOOGLE_CLOUD_LOCATION": "global",
                "GEMINI_MODEL": "gemini-2.5-pro",
                "GEMINI_FALLBACK_MODEL": "",
            },
            clear=False,
        ):
            client = GeminiClient()
            client._vertex_session = session  # type: ignore[assignment]
            payload = {
                "systemInstruction": "Return JSON only.",
                "request": {"prompt": "Ping"},
                "context": {},
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
                "fallbackResponseJsonSchema": {
                    "type": "object",
                    "required": ["ok"],
                },
            }

            result = client.generate(payload)

        self.assertEqual(result, "{\"ok\": true}")
        self.assertEqual(len(session.calls), 2)
        primary_generation_config = session.calls[0]["json"]["generationConfig"]  # type: ignore[index]
        fallback_generation_config = session.calls[1]["json"]["generationConfig"]  # type: ignore[index]
        self.assertEqual(primary_generation_config["responseJsonSchema"]["properties"]["ok"]["type"], "boolean")  # type: ignore[index]
        self.assertEqual(fallback_generation_config["responseJsonSchema"]["required"], ["ok"])  # type: ignore[index]
        self.assertNotIn("properties", fallback_generation_config["responseJsonSchema"])  # type: ignore[index]

    def test_does_not_retry_with_fallback_schema_on_unrelated_bad_request(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    400,
                    {
                        "error": {
                            "code": 400,
                            "message": "Bad request for a different reason.",
                            "status": "INVALID_ARGUMENT",
                        }
                    },
                )
            ]
        )
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLOUD_PROJECT": "demo-project",
                "GOOGLE_CLOUD_LOCATION": "global",
                "GEMINI_MODEL": "gemini-2.5-pro",
                "GEMINI_FALLBACK_MODEL": "",
            },
            clear=False,
        ):
            client = GeminiClient()
            client._vertex_session = session  # type: ignore[assignment]
            payload = {
                "systemInstruction": "Return JSON only.",
                "request": {"prompt": "Ping"},
                "context": {},
                "responseJsonSchema": {"type": "object", "required": ["ok"]},
                "fallbackResponseJsonSchema": {"type": "object"},
            }

            with self.assertRaisesRegex(RawExecutionError, "Vertex AI returned HTTP 400"):
                client.generate(payload)

        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
