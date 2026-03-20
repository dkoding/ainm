from __future__ import annotations

from typing import Any

import requests


class AstarAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class AstarClient:
    def __init__(self, token: str | None = None, base_url: str = "https://api.ainm.no", timeout: float = 60.0):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "ainm-astar-scaffold/2026-03-20"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    @property
    def is_authenticated(self) -> bool:
        return bool(self.token)

    def get_rounds(self) -> list[dict[str, Any]]:
        return self._request("GET", "/astar-island/rounds", auth_required=False)

    def get_round_detail(self, round_id: str) -> dict[str, Any]:
        return self._request("GET", f"/astar-island/rounds/{round_id}", auth_required=False)

    def get_leaderboard(self) -> list[dict[str, Any]]:
        return self._request("GET", "/astar-island/leaderboard", auth_required=False)

    def get_budget(self) -> dict[str, Any]:
        return self._request("GET", "/astar-island/budget", auth_required=True)

    def simulate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/astar-island/simulate", json_body=payload, auth_required=True)

    def submit_prediction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/astar-island/submit", json_body=payload, auth_required=True)

    def get_my_rounds(self) -> list[dict[str, Any]]:
        return self._request("GET", "/astar-island/my-rounds", auth_required=True)

    def get_my_predictions(self, round_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/astar-island/my-predictions/{round_id}", auth_required=True)

    def get_analysis(self, round_id: str, seed_index: int) -> dict[str, Any]:
        return self._request("GET", f"/astar-island/analysis/{round_id}/{seed_index}", auth_required=True)

    def _request(
        self,
        method: str,
        path: str,
        json_body: Any | None = None,
        auth_required: bool = False,
    ) -> Any:
        if auth_required and not self.is_authenticated:
            raise AstarAPIError(401, f"{method} {path} requires AINM authentication.")
        response = self.session.request(method, f"{self.base_url}{path}", json=json_body, timeout=self.timeout)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:2000]}
        if response.status_code >= 400:
            raise AstarAPIError(response.status_code, f"{method} {path} failed: {payload}")
        return payload
