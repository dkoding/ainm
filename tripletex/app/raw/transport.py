from __future__ import annotations

from typing import Any

import requests

from app.contracts.execution import ExecutionContext
from app.raw.errors import RawExecutionError


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
            details: dict[str, Any] = {"path": path, "method": method}
            try:
                details["body"] = response.json()
            except ValueError:
                details["body"] = response.text[:1000]
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
