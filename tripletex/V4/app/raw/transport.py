from __future__ import annotations

import logging
from typing import Any

import requests

from app.contracts.execution import ExecutionContext
from app.raw.errors import RawExecutionError


logger = logging.getLogger("tripletex_transport")


class TripletexTransport:
    def __init__(self, timeout: float = 30.0, session: requests.Session | None = None) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()

    def request(
        self,
        *,
        context: ExecutionContext,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        multipart_data: dict[str, Any] | None = None,
        multipart_files: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{context.base_url.rstrip('/')}{path}"
        logger.info(
            "tripletex.request request_id=%s method=%s path=%s query_keys=%s body_shape=%s multipart_data_keys=%s multipart_file_keys=%s",
            context.request_id,
            method,
            path,
            sorted((params or {}).keys()),
            self._body_shape(json_body),
            sorted((multipart_data or {}).keys()),
            sorted((multipart_files or {}).keys()),
        )
        try:
            response = self.session.request(
                method=method,
                url=url,
                auth=("0", context.session_token),
                params=params or None,
                json=json_body,
                data=multipart_data or None,
                files=multipart_files or None,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RawExecutionError(
                message="Failed to reach the Tripletex proxy.",
                details={"path": path, "method": method},
            ) from exc

        request_id = response.headers.get("x-tlx-request-id")
        if response.status_code >= 400:
            details: dict[str, Any] = {
                "path": path,
                "method": method,
                "queryKeys": sorted((params or {}).keys()),
                "bodyShape": self._body_shape(json_body),
                "multipartDataKeys": sorted((multipart_data or {}).keys()),
                "multipartFileKeys": sorted((multipart_files or {}).keys()),
            }
            try:
                details["body"] = response.json()
            except ValueError:
                details["body"] = response.text[:1000]
            logger.warning(
                "tripletex.response_error request_id=%s method=%s path=%s status=%s details=%s",
                context.request_id,
                method,
                path,
                response.status_code,
                details,
            )
            raise RawExecutionError(
                message=f"Tripletex returned HTTP {response.status_code} for {method} {path}.",
                status_code=response.status_code,
                request_id=request_id,
                details=details,
            )

        if response.status_code == 204 or not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    def _body_shape(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            return {"kind": "object", "keys": sorted(payload.keys())}
        if isinstance(payload, list):
            return {"kind": "array", "length": len(payload)}
        if payload is None:
            return {"kind": "none"}
        return {"kind": type(payload).__name__}
