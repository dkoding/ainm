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
        self.timeout = timeout
        self.endpoint = os.getenv("GEMINI_ENDPOINT", "").strip()
        self.auth_token = os.getenv("GEMINI_AUTH_TOKEN", "").strip()
        self.project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", os.getenv("CLOUD_RUN_REGION", "europe-north1")).strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip()
        self._vertex_session: AuthorizedSession | None = None

    def generate(self, prompt_package: dict[str, Any]) -> str:
        if self.endpoint:
            headers = {"Content-Type": "application/json"}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=prompt_package,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RawExecutionError(message=f"Gemini endpoint returned HTTP {response.status_code}.")
            return response.text
        return self._generate_vertex(prompt_package)

    def repair(self, broken_payload: str, errors: list[str]) -> str:
        return self.generate(
            {
                "systemInstruction": "Fix the provided JSON only. Return one valid JSON object with no prose.",
                "request": {"invalidJson": broken_payload, "errors": errors},
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
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "request": prompt_package["request"],
                                    "context": prompt_package.get("context", {}),
                                },
                                ensure_ascii=False,
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/"
            f"{self.project}/locations/{self.location}/publishers/google/models/{self.model}:generateContent"
        )
        response = session.post(url, json=payload, timeout=self.timeout)
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
