from __future__ import annotations

import base64
import binascii
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .attachments import prepare_attachments
from .client import TripletexAPIError, TripletexClient
from .execution import CommandExecutionError, TripletexCommandExecutor
from .models import SolveRequest, SolveResponse
from .openapi_registry import OpenAPIRegistryError, TripletexOpenAPIRegistry
from .planner import PlannerError, build_planner

logger = logging.getLogger(__name__)


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
        started_at = time.monotonic()
        self._verify_api_key(authorization_header)
        logger.info(
            "solve.start prompt_chars=%s files=%s base_url=%s",
            len(payload.prompt),
            len(payload.files),
            _redact_base_url(payload.tripletex_credentials.base_url),
        )
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
            logger.info("solve.attachments.saved attachments=%s", _summarize_saved_attachments(saved_attachments))
            attachments = prepare_attachments(saved_attachments)
            logger.info("solve.attachments.prepared attachments=%s", _summarize_prepared_attachments(attachments))

            analysis_started_at = time.monotonic()
            task_analysis = planner.analyze_task(
                task_prompt=payload.prompt,
                attachments=attachments,
            )
            logger.info(
                "solve.analysis.complete elapsed_ms=%s task_family=%s operation=%s target_resource=%s risk=%s attachment_required=%s search_hints=%s payload_fields=%s ambiguity_notes=%s",
                round((time.monotonic() - analysis_started_at) * 1000, 1),
                task_analysis.task_family,
                task_analysis.operation,
                task_analysis.target_resource,
                task_analysis.risk_level,
                task_analysis.attachment_required,
                sorted(task_analysis.search_hints.keys()),
                sorted(task_analysis.payload_fields.keys()),
                task_analysis.ambiguity_notes[:4],
            )
            history: list[dict[str, Any]] = []

            for attempt_index in range(self.max_steps):
                logger.info(
                    "solve.step.start step=%s remaining_steps=%s history_entries=%s",
                    attempt_index + 1,
                    self.max_steps - attempt_index,
                    len(history),
                )
                planning_started_at = time.monotonic()
                decision = planner.next_step(
                    task_analysis=task_analysis,
                    attachments=attachments,
                    history=history,
                    remaining_steps=self.max_steps - attempt_index,
                )
                logger.info(
                    "solve.step.decision step=%s kind=%s elapsed_ms=%s reason=%r",
                    attempt_index + 1,
                    decision.kind,
                    round((time.monotonic() - planning_started_at) * 1000, 1),
                    decision.reason[:240],
                )
                if decision.kind == "finish":
                    logger.info(
                        "solve.finish step=%s total_elapsed_ms=%s",
                        attempt_index + 1,
                        round((time.monotonic() - started_at) * 1000, 1),
                    )
                    return SolveResponse(status="completed")

                try:
                    command = decision.to_command()
                except ValueError as exc:
                    raise PlannerError(str(exc)) from exc

                logger.info(
                    "solve.command step=%s method=%s path=%s params=%s json=%s",
                    attempt_index + 1,
                    command.method,
                    command.path,
                    _trim_payload(command.params),
                    _trim_payload(command.json_body),
                )
                execution_started_at = time.monotonic()
                try:
                    response_payload = executor.execute(command)
                except CommandExecutionError as exc:
                    logger.warning(
                        "solve.command.validation_failed step=%s method=%s path=%s error=%r",
                        attempt_index + 1,
                        command.method,
                        command.path,
                        str(exc),
                    )
                    history.append(
                        {
                            "reason": command.reason,
                            "request": {
                                "method": command.method,
                                "path": command.path,
                                "params": command.params,
                                "json": _trim_payload(command.json_body),
                            },
                            "error": {
                                "type": "command_validation",
                                "message": str(exc),
                            },
                        }
                    )
                    continue
                except TripletexAPIError as exc:
                    logger.warning(
                        "solve.command.api_failed step=%s method=%s path=%s status=%s error=%s",
                        attempt_index + 1,
                        command.method,
                        command.path,
                        exc.status_code,
                        str(exc),
                    )
                    history.append(
                        {
                            "reason": command.reason,
                            "request": {
                                "method": command.method,
                                "path": command.path,
                                "params": command.params,
                                "json": _trim_payload(command.json_body),
                            },
                            "error": {
                                "type": "tripletex_api",
                                "status_code": exc.status_code,
                                "message": str(exc),
                                "payload": _trim_payload(exc.payload),
                            },
                        }
                    )
                    continue
                logger.info(
                    "solve.command.complete step=%s method=%s path=%s elapsed_ms=%s response=%s",
                    attempt_index + 1,
                    command.method,
                    command.path,
                    round((time.monotonic() - execution_started_at) * 1000, 1),
                    _payload_signature(response_payload),
                )
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


def _payload_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return {"type": "dict", "keys": list(value.keys())[:10]}
    if isinstance(value, list):
        return {"type": "list", "items": len(value)}
    return {"type": type(value).__name__, "value": str(value)[:240]}


def _summarize_saved_attachments(saved_attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for attachment in saved_attachments:
        summary.append(
            {
                "filename": attachment["filename"],
                "mime_type": attachment["mime_type"],
                "size_bytes": attachment["size_bytes"],
            }
        )
    return summary


def _summarize_prepared_attachments(attachments: list[Any]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for attachment in attachments:
        summary.append(
            {
                "filename": attachment.filename,
                "mime_type": attachment.mime_type,
                "media_kind": attachment.media_kind,
                "size_bytes": attachment.size_bytes,
                "text_excerpt_chars": len(attachment.text_excerpt),
                "extraction_notes": attachment.extraction_notes[:3],
            }
        )
    return summary


def _redact_base_url(base_url: str) -> str:
    if "://" not in base_url:
        return base_url[:120]
    scheme, rest = base_url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}"


__all__ = [
    "PlannerError",
    "CommandExecutionError",
    "OpenAPIRegistryError",
    "SolveError",
    "TripletexAPIError",
    "TripletexSolver",
    "UnauthorizedError",
]
