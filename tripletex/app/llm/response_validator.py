from __future__ import annotations

import json
from typing import Any

from app.llm.contract_utils import input_names, split_required_inputs
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
        data = self._normalize(data)
        try:
            bridge = LLMBridgeDocument.model_validate(data)
        except ValidationError as exc:
            raise RawExecutionError(message="Planner output did not match the bridge schema.", details={"errors": exc.errors()}) from exc
        self._validate_references(bridge)
        self._validate_content(bridge)
        return bridge

    def _normalize(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RawExecutionError(message="Planner output root must be a JSON object.")
        data = dict(payload)
        defaults = data.pop("__tripletex_defaults", {})
        for key in (
            "requestContext",
            "language",
            "understanding",
            "sources",
            "richData",
            "flatBridge",
            "executionPlan",
            "validation",
            "completion",
        ):
            value = data.get(key)
            if value is None or isinstance(value, list):
                data[key] = {}

        execution_plan = data.get("executionPlan")
        if isinstance(execution_plan, dict):
            migrated_raw_steps: list[dict[str, Any]] = []
            for key in ("selectedFlows", "selectedCommands", "fallbackRawCommands", "stepOrder"):
                value = execution_plan.get(key)
                if value is None:
                    execution_plan[key] = []
                elif key != "stepOrder" and isinstance(value, dict):
                    execution_plan[key] = [value]
                elif key == "stepOrder" and isinstance(value, str):
                    execution_plan[key] = [value]
                elif not isinstance(value, list):
                    execution_plan[key] = []
            for key in ("selectedFlows", "selectedCommands", "fallbackRawCommands"):
                execution_plan[key] = [self._normalize_step(step) for step in execution_plan[key] if isinstance(step, dict)]
            selected_commands: list[dict[str, Any]] = []
            for step in execution_plan["selectedCommands"]:
                if self._is_raw_command_step(step):
                    migrated_raw_steps.append(self._coerce_raw_command_step(step))
                else:
                    selected_commands.append(step)
            execution_plan["selectedCommands"] = selected_commands
            fallback_raw_commands: list[dict[str, Any]] = []
            for step in execution_plan["fallbackRawCommands"]:
                if self._is_raw_command_step(step):
                    fallback_raw_commands.append(self._coerce_raw_command_step(step))
                else:
                    fallback_raw_commands.append(step)
            execution_plan["fallbackRawCommands"] = [*fallback_raw_commands, *migrated_raw_steps]

        sources = data.get("sources")
        if isinstance(sources, dict):
            attachments = sources.get("attachments")
            if attachments is None:
                sources["attachments"] = []
            elif not isinstance(attachments, list):
                sources["attachments"] = [attachments]
            if not sources.get("prompt") and defaults.get("prompt"):
                sources["prompt"] = defaults["prompt"]

        request_context = data.get("requestContext")
        if isinstance(request_context, dict):
            if not request_context.get("requestId") and defaults.get("requestId"):
                request_context["requestId"] = defaults["requestId"]
            if not request_context.get("currentDate") and defaults.get("currentDate"):
                request_context["currentDate"] = defaults["currentDate"]
            if not request_context.get("timezone") and defaults.get("timezone"):
                request_context["timezone"] = defaults["timezone"]
            if request_context.get("promptCharCount") is None and defaults.get("prompt"):
                request_context["promptCharCount"] = len(defaults["prompt"])
            if request_context.get("attachmentCount") is None and defaults.get("attachmentCount") is not None:
                request_context["attachmentCount"] = defaults["attachmentCount"]

        language = data.get("language")
        if isinstance(language, dict):
            if not language.get("promptOriginal") and defaults.get("prompt"):
                language["promptOriginal"] = defaults["prompt"]
            if not language.get("promptCanonical") and language.get("promptOriginal"):
                language["promptCanonical"] = language["promptOriginal"]

        understanding = data.get("understanding")
        if isinstance(understanding, dict):
            if not understanding.get("objective") and language and language.get("promptCanonical"):
                understanding["objective"] = language["promptCanonical"]

        return data

    def _normalize_step(self, payload: dict[str, Any]) -> dict[str, Any]:
        step = dict(payload)
        inputs = step.get("inputs")
        if inputs is None or isinstance(inputs, list):
            step["inputs"] = {}
        depends_on = step.get("dependsOn")
        if depends_on is None:
            step["dependsOn"] = []
        elif isinstance(depends_on, str):
            step["dependsOn"] = [depends_on]
        elif not isinstance(depends_on, list):
            step["dependsOn"] = []
        expected_outputs = step.get("expectedOutputs")
        if expected_outputs is None:
            step["expectedOutputs"] = []
        elif isinstance(expected_outputs, str):
            step["expectedOutputs"] = [expected_outputs]
        elif not isinstance(expected_outputs, list):
            step["expectedOutputs"] = []
        return step

    def _is_raw_command_step(self, step: dict[str, Any]) -> bool:
        resolved_kind = step.get("commandType") or step.get("kind") or ""
        resolved_name = step.get("commandName") or step.get("command") or step.get("operationId") or ""
        operation_id = step.get("operationId")
        if resolved_kind == "raw_operation":
            return True
        if operation_id and self.raw_catalog.has(operation_id):
            return True
        return bool(resolved_name and self.raw_catalog.has(resolved_name))

    def _coerce_raw_command_step(self, step: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(step)
        resolved_name = normalized.get("commandName") or normalized.get("command") or normalized.get("operationId") or ""
        if not normalized.get("operationId") and resolved_name and self.raw_catalog.has(resolved_name):
            normalized["operationId"] = resolved_name
        normalized["commandType"] = "raw_operation"
        normalized["kind"] = "raw_operation"
        return normalized

    def _validate_references(self, bridge: LLMBridgeDocument) -> None:
        for flow in bridge.executionPlan.selectedFlows:
            if flow.resolved_kind == "business_flow" and not self.wrapper_catalog.has_flow(flow.resolved_name):
                raise RawExecutionError(message=f"Planner referenced unknown business flow {flow.resolved_name}.")
            if not flow.stepId:
                raise RawExecutionError(message="Planner returned a flow step without stepId.")
            if flow.resolved_kind == "business_flow":
                self._validate_flow_inputs(bridge, flow)
        for command in [*bridge.executionPlan.selectedCommands, *bridge.executionPlan.fallbackRawCommands]:
            if not command.stepId:
                raise RawExecutionError(message="Planner returned a command step without stepId.")
            if command.resolved_kind == "friendly_alias":
                if not self.wrapper_catalog.has_command(command.resolved_name):
                    raise RawExecutionError(message=f"Planner referenced unknown command {command.resolved_name}.")
                self._validate_command_inputs(bridge, command)
            operation_id = command.operationId
            if operation_id and not self.raw_catalog.has(operation_id):
                raise RawExecutionError(message=f"Planner referenced unknown raw operationId {operation_id}.")
            if command.resolved_kind != "friendly_alias":
                self._validate_raw_inputs(bridge, command, operation_id or command.resolved_name)

    def _validate_content(self, bridge: LLMBridgeDocument) -> None:
        if not bridge.language.promptOriginal:
            bridge.language.promptOriginal = bridge.sources.prompt or bridge.language.promptCanonical
        if not bridge.language.promptCanonical:
            bridge.language.promptCanonical = bridge.language.promptOriginal or bridge.understanding.intentSummary
        if not bridge.understanding.objective:
            bridge.understanding.objective = bridge.understanding.intentSummary or bridge.language.promptCanonical
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

    def _validate_flow_inputs(self, bridge: LLMBridgeDocument, flow: Any) -> None:
        meta = self.wrapper_catalog.get_flow(flow.resolved_name)
        legal_inputs = input_names(meta["inputs"])
        required_inputs, _ = split_required_inputs(legal_inputs, meta.get("inputSpec"))
        payload = dict(bridge.flatBridge.flowArguments.get(flow.resolved_name, {}))
        payload.update(flow.inputs)
        illegal = sorted(key for key, value in payload.items() if value is not None and key not in legal_inputs)
        if illegal:
            raise RawExecutionError(
                message=f"Planner emitted illegal inputs for flow {flow.resolved_name}: {', '.join(illegal)}."
            )
        if bridge.validation.isExecutable:
            missing = [name for name in required_inputs if payload.get(name) is None]
            if missing:
                raise RawExecutionError(
                    message=f"Planner omitted required inputs for flow {flow.resolved_name}: {', '.join(missing)}."
                )

    def _validate_command_inputs(self, bridge: LLMBridgeDocument, command: Any) -> None:
        meta = self.wrapper_catalog.get_command(command.resolved_name)
        legal_inputs = self._legal_command_inputs(meta)
        required_inputs, _ = split_required_inputs(legal_inputs, meta.get("inputSpec"))
        payload: dict[str, Any] = {}
        for key in (command.resolved_name, command.operationId):
            if key:
                payload.update(bridge.flatBridge.commandArguments.get(key, {}))
        payload.update(command.inputs)
        illegal = sorted(key for key, value in payload.items() if value is not None and key not in legal_inputs)
        if illegal:
            raise RawExecutionError(
                message=f"Planner emitted illegal inputs for command {command.resolved_name}: {', '.join(illegal)}."
            )
        if bridge.validation.isExecutable:
            missing = [name for name in required_inputs if payload.get(name) is None]
            if missing:
                raise RawExecutionError(
                    message=f"Planner omitted required inputs for command {command.resolved_name}: {', '.join(missing)}."
                )

    def _legal_command_inputs(self, meta: dict[str, Any]) -> list[str]:
        legal_inputs = list(input_names(meta["inputs"]))
        if meta.get("allowsBodyPassthrough"):
            legal_inputs.extend(["body", "payload"])
            raw_meta = self.raw_catalog.get(meta["operationId"])
            body_schema = next(iter(raw_meta.get("requestBody", {}).get("content", {}).values()), {})
            legal_inputs.extend(
                name
                for name, value in body_schema.get("properties", {}).items()
                if not value.get("readOnly")
            )
        return sorted(dict.fromkeys(name for name in legal_inputs if name))

    def _validate_raw_inputs(self, bridge: LLMBridgeDocument, command: Any, operation_id: str) -> None:
        if not operation_id or not self.raw_catalog.has(operation_id):
            raise RawExecutionError(message="Planner emitted a raw operation step without a valid operationId.")
        meta = self.raw_catalog.get(operation_id)
        legal_inputs = self._legal_raw_inputs(meta)
        payload: dict[str, Any] = {}
        for key in (operation_id, command.resolved_name):
            if key:
                payload.update(bridge.flatBridge.commandArguments.get(key, {}))
        payload.update(command.inputs)
        illegal = sorted(key for key, value in payload.items() if value is not None and key not in legal_inputs)
        if illegal:
            raise RawExecutionError(
                message=f"Planner emitted illegal inputs for raw operation {operation_id}: {', '.join(illegal)}."
            )
        if not bridge.validation.isExecutable:
            return
        missing_names = [
            item["name"]
            for item in meta["pathParams"]
            if item["required"] and payload.get(item["name"]) is None
        ]
        missing_names.extend(
            item["name"]
            for item in meta["queryParams"]
            if item["required"] and payload.get(item["name"]) is None
        )
        body_schema = next(iter(meta.get("requestBody", {}).get("content", {}).values()), {})
        required_body = body_schema.get("required", [])
        body_payload = payload.get("body") if isinstance(payload.get("body"), dict) else payload
        missing_names.extend(name for name in required_body if body_payload.get(name) is None)
        if missing_names:
            raise RawExecutionError(
                message=f"Planner omitted required inputs for raw operation {operation_id}: {', '.join(sorted(dict.fromkeys(missing_names)))}."
            )

    def _legal_raw_inputs(self, meta: dict[str, Any]) -> list[str]:
        legal_inputs = [item["name"] for item in meta["pathParams"]]
        legal_inputs.extend(item["name"] for item in meta["queryParams"])
        if meta.get("requestBody"):
            legal_inputs.append("body")
            body_schema = next(iter(meta.get("requestBody", {}).get("content", {}).values()), {})
            legal_inputs.extend(
                name
                for name, value in body_schema.get("properties", {}).items()
                if not value.get("readOnly")
            )
        return sorted(dict.fromkeys(name for name in legal_inputs if name))
