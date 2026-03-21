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
        self.base_url = str(base_url).rstrip("/")
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
            "tripletex.request.start method=%s path=%s base_url=%s timeout_seconds=%s params=%s json=%s",
            method.upper(),
            path,
            _redact_base_url(self.base_url),
            self.timeout_seconds,
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
            "tripletex.request.end method=%s path=%s status=%s elapsed_ms=%s response_request_id=%s response=%s",
            method.upper(),
            path,
            response.status_code,
            elapsed_ms,
            _response_request_id(response),
            _summarize_payload(payload),
        )
        if response.status_code >= 400:
            logger.warning(
                "tripletex.request.error method=%s path=%s status=%s elapsed_ms=%s response_request_id=%s detail=%r payload=%s",
                method.upper(),
                path,
                response.status_code,
                elapsed_ms,
                _response_request_id(response),
                _error_detail_suffix(payload),
                _summarize_payload(payload),
            )
            logger.warning(
                "metric.tripletex_api_failure count=1 method=%s path=%s status=%s source=%s",
                method.upper(),
                path,
                response.status_code,
                payload.get("source") if isinstance(payload, dict) else None,
            )
            raise TripletexAPIError(response.status_code, method.upper(), path, payload)
        return payload


def _summarize_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        summary: dict[str, Any] = {"type": "dict", "keys": list(value.keys())[:10]}
        for key in ("status", "code", "message", "developerMessage", "requestId", "error", "source"):
            if key in value:
                summary[key] = value.get(key)
        validation_messages = value.get("validationMessages")
        if isinstance(validation_messages, list) and validation_messages:
            summary["validationMessages"] = [
                _summarize_validation_message(message) for message in validation_messages[:3]
            ]
        if isinstance(value.get("values"), list):
            summary["values_count"] = len(value["values"])
            if value["values"]:
                summary["values_sample"] = [_sample_mapping(item) for item in value["values"][:2]]
        if isinstance(value.get("value"), dict):
            summary["value_sample"] = _sample_mapping(value["value"])
        if "raw_text" in value:
            summary["raw_text_chars"] = len(str(value.get("raw_text") or ""))
        return summary
    if isinstance(value, list):
        return {
            "type": "list",
            "items": len(value),
            "sample": [_sample_mapping(item) for item in value[:2]],
        }
    return {"type": type(value).__name__, "value": str(value)[:240]}


def _error_detail_suffix(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    parts: list[str] = []
    error_message = payload.get("error")
    if error_message not in {None, ""}:
        parts.append(str(error_message))
    developer_message = payload.get("developerMessage")
    if developer_message not in {None, ""}:
        parts.append(str(developer_message))
    message = payload.get("message")
    if message not in {None, ""}:
        parts.append(str(message))
    source = payload.get("source")
    if source not in {None, ""}:
        parts.append(f"source={source}")
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


def _sample_mapping(value: Any) -> Any:
    if not isinstance(value, dict):
        if value in {None, ""}:
            return None
        return str(value)[:160]
    keys = (
        "id",
        "version",
        "name",
        "number",
        "code",
        "organizationNumber",
        "invoiceNumber",
        "employeeNumber",
        "email",
        "description",
        "date",
        "status",
        "type",
    )
    summary: dict[str, Any] = {}
    for key in keys:
        item = value.get(key)
        if item not in {None, ""}:
            summary[key] = item
    if isinstance(value.get("voucher"), dict):
        summary["voucher"] = _sample_mapping(value["voucher"])
    if not summary:
        return {"keys": list(value.keys())[:8]}
    return summary


def _response_request_id(response: requests.Response) -> str | None:
    for header_name in ("X-Request-Id", "x-request-id", "X-Correlation-Id", "x-correlation-id"):
        value = response.headers.get(header_name)
        if value:
            return value[:120]
    return None


def _redact_base_url(base_url: str) -> str:
    if "://" not in base_url:
        return base_url[:120]
    scheme, rest = base_url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}"
