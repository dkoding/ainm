from __future__ import annotations

import time
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
        self._pacing_rules = {
            ("POST", "/astar-island/simulate"): 0.22,
            ("POST", "/astar-island/submit"): 0.55,
        }
        self._last_request_started_at: dict[tuple[str, str], float] = {}
        self._request_counters: dict[tuple[str, str], int] = {}
        self._request_metrics = {
            "paced_request_count": 0,
            "paced_sleep_seconds_total": 0.0,
            "per_endpoint": {},
        }
        self._last_request_meta: dict[str, Any] | None = None
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

    def get_last_request_meta(self) -> dict[str, Any] | None:
        if self._last_request_meta is None:
            return None
        return dict(self._last_request_meta)

    def get_request_metrics_summary(self) -> dict[str, Any]:
        per_endpoint = []
        for (method, path), count in sorted(self._request_counters.items()):
            metrics = self._request_metrics["per_endpoint"].get(f"{method} {path}", {})
            per_endpoint.append(
                {
                    "method": method,
                    "path": path,
                    "requests": int(count),
                    "paced_sleeps": int(metrics.get("paced_sleeps", 0)),
                    "paced_sleep_seconds_total": float(metrics.get("paced_sleep_seconds_total", 0.0)),
                }
            )
        return {
            "paced_request_count": int(self._request_metrics["paced_request_count"]),
            "paced_sleep_seconds_total": float(self._request_metrics["paced_sleep_seconds_total"]),
            "per_endpoint": per_endpoint,
        }

    def _request(
        self,
        method: str,
        path: str,
        json_body: Any | None = None,
        auth_required: bool = False,
    ) -> Any:
        if auth_required and not self.is_authenticated:
            raise AstarAPIError(401, f"{method} {path} requires AINM authentication.")
        paced_sleep_seconds = self._pace_request(method, path)
        started_at = time.monotonic()
        try:
            response = self.session.request(method, f"{self.base_url}{path}", json=json_body, timeout=self.timeout)
        except requests.Timeout as exc:
            raise AstarAPIError(504, f"{method} {path} timed out after {self.timeout}s.") from exc
        except requests.RequestException as exc:
            raise AstarAPIError(0, f"{method} {path} failed due to network error: {exc}") from exc
        duration_seconds = time.monotonic() - started_at
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text[:2000]}
        key = (method, path)
        self._request_counters[key] = self._request_counters.get(key, 0) + 1
        self._last_request_meta = {
            "method": method,
            "path": path,
            "status_code": int(response.status_code),
            "paced_sleep_seconds": float(paced_sleep_seconds),
            "duration_seconds": float(duration_seconds),
            "timestamp_monotonic": float(started_at),
            "rate_limited": bool(response.status_code == 429),
        }
        if response.status_code >= 400:
            raise AstarAPIError(response.status_code, self._format_error(method, path, response.status_code, payload))
        return payload

    def _pace_request(self, method: str, path: str) -> float:
        interval_seconds = self._pacing_rules.get((method, path))
        if not interval_seconds:
            return 0.0
        now = time.monotonic()
        key = (method, path)
        previous_started_at = self._last_request_started_at.get(key)
        sleep_seconds = 0.0
        if previous_started_at is not None:
            elapsed = now - previous_started_at
            sleep_seconds = max(0.0, float(interval_seconds) - elapsed)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        self._last_request_started_at[key] = time.monotonic()
        if sleep_seconds > 0:
            endpoint_key = f"{method} {path}"
            endpoint_metrics = self._request_metrics["per_endpoint"].setdefault(
                endpoint_key,
                {"paced_sleeps": 0, "paced_sleep_seconds_total": 0.0},
            )
            endpoint_metrics["paced_sleeps"] += 1
            endpoint_metrics["paced_sleep_seconds_total"] += float(sleep_seconds)
            self._request_metrics["paced_request_count"] += 1
            self._request_metrics["paced_sleep_seconds_total"] += float(sleep_seconds)
        return sleep_seconds

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
