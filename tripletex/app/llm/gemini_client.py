from __future__ import annotations

import json
import os
from typing import Any

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import AuthorizedSession
import requests

from app.raw.errors import RawExecutionError


class GeminiClient:
    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = float(os.getenv("GEMINI_TIMEOUT_SECONDS", str(timeout)).strip() or timeout)
        self.endpoint = os.getenv("GEMINI_ENDPOINT", "").strip()
        self.auth_token = os.getenv("GEMINI_AUTH_TOKEN", "").strip()
        self.project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip() or "global"
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip()
        self._vertex_session: AuthorizedSession | None = None

    def generate(self, prompt_package: dict[str, Any]) -> str:
        request_payload = {key: value for key, value in prompt_package.items() if key != "media"}
        if self.endpoint:
            headers = {"Content-Type": "application/json"}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"
            try:
                response = requests.post(
                    self.endpoint,
                    headers=headers,
                    json=request_payload,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise RawExecutionError(
                    message="Gemini endpoint request failed.",
                    details={"errorType": exc.__class__.__name__, "message": str(exc)[:2000]},
                ) from exc
            if response.status_code >= 400:
                raise RawExecutionError(message=f"Gemini endpoint returned HTTP {response.status_code}.")
            return response.text
        return self._generate_vertex(prompt_package)

    def repair(self, request_payload: dict[str, Any]) -> str:
        return self.generate(
            {
                "systemInstruction": (
                    "Fix the provided Tripletex bridge JSON only. "
                    "Return exactly one valid JSON object with no prose. "
                    "The top-level sections requestContext, language, understanding, sources, richData, flatBridge, "
                    "executionPlan, validation, and completion must all be JSON objects, never arrays."
                ),
                "request": request_payload,
                "context": {},
            }
        )

    def _generate_vertex(self, prompt_package: dict[str, Any]) -> str:
        session = self._get_vertex_session()
        payload = {
            "systemInstruction": {"parts": [{"text": prompt_package["systemInstruction"]}]},
            "contents": [
                {
                    "role": "user",
                    "parts": self._build_user_parts(prompt_package),
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        endpoint_host = "aiplatform.googleapis.com" if self.location == "global" else f"{self.location}-aiplatform.googleapis.com"
        url = (
            f"https://{endpoint_host}/v1/projects/{self.project}/locations/"
            f"{self.location}/publishers/google/models/{self.model}:generateContent"
        )
        try:
            response = session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RawExecutionError(
                message="Vertex AI request failed.",
                details={
                    "errorType": exc.__class__.__name__,
                    "message": str(exc)[:2000],
                    "location": self.location,
                    "model": self.model,
                },
            ) from exc
        if response.status_code >= 400:
            raise RawExecutionError(
                message=f"Vertex AI returned HTTP {response.status_code}.",
                status_code=response.status_code,
                details={"body": response.text[:2000]},
            )
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RawExecutionError(message="Vertex AI returned no candidates.", details={"body": data})
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if part.get("text"))
        if not text:
            raise RawExecutionError(message="Vertex AI returned no text content.", details={"body": data})
        return text

    def _build_user_parts(self, prompt_package: dict[str, Any]) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = [
            {
                "text": json.dumps(
                    {
                        "request": prompt_package["request"],
                        "context": prompt_package.get("context", {}),
                    },
                    ensure_ascii=False,
                )
            }
        ]
        for attachment in prompt_package.get("media", []):
            mime_type = str(attachment.get("mimeType", ""))
            content_base64 = attachment.get("contentBase64")
            if not isinstance(content_base64, str) or not content_base64:
                continue
            if not (mime_type.startswith("image/") or mime_type == "application/pdf"):
                continue
            parts.append(
                {
                    "text": (
                        f"Attachment {attachment.get('attachmentId')}: "
                        f"{attachment.get('filename')} ({mime_type})"
                    )
                }
            )
            parts.append({"inlineData": {"mimeType": mime_type, "data": content_base64}})
        return parts

    def _get_vertex_session(self) -> AuthorizedSession:
        if self._vertex_session is not None:
            return self._vertex_session
        try:
            credentials, detected_project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        except DefaultCredentialsError as exc:
            raise RawExecutionError(
                message="Application Default Credentials are not configured for Vertex AI."
            ) from exc
        if not self.project:
            self.project = detected_project or ""
        if not self.project:
            raise RawExecutionError(message="GOOGLE_CLOUD_PROJECT is required for Vertex AI generation.")
        self._vertex_session = AuthorizedSession(credentials)
        return self._vertex_session
