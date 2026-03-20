from __future__ import annotations

from typing import Any

import requests


class AstarAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class AstarClient:
    def __init__(self, token: str, base_url: str = "https://api.ainm.no"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

    def get_rounds(self) -> list[dict[str, Any]]:
        return self._request("GET", "/astar-island/rounds")

    def get_round_detail(self, round_id: str) -> dict[str, Any]:
        return self._request("GET", f"/astar-island/rounds/{round_id}")

    def get_budget(self) -> dict[str, Any]:
        return self._request("GET", "/astar-island/budget")

    def simulate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/astar-island/simulate", json_body=payload)

    def submit_prediction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/astar-island/submit", json_body=payload)

    def _request(self, method: str, path: str, json_body: Any | None = None) -> Any:
        response = self.session.request(method, f"{self.base_url}{path}", json=json_body, timeout=60)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:2000]}
        if response.status_code >= 400:
            raise AstarAPIError(response.status_code, f"{method} {path} failed: {payload}")
        return payload
