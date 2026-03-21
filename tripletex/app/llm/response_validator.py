from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.contracts import LLMBridgeDocument
from app.raw import load_raw_catalog
from app.raw.errors import RawExecutionError
from app.wrapper import load_wrapper_catalog


class ResponseValidator:
    def __init__(self) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()

    def validate(self, payload: str | dict[str, Any]) -> LLMBridgeDocument:
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RawExecutionError(message="Planner output was not valid JSON.") from exc
        else:
            data = payload
        try:
            bridge = LLMBridgeDocument.model_validate(data)
        except ValidationError as exc:
            raise RawExecutionError(message="Planner output did not match the bridge schema.", details={"errors": exc.errors()}) from exc
        self._validate_references(bridge)
        self._validate_content(bridge)
        return bridge

    def _validate_references(self, bridge: LLMBridgeDocument) -> None:
        for flow in bridge.executionPlan.selectedFlows:
            if flow.resolved_kind == "business_flow" and not self.wrapper_catalog.has_flow(flow.resolved_name):
                raise RawExecutionError(message=f"Planner referenced unknown business flow {flow.resolved_name}.")
            if not flow.stepId:
                raise RawExecutionError(message="Planner returned a flow step without stepId.")
        for command in [*bridge.executionPlan.selectedCommands, *bridge.executionPlan.fallbackRawCommands]:
            if not command.stepId:
                raise RawExecutionError(message="Planner returned a command step without stepId.")
            if command.resolved_kind == "friendly_alias":
                if not self.wrapper_catalog.has_command(command.resolved_name):
                    raise RawExecutionError(message=f"Planner referenced unknown command {command.resolved_name}.")
            if command.operationId and not self.raw_catalog.has(command.operationId):
                raise RawExecutionError(message=f"Planner referenced unknown raw operationId {command.operationId}.")

    def _validate_content(self, bridge: LLMBridgeDocument) -> None:
        if not bridge.language.promptOriginal:
            raise RawExecutionError(message="Planner output omitted language.promptOriginal.")
        if not bridge.language.promptCanonical:
            raise RawExecutionError(message="Planner output omitted language.promptCanonical.")
        if not bridge.understanding.objective:
            raise RawExecutionError(message="Planner output omitted understanding.objective.")
        if not (bridge.executionPlan.selectedFlows or bridge.executionPlan.selectedCommands or bridge.executionPlan.fallbackRawCommands):
            raise RawExecutionError(message="Planner output omitted executable steps.")
        if bridge.executionPlan.stepOrder:
            known_steps = {
                *[step.stepId for step in bridge.executionPlan.selectedFlows if step.stepId],
                *[step.stepId for step in bridge.executionPlan.selectedCommands if step.stepId],
                *[step.stepId for step in bridge.executionPlan.fallbackRawCommands if step.stepId],
            }
            missing = [step_id for step_id in bridge.executionPlan.stepOrder if step_id not in known_steps]
            if missing:
                raise RawExecutionError(
                    message=f"Planner output referenced unknown steps in stepOrder: {', '.join(missing)}."
                )
