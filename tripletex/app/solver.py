from __future__ import annotations

import base64
import binascii
import os
import tempfile
from pathlib import Path
from typing import Any

from .attachments import prepare_attachments
from .client import TripletexAPIError, TripletexClient
from .execution import CommandExecutionError, TripletexCommandExecutor
from .models import SolveRequest, SolveResponse
from .openapi_registry import OpenAPIRegistryError, TripletexOpenAPIRegistry
from .planner import PlannerError, build_planner


class SolveError(RuntimeError):
    pass


class UnauthorizedError(SolveError):
    pass


class TripletexSolver:
    def __init__(self) -> None:
        self.expected_api_key = os.getenv("TRIPLETEX_API_KEY", "").strip()
        self.max_steps = int(os.getenv("TRIPLETEX_MAX_STEPS", "8"))
        self.timeout_seconds = float(os.getenv("TRIPLETEX_REQUEST_TIMEOUT", "30"))
        self.allow_noop = os.getenv("TRIPLETEX_ALLOW_NOOP", "false").strip().lower() in {"1", "true", "yes"}

    def solve(self, payload: SolveRequest, authorization_header: str | None) -> SolveResponse:
        self._verify_api_key(authorization_header)
        planner = build_planner(allow_noop=self.allow_noop)
        client = TripletexClient(
            base_url=payload.tripletex_credentials.base_url,
            session_token=payload.tripletex_credentials.session_token,
            timeout_seconds=self.timeout_seconds,
        )
        registry = TripletexOpenAPIRegistry.from_default_spec()
        executor = TripletexCommandExecutor(client, registry)

        with tempfile.TemporaryDirectory(prefix="tripletex-attachments-") as temp_dir:
            saved_attachments = self._save_attachments(payload, Path(temp_dir))
            attachments = prepare_attachments(saved_attachments)
            task_analysis = planner.analyze_task(
                task_prompt=payload.prompt,
                attachments=attachments,
            )
            history: list[dict[str, Any]] = []

            for attempt_index in range(self.max_steps):
                decision = planner.next_step(
                    task_analysis=task_analysis,
                    attachments=attachments,
                    history=history,
                    remaining_steps=self.max_steps - attempt_index,
                )
                if decision.kind == "finish":
                    return SolveResponse(status="completed")

                try:
                    command = decision.to_command()
                except ValueError as exc:
                    raise PlannerError(str(exc)) from exc

                response_payload = executor.execute(command)
                history.append(
                    {
                        "reason": command.reason,
                        "request": {
                            "method": command.method,
                            "path": command.path,
                            "params": command.params,
                            "json": _trim_payload(command.json_body),
                        },
                        "response": _trim_payload(response_payload),
                    }
                )

        raise SolveError(f"Planner exhausted its {self.max_steps}-step budget before finishing.")

    def _verify_api_key(self, authorization_header: str | None) -> None:
        if not self.expected_api_key:
            return
        expected_value = f"Bearer {self.expected_api_key}"
        if authorization_header != expected_value:
            raise UnauthorizedError("Missing or invalid bearer token.")

    def _save_attachments(self, payload: SolveRequest, target_dir: Path) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for index, file in enumerate(payload.files):
            filename = Path(file.filename).name or f"attachment-{index}"
            path = target_dir / filename
            try:
                raw_bytes = base64.b64decode(file.content_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise SolveError(f"Attachment {file.filename!r} is not valid base64.") from exc
            path.write_bytes(raw_bytes)
            saved.append(
                {
                    "filename": filename,
                    "mime_type": file.mime_type,
                    "path": str(path),
                    "size_bytes": len(raw_bytes),
                }
            )
        return saved


def _trim_payload(value: Any, *, max_depth: int = 3, max_items: int = 5) -> Any:
    if max_depth <= 0:
        return "<truncated>"
    if isinstance(value, dict):
        trimmed: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                trimmed["..."] = "<truncated>"
                break
            trimmed[str(key)] = _trim_payload(item, max_depth=max_depth - 1, max_items=max_items)
        return trimmed
    if isinstance(value, list):
        return [_trim_payload(item, max_depth=max_depth - 1, max_items=max_items) for item in value[:max_items]]
    return value


__all__ = [
    "PlannerError",
    "CommandExecutionError",
    "OpenAPIRegistryError",
    "SolveError",
    "TripletexAPIError",
    "TripletexSolver",
    "UnauthorizedError",
]
