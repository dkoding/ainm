from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class TripletexAPIError(RuntimeError):
    def __init__(self, status_code: int, method: str, path: str, payload: Any):
        self.status_code = status_code
        self.method = method
        self.path = path
        self.payload = payload
        detail = _error_detail_suffix(payload)
        message = f"Tripletex API call failed: {method} {path} -> {status_code}"
        if detail:
            message = f"{message} [{detail}]"
        super().__init__(message)


class TripletexClient:
    def __init__(self, base_url: str, session_token: str, timeout_seconds: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.auth = ("0", session_token)
        self.session.headers.update({"Accept": "application/json"})

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        started_at = time.monotonic()
        logger.info(
            "tripletex.request.start method=%s path=%s params=%s json=%s",
            method.upper(),
            path,
            _summarize_payload(params),
            _summarize_payload(json_body),
        )
        response = self.session.request(
            method=method.upper(),
            url=f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            json=json_body,
            timeout=self.timeout_seconds,
        )
        elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:4000]}

        logger.info(
            "tripletex.request.end method=%s path=%s status=%s elapsed_ms=%s response=%s",
            method.upper(),
            path,
            response.status_code,
            elapsed_ms,
            _summarize_payload(payload),
        )
        if response.status_code >= 400:
            raise TripletexAPIError(response.status_code, method.upper(), path, payload)
        return payload


def _summarize_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        summary: dict[str, Any] = {"type": "dict", "keys": list(value.keys())[:10]}
        for key in ("status", "code", "message", "developerMessage", "requestId"):
            if key in value:
                summary[key] = value.get(key)
        validation_messages = value.get("validationMessages")
        if isinstance(validation_messages, list) and validation_messages:
            summary["validationMessages"] = [
                _summarize_validation_message(message) for message in validation_messages[:3]
            ]
        return summary
    if isinstance(value, list):
        return {"type": "list", "items": len(value)}
    return {"type": type(value).__name__, "value": str(value)[:240]}


def _error_detail_suffix(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    parts: list[str] = []
    developer_message = payload.get("developerMessage")
    if developer_message not in {None, ""}:
        parts.append(str(developer_message))
    message = payload.get("message")
    if message not in {None, ""}:
        parts.append(str(message))
    validation_messages = payload.get("validationMessages")
    if isinstance(validation_messages, list):
        for item in validation_messages[:2]:
            summarized = _summarize_validation_message(item)
            if summarized:
                parts.append(str(summarized))
    if not parts:
        return None
    return "; ".join(parts)[:400]


def _summarize_validation_message(value: Any) -> Any:
    if isinstance(value, dict):
        summary = {
            key: value[key]
            for key in ("field", "path", "message", "developerMessage")
            if key in value and value[key] not in {None, ""}
        }
        if summary:
            return summary
    if value in {None, ""}:
        return None
    return str(value)[:240]
