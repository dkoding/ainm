from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from validation import (
    AstarValidationError,
    validate_analysis_response,
    validate_budget_response,
    validate_my_predictions_response,
    validate_my_rounds_response,
    validate_round_detail_response,
    validate_rounds_response,
    validate_simulate_request,
    validate_simulate_response,
    validate_submission_payload,
)


class AstarAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class AstarClient:
    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://api.ainm.no",
        timeout: float = 60.0,
        max_get_retries: int = 3,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "ainm-astar-scaffold/2026-03-20"})
        retry_policy = Retry(
            total=max_get_retries,
            connect=max_get_retries,
            read=max_get_retries,
            status=max_get_retries,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry_policy))
        self.session.mount("http://", HTTPAdapter(max_retries=retry_policy))
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    @property
    def is_authenticated(self) -> bool:
        return bool(self.token)

    def get_rounds(self) -> list[dict[str, Any]]:
        return validate_rounds_response(self._request("GET", "/astar-island/rounds", auth_required=False))

    def get_round_detail(self, round_id: str) -> dict[str, Any]:
        return validate_round_detail_response(self._request("GET", f"/astar-island/rounds/{round_id}", auth_required=False))

    def get_leaderboard(self) -> list[dict[str, Any]]:
        return self._request("GET", "/astar-island/leaderboard", auth_required=False)

    def get_budget(self) -> dict[str, Any]:
        return validate_budget_response(self._request("GET", "/astar-island/budget", auth_required=True))

    def simulate(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_simulate_request(payload)
        return validate_simulate_response(self._request("POST", "/astar-island/simulate", json_body=payload, auth_required=True))

    def submit_prediction(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_submission_payload(payload)
        return self._request("POST", "/astar-island/submit", json_body=payload, auth_required=True)

    def get_my_rounds(self) -> list[dict[str, Any]]:
        return validate_my_rounds_response(self._request("GET", "/astar-island/my-rounds", auth_required=True))

    def get_my_predictions(self, round_id: str) -> list[dict[str, Any]]:
        return validate_my_predictions_response(
            self._request("GET", f"/astar-island/my-predictions/{round_id}", auth_required=True)
        )

    def get_analysis(self, round_id: str, seed_index: int) -> dict[str, Any]:
        return validate_analysis_response(
            self._request("GET", f"/astar-island/analysis/{round_id}/{seed_index}", auth_required=True)
        )

    def _request(
        self,
        method: str,
        path: str,
        json_body: Any | None = None,
        auth_required: bool = False,
    ) -> Any:
        if auth_required and not self.is_authenticated:
            raise AstarAPIError(401, f"{method} {path} requires AINM authentication.")
        try:
            response = self.session.request(method, f"{self.base_url}{path}", json=json_body, timeout=self.timeout)
        except requests.Timeout as exc:
            raise AstarAPIError(504, f"{method} {path} timed out after {self.timeout}s.") from exc
        except requests.RequestException as exc:
            raise AstarAPIError(0, f"{method} {path} failed due to network error: {exc}") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:2000]}
        if response.status_code >= 400:
            raise AstarAPIError(response.status_code, self._format_error(method, path, response.status_code, payload))
        return payload

    def _format_error(self, method: str, path: str, status_code: int, payload: Any) -> str:
        detail = f"{method} {path} failed with HTTP {status_code}: {payload}"
        if status_code == 400:
            return f"{detail} Common causes: malformed payload, invalid seed index, invalid viewport, or closed round."
        if status_code == 401:
            return f"{detail} Check AINM_ACCESS_TOKEN and team access."
        if status_code == 403:
            return f"{detail} Team access may be missing for this endpoint."
        if status_code == 404:
            return f"{detail} The round or endpoint path may be wrong."
        if status_code == 409:
            return f"{detail} The round may no longer be active, or the submission state may have changed."
        if status_code == 429:
            return f"{detail} Rate limit exceeded; slow down retries and submission loops."
        if status_code >= 500:
            return f"{detail} Organizer API error; retry safe GETs, but avoid blindly retrying POSTs."
        return detail
