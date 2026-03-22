from __future__ import annotations

import logging
import os
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.benchmark import BenchmarkRuntime, analysis_log_payload
from app.contracts import ExecutionContext, ExecutionResult, SolveRequest
from app.llm import LLMPlanner
from app.openapi_catalog import load_openapi_catalog
from app.raw.errors import RawExecutionError
from app.router import BridgeRouter


logger = logging.getLogger("tripletex_solver")


class SolveService:
    def __init__(
        self,
        planner: LLMPlanner | None = None,
        router: BridgeRouter | None = None,
        benchmark_runtime: BenchmarkRuntime | None = None,
    ) -> None:
        self.planner = planner or LLMPlanner()
        self.router = router or BridgeRouter()
        self.benchmark_runtime = benchmark_runtime or BenchmarkRuntime()
        self.timezone_name = os.getenv("TRIPLETEX_TIMEZONE", "Europe/Oslo")
        self.openapi_catalog = load_openapi_catalog()

    def execute(self, request: SolveRequest) -> ExecutionResult:
        request_id = str(uuid4())
        zone = ZoneInfo(self.timezone_name)
        now = datetime.now(zone)
        current_date = now.date().isoformat()
        benchmark_analysis, benchmark_bridge = self.benchmark_runtime.prepare_bridge(
            request,
            current_date=current_date,
            timezone=self.timezone_name,
            request_id=request_id,
        )
        logger.info(
            "solve.benchmark request_id=%s payload=%s",
            request_id,
            analysis_log_payload(benchmark_analysis),
        )
        bridge_source = "benchmark" if benchmark_bridge is not None else "legacy"
        bridge = benchmark_bridge or self._legacy_plan(
            request=request,
            current_date=current_date,
            timezone=self.timezone_name,
            request_id=request_id,
        )
        self._apply_request_context_defaults(
            bridge=bridge,
            request=request,
            request_id=request_id,
            current_date=current_date,
        )

        execution_context = ExecutionContext(
            base_url=request.tripletex_credentials.base_url,
            session_token=request.tripletex_credentials.session_token,
            request_id=request_id,
            current_date=current_date,
            timezone=self.timezone_name,
            attachments_by_id={
                f"attachment_{index}": {
                    "filename": file.filename,
                    "content_base64": file.content_base64,
                    "mime_type": file.mime_type,
                }
                for index, file in enumerate(request.files, start=1)
            },
        )
        logger.info(
            "solve.bridge request_id=%s source=%s executable=%s flows=%s commands=%s raw_ops=%s policy_keys=%s",
            request_id,
            bridge_source,
            bridge.validation.isExecutable,
            [step.resolved_name for step in bridge.executionPlan.selectedFlows],
            [step.resolved_name for step in bridge.executionPlan.selectedCommands],
            [step.operationId or step.resolved_name for step in bridge.executionPlan.fallbackRawCommands],
            self.router._selected_policy_keys(bridge),
        )
        try:
            result = self.router.execute(bridge, execution_context)
        except RawExecutionError as exc:
            if bridge_source == "benchmark":
                logger.warning(
                    "solve.benchmark_bridge_failed request_id=%s message=%s details=%s",
                    request_id,
                    exc.message,
                    exc.details,
                )
                bridge_source = "legacy"
                bridge = self._legacy_plan(
                    request=request,
                    current_date=current_date,
                    timezone=self.timezone_name,
                    request_id=request_id,
                )
                self._apply_request_context_defaults(
                    bridge=bridge,
                    request=request,
                    request_id=request_id,
                    current_date=current_date,
                )
                logger.info(
                    "solve.bridge request_id=%s source=%s executable=%s flows=%s commands=%s raw_ops=%s policy_keys=%s",
                    request_id,
                    bridge_source,
                    bridge.validation.isExecutable,
                    [step.resolved_name for step in bridge.executionPlan.selectedFlows],
                    [step.resolved_name for step in bridge.executionPlan.selectedCommands],
                    [step.operationId or step.resolved_name for step in bridge.executionPlan.fallbackRawCommands],
                    self.router._selected_policy_keys(bridge),
                )
                try:
                    result = self.router.execute(bridge, execution_context)
                except RawExecutionError as fallback_exc:
                    exc = fallback_exc
                else:
                    logger.info("solve.executed request_id=%s steps=%s", request_id, len(result.traces))
                    return result
            capability_issues = self._blocking_issues_from_capability_error(exc)
            if capability_issues:
                raise RawExecutionError(
                    message="Bridge JSON is blocked.",
                    details={"blockingIssues": capability_issues},
                ) from exc
            if exc.status_code in {400, 409, 422}:
                repaired_bridge = self.planner.repair_after_execution_error(
                    request=request,
                    bridge=bridge,
                    error=exc,
                    current_date=current_date,
                    timezone=self.timezone_name,
                    request_id=request_id,
                )
                logger.info(
                    "solve.bridge_retry request_id=%s flows=%s commands=%s raw_ops=%s policy_keys=%s",
                    request_id,
                    [step.resolved_name for step in repaired_bridge.executionPlan.selectedFlows],
                    [step.resolved_name for step in repaired_bridge.executionPlan.selectedCommands],
                    [step.operationId or step.resolved_name for step in repaired_bridge.executionPlan.fallbackRawCommands],
                    self.router._selected_policy_keys(repaired_bridge),
                )
                try:
                    result = self.router.execute(repaired_bridge, execution_context)
                except RawExecutionError as retry_exc:
                    capability_issues = self._blocking_issues_from_capability_error(retry_exc)
                    if capability_issues:
                        raise RawExecutionError(
                            message="Bridge JSON is blocked.",
                            details={"blockingIssues": capability_issues},
                        ) from retry_exc
                    blocking_issues = self._blocking_issues_from_retry_error(retry_exc)
                    if blocking_issues:
                        raise RawExecutionError(
                            message="Bridge JSON is blocked.",
                            details={"blockingIssues": blocking_issues},
                        ) from retry_exc
                    raise
            else:
                raise
        logger.info("solve.executed request_id=%s steps=%s", request_id, len(result.traces))
        return result

    def _legacy_plan(
        self,
        *,
        request: SolveRequest,
        current_date: str,
        timezone: str,
        request_id: str,
    ):
        return self.planner.plan(
            request,
            current_date=current_date,
            timezone=timezone,
            request_id=request_id,
        )

    def _apply_request_context_defaults(
        self,
        *,
        bridge,
        request: SolveRequest,
        request_id: str,
        current_date: str,
    ) -> None:
        if bridge.requestContext.requestId is None:
            bridge.requestContext.requestId = request_id
        if bridge.requestContext.currentDate is None:
            bridge.requestContext.currentDate = current_date
        if bridge.requestContext.timezone is None:
            bridge.requestContext.timezone = self.timezone_name
        if bridge.requestContext.promptCharCount is None:
            bridge.requestContext.promptCharCount = len(request.prompt)
        if bridge.requestContext.attachmentCount is None:
            bridge.requestContext.attachmentCount = len(request.files)
        if bridge.requestContext.hasTripletexCredentials is None:
            bridge.requestContext.hasTripletexCredentials = True
        if bridge.requestContext.baseUrlPresent is None:
            bridge.requestContext.baseUrlPresent = bool(request.tripletex_credentials.base_url)
        if bridge.requestContext.sessionTokenPresent is None:
            bridge.requestContext.sessionTokenPresent = bool(request.tripletex_credentials.session_token)

    def _blocking_issues_from_capability_error(self, error: RawExecutionError) -> list[str] | None:
        if error.status_code != 403:
            return None
        details = error.details if isinstance(error.details, dict) else {}
        operation_id = details.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            return None
        profile = self.openapi_catalog.capability_profile(operation_id)
        if not profile.get("isRestricted"):
            return None
        summary = profile.get("summary") or operation_id
        if profile.get("isPilotOnly"):
            return [f"The task requires {summary}, but that Tripletex API is restricted to pilot-enabled tenants."]
        return [f"The task requires {summary}, but that Tripletex API is restricted for the current tenant."]

    def _blocking_issues_from_retry_error(self, error: RawExecutionError) -> list[str] | None:
        if error.status_code not in {400, 409, 422}:
            return None
        details = error.details if isinstance(error.details, dict) else {}
        body = details.get("body")
        if not isinstance(body, dict):
            return None
        validation_messages = body.get("validationMessages")
        if not isinstance(validation_messages, list) or not validation_messages:
            return None
        blocking_issues: list[str] = []
        for item in validation_messages:
            if not isinstance(item, dict):
                return None
            message = str(item.get("message") or "").strip()
            if not message or not self._is_missing_required_message(message):
                return None
            field = str(item.get("field") or "").strip()
            if field:
                blocking_issues.append(f"Tripletex requires {field}: {message}")
            else:
                blocking_issues.append(f"Tripletex requires additional data: {message}")
        return blocking_issues or None

    def _is_missing_required_message(self, message: str) -> bool:
        normalized = message.strip().lower()
        required_markers = (
            "feltet må fylles ut",
            "kan ikke være",
            "required",
            "must be provided",
            "must not be empty",
            "cannot be empty",
            "mandatory",
        )
        return any(marker in normalized for marker in required_markers)
