from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from typing import Any

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import AuthorizedSession
import requests

from app.raw.errors import RawExecutionError


logger = logging.getLogger("tripletex_gemini")

DEFAULT_VERTEX_LOCATION = "global"
DEFAULT_GEMINI_TIMEOUT_SECONDS = 3600.0
DEFAULT_GEMINI_MAX_OUTPUT_TOKENS = 65536
DEFAULT_GEMINI_2_5_PRO_THINKING_BUDGET = 32768


@dataclass(frozen=True)
class VertexRuntimeConfig:
    model: str
    location: str
    timeout: float
    thinking_budget: int | None


def _read_optional_int_env(name: str, *, default: int | None = None) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 0:
        return None
    return value


def _read_float_env(name: str, *, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


class GeminiClient:
    def __init__(self, timeout: float = DEFAULT_GEMINI_TIMEOUT_SECONDS) -> None:
        self.timeout = _read_float_env("GEMINI_TIMEOUT_SECONDS", default=timeout)
        self.endpoint = os.getenv("GEMINI_ENDPOINT", "").strip()
        self.auth_token = os.getenv("GEMINI_AUTH_TOKEN", "").strip()
        self.project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", DEFAULT_VERTEX_LOCATION).strip() or DEFAULT_VERTEX_LOCATION
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip()
        self.max_output_tokens = _read_optional_int_env(
            "GEMINI_MAX_OUTPUT_TOKENS",
            default=DEFAULT_GEMINI_MAX_OUTPUT_TOKENS,
        )
        self.thinking_budget = _read_optional_int_env(
            "GEMINI_THINKING_BUDGET",
            default=DEFAULT_GEMINI_2_5_PRO_THINKING_BUDGET,
        )
        self.fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "").strip()
        self.fallback_location = os.getenv("GEMINI_FALLBACK_LOCATION", self.location).strip() or self.location
        self.fallback_timeout = _read_float_env(
            "GEMINI_FALLBACK_TIMEOUT_SECONDS",
            default=self.timeout,
        )
        self.fallback_thinking_budget = _read_optional_int_env(
            "GEMINI_FALLBACK_THINKING_BUDGET",
            default=self.thinking_budget,
        )
        self._vertex_session: AuthorizedSession | None = None

    def generate(self, prompt_package: dict[str, Any]) -> str:
        request_payload = dict(prompt_package)
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
        primary = VertexRuntimeConfig(
            model=self.model,
            location=self.location,
            timeout=self.timeout,
            thinking_budget=self.thinking_budget,
        )
        fallback = self._fallback_vertex_config()
        try:
            return self._generate_vertex_once(prompt_package, primary)
        except RawExecutionError as exc:
            if fallback is None or not self._should_retry_with_fallback(exc):
                raise
            logger.warning(
                "vertex.primary_failed retrying_with_fallback primary_model=%s primary_location=%s fallback_model=%s fallback_location=%s error=%s",
                primary.model,
                primary.location,
                fallback.model,
                fallback.location,
                exc.message,
            )
            try:
                return self._generate_vertex_once(prompt_package, fallback)
            except RawExecutionError as fallback_exc:
                raise RawExecutionError(
                    message="Vertex AI primary and fallback requests failed.",
                    status_code=fallback_exc.status_code or exc.status_code,
                    details={
                        "primary": self._error_summary(exc),
                        "fallback": self._error_summary(fallback_exc),
                    },
                ) from fallback_exc

    def _generate_vertex_once(self, prompt_package: dict[str, Any], config: VertexRuntimeConfig) -> str:
        session = self._get_vertex_session()
        generation_config: dict[str, Any] = {
            "temperature": 0,
            "responseMimeType": "application/json",
        }
        if self.max_output_tokens is not None:
            generation_config["maxOutputTokens"] = self.max_output_tokens
        if config.thinking_budget is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": config.thinking_budget}
        payload = {
            "systemInstruction": {"parts": [{"text": prompt_package["systemInstruction"]}]},
            "contents": [
                {
                    "role": "user",
                    "parts": self._build_user_parts(prompt_package),
                }
            ],
            "generationConfig": generation_config,
        }
        endpoint_host = (
            "aiplatform.googleapis.com"
            if config.location == "global"
            else f"{config.location}-aiplatform.googleapis.com"
        )
        url = (
            f"https://{endpoint_host}/v1/projects/{self.project}/locations/"
            f"{config.location}/publishers/google/models/{config.model}:generateContent"
        )
        try:
            response = session.post(url, json=payload, timeout=config.timeout)
        except requests.RequestException as exc:
            raise RawExecutionError(
                message="Vertex AI request failed.",
                details={
                    "errorType": exc.__class__.__name__,
                    "message": str(exc)[:2000],
                    "location": config.location,
                    "model": config.model,
                },
            ) from exc
        if response.status_code >= 400:
            raise RawExecutionError(
                message=f"Vertex AI returned HTTP {response.status_code}.",
                status_code=response.status_code,
                details={
                    "body": response.text[:2000],
                    "location": config.location,
                    "model": config.model,
                },
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

    def _fallback_vertex_config(self) -> VertexRuntimeConfig | None:
        if not self.fallback_model:
            return None
        fallback = VertexRuntimeConfig(
            model=self.fallback_model,
            location=self.fallback_location,
            timeout=self.fallback_timeout,
            thinking_budget=self.fallback_thinking_budget,
        )
        primary = VertexRuntimeConfig(
            model=self.model,
            location=self.location,
            timeout=self.timeout,
            thinking_budget=self.thinking_budget,
        )
        if fallback == primary:
            return None
        return fallback

    def _should_retry_with_fallback(self, exc: RawExecutionError) -> bool:
        if exc.status_code in {408, 429, 500, 502, 503, 504}:
            return True
        error_type = str(exc.details.get("errorType", "")).strip()
        return error_type in {"ConnectTimeout", "ConnectionError", "ReadTimeout", "Timeout"}

    def _error_summary(self, exc: RawExecutionError) -> dict[str, Any]:
        return {
            "message": exc.message,
            "statusCode": exc.status_code,
            "details": exc.details,
        }
