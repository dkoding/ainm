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
from .generated_methods import GeneratedAPIMethodRegistry, GeneratedMethodError
from .internal_tasks import (
    METHOD_SPECS,
    derive_internal_task,
    normalize_task_analysis_method_selection,
    resolved_missing_required_arguments,
    startup_coverage_audit_lines,
    validate_task_analysis_contract,
)
from .models import SolveRequest, SolveResponse
from .openapi_registry import OpenAPIRegistryError, TripletexOpenAPIRegistry
from .planner import PlannerError, build_planner
from .spec_runtime import repair_command
from .workflow_router import DeterministicWorkflowRouter

logger = logging.getLogger(__name__)


class SolveError(RuntimeError):
    pass


class UnauthorizedError(SolveError):
    pass


class TaskInputError(SolveError):
    pass


class TaskPreconditionError(SolveError):
    pass


class TripletexSolver:
    def __init__(self) -> None:
        self.expected_api_key = os.getenv("TRIPLETEX_API_KEY", "").strip()
        legacy_steps = os.getenv("TRIPLETEX_MAX_STEPS", "").strip()
        self.max_planner_steps = int(os.getenv("TRIPLETEX_MAX_PLANNER_STEPS", legacy_steps or "12"))
        self.max_api_calls = int(os.getenv("TRIPLETEX_MAX_API_CALLS", legacy_steps or "12"))
        self.timeout_seconds = float(os.getenv("TRIPLETEX_REQUEST_TIMEOUT", "30"))
        self.solve_budget_seconds = min(
            300.0,
            float(os.getenv("TRIPLETEX_SOLVE_BUDGET_SECONDS", "300")),
        )
        self.allow_noop = os.getenv("TRIPLETEX_ALLOW_NOOP", "false").strip().lower() in {"1", "true", "yes"}
        self.enable_llm_step_planning = (
            os.getenv("TRIPLETEX_ENABLE_LLM_STEP_PLANNING", "false").strip().lower() in {"1", "true", "yes"}
        )
        if not getattr(self.__class__, "_coverage_audit_logged", False):
            for line in startup_coverage_audit_lines():
                logger.info(line)
            self.__class__._coverage_audit_logged = True

    def solve(self, payload: SolveRequest, authorization_header: str | None) -> SolveResponse:
        started_at = time.monotonic()
        self._verify_api_key(authorization_header)
        logger.info(
            "solve.start prompt_chars=%s files=%s base_url=%s max_planner_steps=%s max_api_calls=%s timeout_seconds=%s solve_budget_seconds=%s enable_llm_step_planning=%s",
            len(payload.prompt),
            len(payload.files),
            _redact_base_url(payload.tripletex_credentials.base_url),
            self.max_planner_steps,
            self.max_api_calls,
            self.timeout_seconds,
            self.solve_budget_seconds,
            self.enable_llm_step_planning,
        )
        planner = None
        client = TripletexClient(
            base_url=payload.tripletex_credentials.base_url,
            session_token=payload.tripletex_credentials.session_token,
            timeout_seconds=self.timeout_seconds,
        )
        registry = TripletexOpenAPIRegistry.from_default_spec()
        generated_methods = GeneratedAPIMethodRegistry.from_default_spec()
        executor = TripletexCommandExecutor(client, registry)
        router = DeterministicWorkflowRouter(registry=registry)

        def ensure_planner():
            nonlocal planner
            if planner is None:
                planner = build_planner(allow_noop=self.allow_noop)
            return planner

        with tempfile.TemporaryDirectory(prefix="tripletex-attachments-") as temp_dir:
            saved_attachments = self._save_attachments(payload, Path(temp_dir))
            logger.info("solve.attachments.saved attachments=%s", _summarize_saved_attachments(saved_attachments))
            attachments = prepare_attachments(saved_attachments)
            logger.info("solve.attachments.prepared attachments=%s", _summarize_prepared_attachments(attachments))

            analysis_started_at = time.monotonic()
            analysis_source = "planner"
            task_analysis = ensure_planner().analyze_task(
                task_prompt=payload.prompt,
                attachments=attachments,
            )
            try:
                validate_task_analysis_contract(task_analysis)
            except ValueError as exc:
                raise PlannerError(f"Planner contract violation: {exc}") from exc
            self._ensure_budget_remaining(started_at, stage="analysis")
            normalized_task_analysis = normalize_task_analysis_method_selection(
                task_analysis=task_analysis,
            )
            if (
                normalized_task_analysis.method_name != task_analysis.method_name
                or normalized_task_analysis.method_arguments != task_analysis.method_arguments
                or normalized_task_analysis.missing_required_arguments != task_analysis.missing_required_arguments
            ):
                logger.info(
                    "solve.analysis.method.normalized from_method=%s to_method=%s notes=%s",
                    task_analysis.method_name,
                    normalized_task_analysis.method_name,
                    normalized_task_analysis.notes[-3:],
                )
            task_analysis = normalized_task_analysis
            logger.info(
                "solve.analysis.complete source=%s elapsed_ms=%s method=%s missing_required_arguments=%s task_family=%s operation=%s target_resource=%s risk=%s attachment_required=%s search_hints=%s payload_fields=%s ambiguity_notes=%s",
                analysis_source,
                round((time.monotonic() - analysis_started_at) * 1000, 1),
                task_analysis.method_name,
                task_analysis.missing_required_arguments,
                task_analysis.task_family,
                task_analysis.operation,
                task_analysis.target_resource,
                task_analysis.risk_level,
                task_analysis.attachment_required,
                sorted(task_analysis.search_hints.keys()),
                sorted(task_analysis.payload_fields.keys()),
                task_analysis.ambiguity_notes[:4],
            )
            internal_task = derive_internal_task(task_analysis=task_analysis)
            method_spec = METHOD_SPECS.get(internal_task.method_name)
            missing_required_arguments = resolved_missing_required_arguments(
                task_analysis,
                method_name=internal_task.method_name,
                internal_payload=internal_task.payload,
            )
            logger.info(
                "solve.method.extract method=%s arguments=%s missing_required_arguments=%s flow_kind=%s operation=%s target_resource=%s execution_strategy=%s coded_route=%s search=%s payload=%s notes=%s workflow_context=%s",
                internal_task.method_name,
                _trim_payload(task_analysis.method_arguments),
                missing_required_arguments,
                internal_task.flow_kind.value,
                internal_task.operation,
                internal_task.target_resource,
                method_spec.execution_strategy if method_spec is not None else "unknown",
                bool(method_spec and method_spec.coverage_status == "coded"),
                _trim_payload(internal_task.search),
                _trim_payload(internal_task.payload),
                list(internal_task.notes),
                _workflow_context(internal_task),
            )
            if method_spec is not None:
                logger.info(
                    "metric.solve.workflow_selection count=1 method=%s execution_strategy=%s coverage_status=%s target_resource=%s",
                    internal_task.method_name,
                    method_spec.execution_strategy,
                    method_spec.coverage_status,
                    internal_task.target_resource,
                )
                if method_spec.coverage_status == "wrapper_only":
                    logger.info(
                        "metric.solve.wrapper_only_selection count=1 method=%s target_resource=%s",
                        internal_task.method_name,
                        internal_task.target_resource,
                    )
            if internal_task.is_supported and missing_required_arguments:
                raise TaskInputError(
                    "Method extraction is incomplete. "
                    f"method={internal_task.method_name} "
                    f"missing_required_arguments={missing_required_arguments} "
                    f"arguments={_trim_payload(task_analysis.method_arguments)} "
                    f"payload={_trim_payload(internal_task.payload)} "
                    f"notes={list(internal_task.notes)}"
                )
            history: list[dict[str, Any]] = []
            api_calls_used = 0

            for attempt_index in range(self.max_planner_steps):
                self._ensure_budget_remaining(started_at, stage=f"step_{attempt_index + 1}_planning")
                logger.info(
                    "solve.step.start step=%s remaining_steps=%s api_calls_used=%s remaining_api_calls=%s history_entries=%s",
                    attempt_index + 1,
                    self.max_planner_steps - attempt_index,
                    api_calls_used,
                    self.max_api_calls - api_calls_used,
                    len(history),
                )
                planning_started_at = time.monotonic()
                decision_source = "method"
                if internal_task.is_supported:
                    decision = router.next_step(
                        internal_task=internal_task,
                        task_analysis=task_analysis,
                        history=history,
                    )
                    if decision is None:
                        logger.error(
                            "solve.step.router_exhausted step=%s method=%s flow_kind=%s history_entries=%s payload=%s notes=%s enable_llm_step_planning=%s",
                            attempt_index + 1,
                            internal_task.method_name,
                            internal_task.flow_kind.value,
                            len(history),
                            _trim_payload(internal_task.payload),
                            list(internal_task.notes),
                            self.enable_llm_step_planning,
                        )
                        logger.warning(
                            "metric.solve.missing_deterministic_route count=1 method=%s flow_kind=%s target_resource=%s",
                            internal_task.method_name,
                            internal_task.flow_kind.value,
                            internal_task.target_resource,
                        )
                        if not self.enable_llm_step_planning:
                            raise TaskInputError(
                                "No coded deterministic workflow is available for the analyzed task. "
                                f"method={internal_task.method_name} "
                                f"flow_kind={internal_task.flow_kind.value} "
                                f"task_analysis={_compact_task_analysis(task_analysis)} "
                                f"history={_summarize_history(history)}"
                            )
                        decision_source = "planner_fallback"
                        decision = ensure_planner().next_step(
                            task_prompt=payload.prompt,
                            task_analysis=task_analysis,
                            attachments=attachments,
                            history=history,
                            remaining_steps=self.max_planner_steps - attempt_index,
                            active_method_name=internal_task.method_name,
                            active_workflow_context=_workflow_context(internal_task),
                        )
                else:
                    if not self.enable_llm_step_planning:
                        raise SolveError(
                            "Task analysis selected a non-deterministic workflow, but LLM step planning is disabled. "
                            f"method={internal_task.method_name} "
                            f"flow_kind={internal_task.flow_kind.value} "
                            f"task_analysis={_compact_task_analysis(task_analysis)}"
                        )
                    decision_source = "planner"
                    decision = ensure_planner().next_step(
                        task_prompt=payload.prompt,
                        task_analysis=task_analysis,
                        attachments=attachments,
                        history=history,
                        remaining_steps=self.max_planner_steps - attempt_index,
                        active_method_name=task_analysis.method_name,
                    )
                logger.info(
                    "solve.step.decision step=%s source=%s kind=%s elapsed_ms=%s reason=%r",
                    attempt_index + 1,
                    decision_source,
                    decision.kind,
                    round((time.monotonic() - planning_started_at) * 1000, 1),
                    decision.reason[:240],
                )
                if decision.kind == "finish":
                    if (
                        _finish_reason_indicates_failure(decision.reason)
                        and self.enable_llm_step_planning
                        and internal_task.is_supported
                        and decision_source in {"method", "planner_fallback"}
                    ):
                        logger.warning(
                            "solve.finish.workflow_recovery step=%s method=%s flow_kind=%s source=%s reason=%r",
                            attempt_index + 1,
                            internal_task.method_name,
                            internal_task.flow_kind.value,
                            decision_source,
                            decision.reason[:240],
                        )
                        history.append(
                            {
                                "reason": decision.reason,
                                "request": {
                                    "kind": "workflow_finish",
                                    "status": "unsuccessful",
                                    "method_name": internal_task.method_name,
                                    "flow_kind": internal_task.flow_kind.value,
                                },
                                "error": {
                                    "type": "workflow_finish",
                                    "message": decision.reason,
                                },
                            }
                        )
                        decision = ensure_planner().next_step(
                            task_prompt=payload.prompt,
                            task_analysis=task_analysis,
                            attachments=attachments,
                            history=history,
                            remaining_steps=self.max_planner_steps - attempt_index,
                            active_method_name=internal_task.method_name,
                            active_workflow_context=_workflow_context(internal_task),
                        )
                        decision_source = "planner_recovery"
                        logger.info(
                            "solve.step.decision step=%s source=%s kind=%s elapsed_ms=%s reason=%r",
                            attempt_index + 1,
                            decision_source,
                            decision.kind,
                            round((time.monotonic() - planning_started_at) * 1000, 1),
                            decision.reason[:240],
                        )

                    if _finish_reason_indicates_failure(decision.reason):
                        precondition_detail = _latest_tripletex_validation_detail(history)
                        if precondition_detail is not None:
                            message = decision.reason.strip()
                            if precondition_detail.lower() not in " ".join(message.lower().split()):
                                message = f"{message} Tripletex validation: {precondition_detail}"
                            logger.warning(
                                "solve.finish.precondition_failed step=%s total_elapsed_ms=%s reason=%r detail=%r history=%s",
                                attempt_index + 1,
                                round((time.monotonic() - started_at) * 1000, 1),
                                decision.reason[:240],
                                precondition_detail,
                                _summarize_history(history),
                            )
                            raise TaskPreconditionError(message)
                        if internal_task.is_supported and not self.enable_llm_step_planning:
                            logger.warning(
                                "solve.finish.deterministic_failed step=%s total_elapsed_ms=%s reason=%r history=%s",
                                attempt_index + 1,
                                round((time.monotonic() - started_at) * 1000, 1),
                                decision.reason[:240],
                                _summarize_history(history),
                            )
                            logger.warning(
                                "metric.solve.deterministic_failure count=1 method=%s flow_kind=%s target_resource=%s",
                                internal_task.method_name,
                                internal_task.flow_kind.value,
                                internal_task.target_resource,
                            )
                            raise TaskPreconditionError(decision.reason.strip())
                        logger.error(
                            "solve.finish.unsuccessful step=%s total_elapsed_ms=%s reason=%r history=%s",
                            attempt_index + 1,
                            round((time.monotonic() - started_at) * 1000, 1),
                            decision.reason[:240],
                            _summarize_history(history),
                        )
                        raise SolveError(
                            "Planner reported an unsuccessful finish before completing the task. "
                            f"reason={decision.reason!r} "
                            f"task_analysis={_compact_task_analysis(task_analysis)} "
                            f"history={_summarize_history(history)}"
                        )
                    logger.info(
                        "solve.finish step=%s total_elapsed_ms=%s",
                        attempt_index + 1,
                        round((time.monotonic() - started_at) * 1000, 1),
                    )
                    return SolveResponse(status="completed")

                try:
                    if decision.kind == "method":
                        method_call = decision.to_method_call()
                        command = generated_methods.command_for_call(
                            method_name=method_call.method_name,
                            arguments=method_call.arguments,
                            reason=decision.reason,
                        )
                    else:
                        command = decision.to_command()
                except (ValueError, GeneratedMethodError) as exc:
                    logger.warning(
                        "solve.method_call.validation_failed step=%s source=%s error=%r",
                        attempt_index + 1,
                        decision_source,
                        str(exc),
                    )
                    history.append(
                        {
                            "reason": decision.reason,
                            "request": {
                                "kind": decision.kind,
                                "action": (
                                    {
                                        "method": decision.action.method,
                                        "path": decision.action.path,
                                        "params": decision.action.params,
                                        "json": decision.action.json_body,
                                    }
                                    if decision.action is not None
                                    else None
                                ),
                                "method_call": (
                                    {
                                        "method_name": decision.method_call.method_name,
                                        "arguments": decision.method_call.arguments,
                                    }
                                    if decision.method_call is not None
                                    else None
                                ),
                            },
                            "error": {
                                "type": "method_call_validation",
                                "message": str(exc),
                            },
                        }
                    )
                    continue

                repair_result = repair_command(
                    command,
                    task_analysis=task_analysis,
                    history=history,
                    registry=registry,
                )
                original_command = command
                command = repair_result.command
                if repair_result.notes:
                    logger.info(
                        "solve.command.repaired step=%s repairs=%s before=%s after=%s",
                        attempt_index + 1,
                        list(repair_result.notes),
                        _command_signature(original_command),
                        _command_signature(command),
                    )
                logger.info(
                    "solve.command step=%s method=%s path=%s reason=%r params=%s json=%s history_tail=%s",
                    attempt_index + 1,
                    command.method,
                    command.path,
                    command.reason[:240],
                    _trim_payload(command.params),
                    _trim_payload(command.json_body),
                    _summarize_history(history[-3:]),
                )
                client.timeout_seconds = min(
                    self.timeout_seconds,
                    self._remaining_budget_seconds(started_at, reserve_seconds=1.0),
                )
                if client.timeout_seconds <= 0:
                    raise SolveError(
                        f"The solve budget expired before executing the next Tripletex API call. method={command.method} path={command.path}"
                    )
                execution_started_at = time.monotonic()
                duplicate_error = _prior_repeatable_tripletex_error(history, command)
                if duplicate_error is not None:
                    logger.warning(
                        "solve.command.skipped_duplicate_api_failure step=%s method=%s path=%s status=%s prior_error=%s",
                        attempt_index + 1,
                        command.method,
                        command.path,
                        duplicate_error.get("status_code"),
                        _trim_payload(duplicate_error),
                    )
                    history.append(
                        {
                            "reason": command.reason,
                            "request": {
                                "method": command.method,
                                "path": command.path,
                                "params": command.params,
                                "json": command.json_body,
                            },
                            "error": {
                                "type": "duplicate_tripletex_api",
                                "message": "Skipped repeating an identical Tripletex API request that already failed with a non-retryable 4xx error.",
                                "status_code": duplicate_error.get("status_code"),
                                "payload": duplicate_error.get("payload"),
                            },
                        }
                    )
                    continue
                try:
                    executor.validate(command)
                    if api_calls_used >= self.max_api_calls:
                        raise SolveError(
                            "Tripletex API call budget exhausted before task completion. "
                            f"api_calls_used={api_calls_used} max_api_calls={self.max_api_calls} "
                            f"task_analysis={_compact_task_analysis(task_analysis)} "
                            f"history={_summarize_history(history)}"
                        )
                    api_calls_used += 1
                    response_payload = executor.execute_prevalidated(command)
                except CommandExecutionError as exc:
                    logger.warning(
                        "solve.command.validation_failed step=%s method=%s path=%s error=%r command=%s",
                        attempt_index + 1,
                        command.method,
                        command.path,
                        str(exc),
                        _command_signature(command),
                    )
                    history.append(
                        {
                            "reason": command.reason,
                            "request": {
                                "method": command.method,
                                "path": command.path,
                                "params": command.params,
                                "json": command.json_body,
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
                        "solve.command.api_failed step=%s method=%s path=%s status=%s error=%s payload=%s validation_detail=%r command=%s",
                        attempt_index + 1,
                        command.method,
                        command.path,
                        exc.status_code,
                        str(exc),
                        _payload_signature(exc.payload),
                        _extract_validation_detail(exc.payload),
                        _command_signature(command),
                    )
                    history.append(
                        {
                            "reason": command.reason,
                            "request": {
                                "method": command.method,
                                "path": command.path,
                                "params": command.params,
                                "json": command.json_body,
                            },
                            "error": {
                                "type": "tripletex_api",
                                "status_code": exc.status_code,
                                "message": str(exc),
                                "payload": exc.payload,
                            },
                        }
                    )
                    if exc.status_code in {401, 403}:
                        raise TaskPreconditionError(
                            "Tripletex rejected a deterministic workflow step due to missing or invalid access. "
                            f"{exc}"
                        ) from exc
                    continue
                logger.info(
                    "solve.command.complete step=%s method=%s path=%s elapsed_ms=%s response=%s history_entries=%s",
                    attempt_index + 1,
                    command.method,
                    command.path,
                    round((time.monotonic() - execution_started_at) * 1000, 1),
                    _payload_signature(response_payload),
                    len(history) + 1,
                )
                history.append(
                    {
                        "reason": command.reason,
                        "request": {
                            "method": command.method,
                            "path": command.path,
                            "params": command.params,
                            "json": command.json_body,
                        },
                        "response": response_payload,
                    }
                )

        logger.error(
            "solve.exhausted total_elapsed_ms=%s max_planner_steps=%s api_calls_used=%s max_api_calls=%s task_analysis=%s history=%s",
            round((time.monotonic() - started_at) * 1000, 1),
            self.max_planner_steps,
            api_calls_used,
            self.max_api_calls,
            {
                "method_name": task_analysis.method_name,
                "method_arguments": _trim_payload(task_analysis.method_arguments),
                "missing_required_arguments": task_analysis.missing_required_arguments,
                "task_family": task_analysis.task_family,
                "operation": task_analysis.operation,
                "target_resource": task_analysis.target_resource,
                "risk_level": task_analysis.risk_level,
                "search_hints": _trim_payload(task_analysis.search_hints),
                "payload_fields": _trim_payload(task_analysis.payload_fields),
                "ambiguity_notes": task_analysis.ambiguity_notes[:6],
                "completion_signals": task_analysis.completion_signals[:6],
            },
            _summarize_history(history),
        )
        raise SolveError(
            "Planner exhausted its "
            f"{self.max_planner_steps}-step budget before finishing. "
            f"api_calls_used={api_calls_used} max_api_calls={self.max_api_calls} "
            f"task_analysis={_compact_task_analysis(task_analysis)} "
            f"history={_summarize_history(history)}"
        )

    def _remaining_budget_seconds(self, started_at: float, *, reserve_seconds: float = 0.0) -> float:
        return self.solve_budget_seconds - (time.monotonic() - started_at) - reserve_seconds

    def _ensure_budget_remaining(self, started_at: float, *, stage: str) -> None:
        remaining = self._remaining_budget_seconds(started_at)
        logger.info("solve.budget stage=%s remaining_seconds=%s", stage, round(max(remaining, 0.0), 3))
        if remaining <= 0:
            raise SolveError(
                f"The solve budget of {self.solve_budget_seconds}s was exhausted during {stage}."
            )

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


def _workflow_context(internal_task: Any) -> dict[str, Any]:
    return {
        "method_name": internal_task.method_name,
        "flow_kind": internal_task.flow_kind.value,
        "operation": internal_task.operation,
        "target_resource": internal_task.target_resource,
        "search": _trim_payload(internal_task.search),
        "payload": _trim_payload(internal_task.payload),
        "notes": list(internal_task.notes),
    }


def _payload_signature(value: Any) -> Any:
    if isinstance(value, dict):
        summary: dict[str, Any] = {"type": "dict", "keys": list(value.keys())[:10]}
        if isinstance(value.get("values"), list):
            summary["values_count"] = len(value["values"])
        if isinstance(value.get("value"), dict) and value["value"].get("id") not in {None, ""}:
            summary["value_id"] = value["value"]["id"]
        validation_detail = _extract_validation_detail(value)
        if validation_detail is not None:
            summary["validation_detail"] = validation_detail
        return summary
    if isinstance(value, list):
        return {"type": "list", "items": len(value)}
    return {"type": type(value).__name__, "value": str(value)[:240]}


def _command_signature(command: Any) -> dict[str, Any]:
    return {
        "method": command.method,
        "path": command.path,
        "params": _trim_payload(command.params),
        "json": _trim_payload(command.json_body),
    }


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
    base_url = str(base_url)
    if "://" not in base_url:
        return base_url[:120]
    scheme, rest = base_url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}"


def _summarize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for entry in history[-8:]:
        item: dict[str, Any] = {
            "reason": str(entry.get("reason", ""))[:240],
            "request": _trim_payload(entry.get("request")),
        }
        if "response" in entry:
            item["response"] = _payload_signature(entry.get("response"))
        if "error" in entry:
            item["error"] = _trim_payload(entry.get("error"))
        summary.append(item)
    return summary


def _compact_task_analysis(task_analysis: Any) -> dict[str, Any]:
    return {
        "method_name": task_analysis.method_name,
        "method_arguments": _trim_payload(task_analysis.method_arguments),
        "missing_required_arguments": task_analysis.missing_required_arguments,
        "task_family": task_analysis.task_family,
        "operation": task_analysis.operation,
        "target_resource": task_analysis.target_resource,
        "risk_level": task_analysis.risk_level,
        "search_hints": _trim_payload(task_analysis.search_hints),
        "payload_fields": _trim_payload(task_analysis.payload_fields),
        "ambiguity_notes": task_analysis.ambiguity_notes[:6],
        "completion_signals": task_analysis.completion_signals[:6],
    }


def _prior_repeatable_tripletex_error(history: list[dict[str, Any]], command: Any) -> dict[str, Any] | None:
    for entry in reversed(history):
        error = entry.get("error")
        if not isinstance(error, dict):
            continue
        if error.get("type") != "tripletex_api":
            continue
        status_code = error.get("status_code")
        if not isinstance(status_code, int) or status_code < 400 or status_code >= 500 or status_code == 429:
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != command.method.upper():
            continue
        if str(request.get("path") or "") != command.path:
            continue
        if request.get("params") != command.params:
            continue
        if request.get("json") != command.json_body:
            continue
        return error
    return None


def _finish_reason_indicates_failure(reason: str) -> bool:
    normalized = " ".join(str(reason).strip().lower().split())
    return any(
        token in normalized
        for token in (
            "unable to",
            "cannot ",
            "can't ",
            "could not",
            "did not",
            "not found",
            "no results",
            "no matching",
            "failed to",
            "cannot proceed",
            "couldn't",
        )
    )


def _latest_tripletex_validation_detail(history: list[dict[str, Any]]) -> str | None:
    for entry in reversed(history):
        error = entry.get("error")
        if not isinstance(error, dict):
            continue
        if error.get("type") not in {"tripletex_api", "duplicate_tripletex_api"}:
            continue
        status_code = error.get("status_code")
        payload = error.get("payload")
        if status_code != 422 or not isinstance(payload, dict):
            continue
        detail = _extract_validation_detail(payload)
        if detail is None:
            continue
        return detail
    return None


def _extract_validation_detail(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    validation_messages = payload.get("validationMessages")
    developer_message = str(payload.get("developerMessage") or "").upper()
    if developer_message != "VALIDATION_ERROR" and not (
        isinstance(validation_messages, list) and validation_messages
    ):
        return None
    details: list[str] = []
    if isinstance(validation_messages, list):
        for item in validation_messages[:3]:
            if isinstance(item, dict):
                message = item.get("message") or item.get("developerMessage")
                if message not in {None, ""}:
                    details.append(str(message))
            elif item not in {None, ""}:
                details.append(str(item))
    if not details:
        message = payload.get("message")
        if message not in {None, ""}:
            details.append(str(message))
    return "; ".join(_dedupe_preserve_order(details))[:400] or None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).strip().split())
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


__all__ = [
    "PlannerError",
    "CommandExecutionError",
    "OpenAPIRegistryError",
    "SolveError",
    "TaskPreconditionError",
    "TripletexAPIError",
    "TripletexSolver",
    "UnauthorizedError",
]
