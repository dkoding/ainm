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
        super().__init__(f"Tripletex API call failed: {method} {path} -> {status_code}")


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
        return {"type": "dict", "keys": list(value.keys())[:10]}
    if isinstance(value, list):
        return {"type": "list", "items": len(value)}
    return {"type": type(value).__name__, "value": str(value)[:240]}
