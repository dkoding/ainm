from __future__ import annotations

from typing import Any

import requests


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
        response = self.session.request(
            method=method.upper(),
            url=f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            json=json_body,
            timeout=self.timeout_seconds,
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:4000]}

        if response.status_code >= 400:
            raise TripletexAPIError(response.status_code, method.upper(), path, payload)
        return payload
