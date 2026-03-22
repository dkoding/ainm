from __future__ import annotations

import json
from typing import Any

from app.llm.contract_utils import input_names, split_required_inputs
from app.llm.json_payloads import load_json_payload
from app.openapi_schema_guard import validate_request_body_schema_value, validate_request_body_value
from app.openapi_catalog import load_openapi_catalog
from pydantic import ValidationError

from app.contracts import LLMBridgeDocument
from app.raw import load_raw_catalog
from app.raw.errors import RawExecutionError
from app.raw.input_coercion import RawInputCoercer
from app.runtime_refs import canonical_step_output_binding, canonical_step_output_reference, iter_step_output_bindings
from app.semantic_contract import (
    canonicalize_payload_value,
    canonicalize_selector_value,
    clean_contract_name,
    payload_reference_selector_family,
    to_raw_payload_value,
)
from app.wrapper import load_wrapper_catalog
from app.wrapper.helpers import is_int_like, is_iso_date_string


class ResponseValidator:
    def __init__(self) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()
        self.openapi_catalog = load_openapi_catalog()
        self.input_coercer = RawInputCoercer(raw_catalog=self.raw_catalog)

    def validate(self, payload: str | dict[str, Any]) -> LLMBridgeDocument:
        if isinstance(payload, str):
            data = self._load_json_payload(payload)
        else:
            data = payload
        data = self._normalize(data)
        try:
            bridge = LLMBridgeDocument.model_validate(data)
        except ValidationError as exc:
            raise RawExecutionError(message="Planner output did not match the bridge schema.", details={"errors": exc.errors()}) from exc
        self._canonicalize_admissibility(bridge)
        self._validate_references(bridge)
        self._validate_content(bridge)
        return bridge

    def _normalize(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RawExecutionError(message="Planner output root must be a JSON object.")
        data = dict(payload)
        defaults = data.pop("__tripletex_defaults", {})
        data["contractVersion"] = self._normalize_contract_version(data.get("contractVersion"))
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
            self._assign_step_ids(execution_plan["selectedFlows"], prefix="flow")
            self._assign_step_ids(execution_plan["selectedCommands"], prefix="cmd")
            self._assign_step_ids(execution_plan["fallbackRawCommands"], prefix="raw")
            fallback_raw_commands: list[dict[str, Any]] = []
            for step in execution_plan["fallbackRawCommands"]:
                if self._is_raw_command_step(step):
                    fallback_raw_commands.append(self._coerce_raw_command_step(step))
                else:
                    fallback_raw_commands.append(step)
            execution_plan["fallbackRawCommands"] = fallback_raw_commands

        sources = data.get("sources")
        if isinstance(sources, dict):
            attachments = sources.get("attachments")
            default_attachments = defaults.get("attachments") if isinstance(defaults.get("attachments"), list) else []
            if attachments is None:
                sources["attachments"] = list(default_attachments)
            elif not isinstance(attachments, list):
                sources["attachments"] = [attachments]
            elif not attachments and default_attachments:
                sources["attachments"] = list(default_attachments)
            sources_prompt = self._normalize_text_evidence(sources.get("prompt"))
            if sources_prompt is not None:
                sources["prompt"] = sources_prompt
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
            prompt_original = self._normalize_text_evidence(language.get("promptOriginal"))
            if prompt_original is not None:
                language["promptOriginal"] = prompt_original
            prompt_canonical = self._normalize_text_evidence(language.get("promptCanonical"))
            if prompt_canonical is not None:
                language["promptCanonical"] = prompt_canonical
            if not language.get("promptOriginal") and defaults.get("prompt"):
                language["promptOriginal"] = defaults["prompt"]
            if not language.get("promptCanonical") and language.get("promptOriginal"):
                language["promptCanonical"] = language["promptOriginal"]

        understanding = data.get("understanding")
        if isinstance(understanding, dict):
            objective = self._normalize_text_evidence(understanding.get("objective"))
            if objective is not None:
                understanding["objective"] = objective
            if not understanding.get("objective") and language and language.get("promptCanonical"):
                understanding["objective"] = language["promptCanonical"]

        validation = data.get("validation")
        if isinstance(validation, dict):
            for key in ("blockingIssues", "warnings", "missingRequiredData", "highRiskActions", "contradictions"):
                validation[key] = self._normalize_issue_list(validation.get(key))

        self._normalize_known_arguments(data)
        return data

    def _normalize_text_evidence(self, value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if not isinstance(value, dict):
            return None
        for key in (
            "text",
            "prompt",
            "promptOriginal",
            "promptCanonical",
            "textOriginal",
            "textCanonical",
            "content",
            "value",
            "raw",
        ):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    def _validate_step_output_bindings(self, bridge: LLMBridgeDocument) -> None:
        illegal_global_binding = self._first_step_binding(bridge.flatBridge.fieldBag)
        if illegal_global_binding is not None:
            location, binding = illegal_global_binding
            raise RawExecutionError(
                message=(
                    f"flatBridge.fieldBag may not contain step-output bindings at {location} for {binding['stepId']}. "
                    "Place step-output bindings inside the specific step inputs that consume them."
                )
            )
        execution_order = self._effective_step_order(bridge)
        positions = {step_id: index for index, step_id in enumerate(execution_order)}
        for step in bridge.executionPlan.selectedFlows:
            self._validate_step_output_bindings_for_payload(
                payload={**bridge.flatBridge.flowArguments.get(step.resolved_name, {}), **step.inputs},
                owner_step_id=step.stepId or "",
                positions=positions,
            )
        for step in [*bridge.executionPlan.selectedCommands, *bridge.executionPlan.fallbackRawCommands]:
            payload: dict[str, Any] = {}
            for key in (step.resolved_name, step.operationId):
                if key:
                    payload.update(bridge.flatBridge.commandArguments.get(key, {}))
            payload.update(step.inputs)
            self._validate_step_output_bindings_for_payload(
                payload=payload,
                owner_step_id=step.stepId or "",
                positions=positions,
            )

    def _validate_step_output_bindings_for_payload(
        self,
        *,
        payload: dict[str, Any],
        owner_step_id: str,
        positions: dict[str, int],
    ) -> None:
        if not owner_step_id:
            return
        owner_position = positions.get(owner_step_id)
        if owner_position is None:
            raise RawExecutionError(message=f"Planner referenced unknown step position for {owner_step_id}.")
        for location, binding in iter_step_output_bindings(payload):
            referenced_position = positions.get(binding["stepId"])
            if referenced_position is None:
                raise RawExecutionError(
                    message=(
                        f"{owner_step_id} references unknown prior step {binding['stepId']} at {location}. "
                        "Step-output bindings must reference a selected step."
                    )
                )
            if referenced_position >= owner_position:
                raise RawExecutionError(
                    message=(
                        f"{owner_step_id} references {binding['stepId']} at {location}, but step-output bindings must "
                        "point only to earlier executed steps."
                    )
                )

    def _default_step_order(self, bridge: LLMBridgeDocument) -> list[str]:
        ordered = [step.stepId for step in bridge.executionPlan.selectedFlows if step.stepId]
        ordered.extend(step.stepId for step in bridge.executionPlan.selectedCommands if step.stepId)
        ordered.extend(step.stepId for step in bridge.executionPlan.fallbackRawCommands if step.stepId)
        return ordered

    def _effective_step_order(self, bridge: LLMBridgeDocument) -> list[str]:
        if not bridge.executionPlan.stepOrder:
            return self._default_step_order(bridge)
        ordered = list(bridge.executionPlan.stepOrder)
        for step_id in self._default_step_order(bridge):
            if step_id not in ordered:
                ordered.append(step_id)
        return ordered

    def _first_step_binding(self, value: Any) -> tuple[str, dict[str, str]] | None:
        bindings = iter_step_output_bindings(value)
        return bindings[0] if bindings else None

    def _load_json_payload(self, payload: str) -> Any:
        try:
            return load_json_payload(payload)
        except json.JSONDecodeError as exc:
            raise RawExecutionError(message="Planner output was not valid JSON.") from exc

    def _normalize_contract_version(self, value: Any) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            return "tripletex.llm_bridge.v1"
        if text == "tripletex.llm_bridge.v1":
            return text
        if text.startswith("tripletex.") and text.endswith(".v1"):
            return "tripletex.llm_bridge.v1"
        return text

    def _normalize_step(self, payload: dict[str, Any]) -> dict[str, Any]:
        step = dict(payload)
        inputs = step.get("inputs")
        if inputs is None or isinstance(inputs, list):
            step["inputs"] = {}
        elif isinstance(inputs, dict):
            step["inputs"] = self._clean_argument_keys(inputs)
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

    def _assign_step_ids(self, steps: list[dict[str, Any]], *, prefix: str) -> None:
        for index, step in enumerate(steps, start=1):
            if not step.get("stepId"):
                step["stepId"] = f"{prefix}_{index}"

    def _clean_argument_keys(self, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            cleaned[clean_contract_name(str(key))] = value
        return cleaned

    def _normalize_issue_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        items = value if isinstance(value, list) else [value]
        normalized: list[str] = []
        for item in items:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                message = item.get("message")
                if isinstance(message, str):
                    text = message.strip()
                else:
                    text = json.dumps(item, ensure_ascii=False, sort_keys=True)
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    def _normalize_known_arguments(self, data: dict[str, Any]) -> None:
        flat_bridge = data.get("flatBridge")
        if not isinstance(flat_bridge, dict):
            return
        flow_arguments = flat_bridge.get("flowArguments")
        if isinstance(flow_arguments, dict):
            normalized_flow_arguments: dict[str, Any] = {}
            for flow_name, payload in flow_arguments.items():
                if not isinstance(payload, dict):
                    normalized_flow_arguments[flow_name] = payload
                    continue
                cleaned_payload = self._clean_argument_keys(payload)
                if self.wrapper_catalog.has_flow(flow_name):
                    cleaned_payload = self._normalize_flow_payload(flow_name, cleaned_payload)
                normalized_flow_arguments[flow_name] = cleaned_payload
            flat_bridge["flowArguments"] = normalized_flow_arguments
        command_arguments = flat_bridge.get("commandArguments")
        if isinstance(command_arguments, dict):
            normalized_command_arguments: dict[str, Any] = {}
            for command_name, payload in command_arguments.items():
                if not isinstance(payload, dict):
                    normalized_command_arguments[command_name] = payload
                    continue
                cleaned_payload = self._clean_argument_keys(payload)
                if self.wrapper_catalog.has_command(command_name):
                    cleaned_payload = self._normalize_command_payload(command_name, cleaned_payload)
                    cleaned_payload = self.input_coercer.normalize_command_inputs(
                        self.wrapper_catalog.get_command(command_name),
                        cleaned_payload,
                    )
                elif self.raw_catalog.has(command_name):
                    cleaned_payload = self.input_coercer.normalize_operation_inputs(command_name, cleaned_payload)
                normalized_command_arguments[command_name] = cleaned_payload
            flat_bridge["commandArguments"] = normalized_command_arguments

        execution_plan = data.get("executionPlan")
        if not isinstance(execution_plan, dict):
            return
        for step in execution_plan.get("selectedFlows", []):
            if isinstance(step.get("inputs"), dict) and self.wrapper_catalog.has_flow(step.get("flowName") or step.get("name") or ""):
                flow_name = step.get("flowName") or step.get("name") or ""
                step["inputs"] = self._normalize_flow_payload(flow_name, step["inputs"])
        for step in execution_plan.get("selectedCommands", []):
            command_name = step.get("commandName") or step.get("command") or ""
            if isinstance(step.get("inputs"), dict) and self.wrapper_catalog.has_command(command_name):
                step["inputs"] = self.input_coercer.normalize_command_inputs(
                    self.wrapper_catalog.get_command(command_name),
                    self._normalize_command_payload(command_name, step["inputs"]),
                )
        for step in execution_plan.get("fallbackRawCommands", []):
            operation_id = step.get("operationId") or step.get("commandName") or step.get("command") or ""
            if isinstance(step.get("inputs"), dict) and self.raw_catalog.has(operation_id):
                step["inputs"] = self.input_coercer.normalize_operation_inputs(operation_id, step["inputs"])

    def _normalize_flow_payload(self, flow_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        meta = self.wrapper_catalog.get_flow(flow_name)
        semantics = meta.get("inputSemantics", {})
        normalized = dict(payload)
        for key, semantic in semantics.items():
            if key not in normalized:
                continue
            normalized[key] = self._normalize_semantic_value(normalized[key], semantic)
        return normalized

    def _normalize_command_payload(self, command_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        meta = self.wrapper_catalog.get_command(command_name)
        normalized = dict(payload)
        selector_family = meta.get("selectorFamily")
        if selector_family:
            normalized = canonicalize_selector_value(selector_family, normalized)
        for key, semantic in meta.get("inputSemantics", {}).items():
            if key not in normalized:
                continue
            normalized[key] = self._normalize_semantic_value(normalized[key], semantic)
        return normalized

    def _normalize_semantic_value(self, value: Any, semantic: dict[str, Any]) -> Any:
        kind = semantic.get("kind")
        if kind in {"selector", "selector_or_create_payload"}:
            return canonicalize_selector_value(semantic.get("selectorFamily"), value)
        if kind == "payload":
            return canonicalize_payload_value(semantic.get("payloadFamily"), value)
        if kind == "array_payload":
            return canonicalize_payload_value(semantic.get("itemFamily"), value)
        return value

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
            if flow.resolved_kind != "business_flow":
                raise RawExecutionError(message=f"Planner emitted unsupported flow kind {flow.resolved_kind}.")
            if flow.resolved_kind == "business_flow" and not self.wrapper_catalog.has_flow(flow.resolved_name):
                raise RawExecutionError(message=f"Planner referenced unknown business flow {flow.resolved_name}.")
            if not flow.stepId:
                raise RawExecutionError(message="Planner returned a flow step without stepId.")
            if flow.resolved_kind == "business_flow":
                self._validate_flow_inputs(bridge, flow)
        for command in bridge.executionPlan.selectedCommands:
            if not command.stepId:
                raise RawExecutionError(message="Planner returned a command step without stepId.")
            if command.resolved_kind != "friendly_alias":
                raise RawExecutionError(message="executionPlan.selectedCommands may only contain friendly command names.")
            if self.raw_catalog.has(command.resolved_name):
                raise RawExecutionError(message=f"Raw operationId {command.resolved_name} must go in fallbackRawCommands, not selectedCommands.")
            if not self.wrapper_catalog.has_command(command.resolved_name):
                raise RawExecutionError(message=f"Planner referenced unknown command {command.resolved_name}.")
            self._validate_command_inputs(bridge, command)
        for command in bridge.executionPlan.fallbackRawCommands:
            if not command.stepId:
                raise RawExecutionError(message="Planner returned a raw command step without stepId.")
            operation_id = command.operationId or (command.resolved_name if self.raw_catalog.has(command.resolved_name) else None)
            if not operation_id:
                raise RawExecutionError(message="Planner emitted a raw fallback step without a valid operationId.")
            if self.wrapper_catalog.has_command(command.resolved_name) and command.resolved_kind == "friendly_alias":
                raise RawExecutionError(message=f"Friendly command {command.resolved_name} must go in selectedCommands, not fallbackRawCommands.")
            if operation_id and not self.raw_catalog.has(operation_id):
                raise RawExecutionError(message=f"Planner referenced unknown raw operationId {operation_id}.")
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
        if bridge.validation.isExecutable and not (
            bridge.executionPlan.selectedFlows or bridge.executionPlan.selectedCommands or bridge.executionPlan.fallbackRawCommands
        ):
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
        self._validate_step_output_bindings(bridge)
        self._validate_policy_requirements(bridge)

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
        self._validate_flow_typed_inputs(payload, flow.resolved_name, bridge)

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
        self._validate_command_typed_inputs(payload, meta, bridge)
        self._validate_command_routing_choice(
            meta,
            command_name=command.resolved_name,
            executable=bridge.validation.isExecutable,
        )

    def _validate_command_routing_choice(
        self,
        meta: dict[str, Any],
        *,
        command_name: str,
        executable: bool,
    ) -> None:
        if not executable:
            return
        if meta.get("safetyClass") not in {"mutation", "destructive"}:
            return
        business_flows = [
            flow_name
            for flow_name in meta.get("workflowMembership", [])
            if isinstance(flow_name, str) and self.wrapper_catalog.has_flow(flow_name)
        ]
        if not business_flows:
            return
        raise RawExecutionError(
            message=(
                f"Planner chose direct mutation command {command_name} even though business flows exist: "
                f"{', '.join(sorted(dict.fromkeys(business_flows)))}. Use a documented business flow or block execution."
            )
        )

    def _legal_command_inputs(self, meta: dict[str, Any]) -> list[str]:
        legal_inputs = list(input_names(meta["inputs"]))
        if meta.get("allowsBodyPassthrough"):
            legal_inputs.extend(["body", "payload"])
            body_schema = self.input_coercer.openapi_catalog.body_schema(meta["operationId"])
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
            if item["required"]
            and payload.get(item["name"]) is None
            and not self.input_coercer.has_documented_default(operation_id, item["name"], section="path")
        ]
        missing_names.extend(
            item["name"]
            for item in meta["queryParams"]
            if item["required"]
            and payload.get(item["name"]) is None
            and not self.input_coercer.has_documented_default(operation_id, item["name"], section="query")
        )
        body_schema = self.input_coercer.openapi_catalog.body_schema(operation_id)
        required_body = body_schema.get("required", [])
        body_payload = payload.get("body") if isinstance(payload.get("body"), dict) else payload
        missing_names.extend(
            name
            for name in required_body
            if body_payload.get(name) is None
            and not self.input_coercer.has_documented_default(operation_id, name, section="body")
        )
        if missing_names:
            raise RawExecutionError(
                message=f"Planner omitted required inputs for raw operation {operation_id}: {', '.join(sorted(dict.fromkeys(missing_names)))}."
            )
        self._validate_raw_typed_inputs(payload, meta, bridge)

    def _legal_raw_inputs(self, meta: dict[str, Any]) -> list[str]:
        legal_inputs = [item["name"] for item in meta["pathParams"]]
        legal_inputs.extend(item["name"] for item in meta["queryParams"])
        if meta.get("requestBody"):
            legal_inputs.append("body")
            body_schema = self.input_coercer.openapi_catalog.body_schema(meta["operationId"])
            legal_inputs.extend(
                name
                for name, value in body_schema.get("properties", {}).items()
                if not value.get("readOnly")
            )
        return sorted(dict.fromkeys(name for name in legal_inputs if name))

    def _validate_flow_typed_inputs(self, payload: dict[str, Any], flow_name: str, bridge: LLMBridgeDocument) -> None:
        meta = self.wrapper_catalog.get_flow(flow_name)
        semantics = meta.get("inputSemantics", {})
        attachment_ids = self._attachment_ids(bridge)
        for key, value in payload.items():
            if value is None:
                continue
            semantic = semantics.get(key)
            if semantic:
                self._validate_semantic_value(
                    value,
                    semantic,
                    field_name=key,
                    executable=bridge.validation.isExecutable,
                    allow_unresolved_payload_refs=True,
                )
            if key in {"date_window", "search_date_window"}:
                self._validate_date_window(value, key)
            elif key == "attachment_id":
                if bridge.validation.isExecutable or attachment_ids:
                    self._validate_attachment_reference(value, attachment_ids)
            elif key.endswith("_date") or key in {"date", "voucher_date", "reverse_date", "credit_note_date", "payment_date"}:
                self._validate_date_value(value, key)

    def _validate_command_typed_inputs(self, payload: dict[str, Any], meta: dict[str, Any], bridge: LLMBridgeDocument) -> None:
        raw_meta = self.raw_catalog.get(meta["operationId"])
        bindings = meta.get("inputBindings", {})
        semantics = meta.get("inputSemantics", {})
        attachment_ids = self._attachment_ids(bridge)
        body_schema = self.input_coercer.openapi_catalog.body_schema(raw_meta["operationId"])
        body_properties = body_schema.get("properties", {})
        for key, value in payload.items():
            if value is None:
                continue
            semantic = semantics.get(key)
            if semantic:
                self._validate_semantic_value(
                    value,
                    semantic,
                    field_name=key,
                    executable=bridge.validation.isExecutable,
                )
            if key == "attachment_id":
                if bridge.validation.isExecutable or attachment_ids:
                    self._validate_attachment_reference(value, attachment_ids)
                continue
            if key in {"body", "payload"}:
                self._validate_request_body_value(value, raw_meta, key)
                continue
            binding = bindings.get(key)
            if binding is None:
                passthrough_schema = body_properties.get(key)
                if passthrough_schema:
                    self._validate_body_bound_value(
                        value,
                        schema=passthrough_schema,
                        field_name=f"body.{key}",
                        operation_id=raw_meta["operationId"],
                    )
                continue
            section = binding["targetSection"]
            if section == "control":
                self._validate_control_input(key, value)
                continue
            schema = self._schema_for_binding(raw_meta, section, binding["targetName"])
            if section == "body":
                self._validate_body_bound_value(
                    value,
                    schema=schema,
                    field_name=f"body.{binding['targetName']}",
                    operation_id=raw_meta["operationId"],
                    semantic=semantic,
                    value_strategy=binding.get("valueStrategy"),
                )
                continue
            self._validate_typed_value(
                value,
                field_name=key,
                schema=schema,
                value_strategy=binding.get("valueStrategy"),
            )

    def _validate_raw_typed_inputs(self, payload: dict[str, Any], meta: dict[str, Any], bridge: LLMBridgeDocument) -> None:
        attachment_ids = self._attachment_ids(bridge)
        for key, value in payload.items():
            if value is None:
                continue
            if key == "attachment_id":
                if bridge.validation.isExecutable or attachment_ids:
                    self._validate_attachment_reference(value, attachment_ids)
                continue
            if key == "body":
                self._validate_request_body_value(value, meta, key)
                continue
            schema = self._schema_for_raw_input(meta, key)
            self._validate_typed_value(value, field_name=key, schema=schema)

    def _schema_for_binding(self, raw_meta: dict[str, Any], section: str, target_name: str) -> dict[str, Any]:
        if section == "path":
            return next((item for item in raw_meta["pathParams"] if item["name"] == target_name), {})
        if section == "query":
            return next((item for item in raw_meta["queryParams"] if item["name"] == target_name), {})
        body_schema = self.input_coercer.openapi_catalog.body_schema(raw_meta["operationId"])
        return body_schema.get("properties", {}).get(target_name, {})

    def _schema_for_raw_input(self, raw_meta: dict[str, Any], input_name: str) -> dict[str, Any]:
        for item in [*raw_meta["pathParams"], *raw_meta["queryParams"]]:
            if item["name"] == input_name:
                return item
        body_schema = self.input_coercer.openapi_catalog.body_schema(raw_meta["operationId"])
        return body_schema.get("properties", {}).get(input_name, {})

    def _validate_typed_value(
        self,
        value: Any,
        *,
        field_name: str,
        schema: dict[str, Any],
        value_strategy: str | None = None,
    ) -> None:
        if canonical_step_output_binding(value) is not None:
            return
        step_reference = canonical_step_output_reference(value)
        if step_reference is not None and schema.get("type") != "string":
            raise RawExecutionError(
                message=(
                    f"{field_name} may not reference prior step outputs via {step_reference!r}. "
                    "The runtime does not dereference step-output placeholders for typed command or raw inputs."
                )
            )
        if field_name in {"from", "count"}:
            if not is_int_like(value):
                raise RawExecutionError(message=f"{field_name} must be an integer.")
            return
        if field_name == "fields":
            if not isinstance(value, (str, list)):
                raise RawExecutionError(message="fields must be a string or list.")
            return
        if field_name == "sorting":
            if not isinstance(value, (str, list)):
                raise RawExecutionError(message="sorting must be a string or list.")
            return
        if field_name.endswith("_date") or field_name in {"date", "startDate", "endDate"} or schema.get("format") == "date":
            self._validate_date_value(value, field_name)
            return
        if value_strategy in {"ref_id", "ref_object", "ref_list"} or field_name.endswith("_ref"):
            self._validate_ref_value(value, field_name, allow_list=value_strategy == "ref_list")
            return
        schema_type = schema.get("type")
        if schema_type == "integer":
            if not is_int_like(value):
                raise RawExecutionError(message=f"{field_name} must be an integer.")
            return
        if schema_type == "number":
            if not isinstance(value, (int, float)):
                raise RawExecutionError(message=f"{field_name} must be numeric.")
            return
        if schema_type == "boolean":
            if not isinstance(value, bool):
                raise RawExecutionError(message=f"{field_name} must be a boolean.")
            return
        if schema_type == "array":
            if not isinstance(value, list):
                raise RawExecutionError(message=f"{field_name} must be a list.")
            return
        if schema_type == "object":
            if not isinstance(value, dict):
                raise RawExecutionError(message=f"{field_name} must be an object.")
            if "id" in value and not is_int_like(value["id"]):
                raise RawExecutionError(message=f"{field_name}.id must be an integer id.")
            return
        if schema_type == "string" and not isinstance(value, str):
            raise RawExecutionError(message=f"{field_name} must be a string.")

    def _validate_semantic_value(
        self,
        value: Any,
        semantic: dict[str, Any],
        *,
        field_name: str,
        executable: bool,
        allow_unresolved_payload_refs: bool = False,
    ) -> None:
        kind = semantic.get("kind")
        if kind == "selector":
            self._validate_selector_value(
                value,
                selector_family=semantic.get("selectorFamily"),
                field_name=field_name,
            )
            return
        if kind == "selector_or_create_payload":
            if not isinstance(value, (dict, str, int)):
                raise RawExecutionError(message=f"{field_name} must be a selector object, string, or id.")
            return
        if kind == "payload":
            self._validate_payload_family(
                value,
                family=semantic.get("payloadFamily"),
                field_name=field_name,
                executable=executable,
                allow_unresolved_refs=allow_unresolved_payload_refs,
            )
            return
        if kind == "array_payload":
            if not isinstance(value, list):
                raise RawExecutionError(message=f"{field_name} must be a list.")
            for index, item in enumerate(value, start=1):
                self._validate_payload_family(
                    item,
                    family=semantic.get("itemFamily"),
                    field_name=f"{field_name}[{index}]",
                    executable=executable,
                    allow_unresolved_refs=allow_unresolved_payload_refs,
                )

    def _validate_selector_value(self, value: Any, *, selector_family: str | None, field_name: str) -> None:
        if canonical_step_output_binding(value) is not None:
            return
        if isinstance(value, (int, str)):
            return
        if not isinstance(value, dict):
            raise RawExecutionError(message=f"{field_name} must be a selector object, string, or id.")
        candidate = dict(value)
        if "id" in candidate and not is_int_like(candidate["id"]):
            if self._has_meaningful_selector_content(candidate):
                candidate.pop("id", None)
            else:
                raise RawExecutionError(message=f"{field_name}.id must be an integer id.")
        if selector_family is None:
            return
        allowed_fields = set(self.wrapper_catalog.selector_families.get(selector_family, {}).get("allowedFields", []))
        if not allowed_fields:
            return
        illegal = sorted(key for key, item in candidate.items() if item is not None and key not in allowed_fields)
        if illegal:
            raise RawExecutionError(
                message=f"{field_name} contains illegal selector fields for {selector_family}: {', '.join(illegal)}."
            )

    def _validate_payload_family(
        self,
        value: Any,
        *,
        family: str | None,
        field_name: str,
        executable: bool,
        allow_unresolved_refs: bool = False,
    ) -> None:
        if family is None:
            return
        if not isinstance(value, dict):
            raise RawExecutionError(message=f"{field_name} must be an object.")
        family_meta = self.wrapper_catalog.payload_families.get(family, {})
        allowed_fields = set(family_meta.get("allowedFields", []))
        illegal = sorted(key for key, item in value.items() if item is not None and allowed_fields and key not in allowed_fields)
        if illegal:
            raise RawExecutionError(
                message=f"{field_name} contains illegal fields for {family}: {', '.join(illegal)}."
            )
        if executable:
            missing = [name for name in family_meta.get("requiredFields", []) if value.get(name) is None]
            if missing:
                raise RawExecutionError(
                    message=f"{field_name} omitted required fields for {family}: {', '.join(missing)}."
                )
        for key, item in value.items():
            if item is None:
                continue
            if key.endswith("_ref"):
                if allow_unresolved_refs:
                    self._validate_resolvable_ref_value(
                        item,
                        f"{field_name}.{key}",
                        selector_family=payload_reference_selector_family(family, key),
                    )
                else:
                    self._validate_ref_value(item, f"{field_name}.{key}")

    def _validate_ref_value(self, value: Any, field_name: str, *, allow_list: bool = False) -> None:
        if allow_list:
            if not isinstance(value, list):
                raise RawExecutionError(message=f"{field_name} must be a list of id refs.")
            for item in value:
                self._validate_ref_value(item, field_name)
            return
        if canonical_step_output_binding(value) is not None:
            return
        step_reference = canonical_step_output_reference(value)
        if step_reference is not None:
            raise RawExecutionError(
                message=(
                    f"{field_name} may not reference prior step outputs via {step_reference!r}. "
                    "The runtime does not dereference step-output placeholders; use a selector or business flow instead."
                )
            )
        if isinstance(value, dict):
            if "id" not in value or not is_int_like(value["id"]):
                raise RawExecutionError(message=f"{field_name} must contain an integer id.")
            return
        if not is_int_like(value):
            raise RawExecutionError(message=f"{field_name} must be an integer id, numeric string, or object with id.")

    def _validate_resolvable_ref_value(
        self,
        value: Any,
        field_name: str,
        *,
        selector_family: str | None,
        allow_list: bool = False,
    ) -> None:
        if allow_list:
            if not isinstance(value, list):
                raise RawExecutionError(message=f"{field_name} must be a list of selector or id refs.")
            for item in value:
                self._validate_resolvable_ref_value(item, field_name, selector_family=selector_family)
            return
        if canonical_step_output_binding(value) is not None:
            return
        step_reference = canonical_step_output_reference(value)
        if step_reference is not None:
            raise RawExecutionError(
                message=(
                    f"{field_name} may not reference prior step outputs via {step_reference!r}. "
                    "The runtime does not dereference step-output placeholders; use selector data instead."
                )
            )
        if isinstance(value, (int, str)):
            return
        if not isinstance(value, dict):
            raise RawExecutionError(message=f"{field_name} must be a selector object, string, or id.")
        if "id" in value:
            step_reference = canonical_step_output_reference(value.get("id"))
            if step_reference is not None:
                raise RawExecutionError(
                    message=(
                        f"{field_name}.id may not reference prior step outputs via {step_reference!r}. "
                        "The runtime does not dereference step-output placeholders; use selector data instead."
                    )
                )
            if is_int_like(value["id"]):
                return
            candidate = dict(value)
            if self._has_meaningful_selector_content(candidate):
                candidate.pop("id", None)
                self._validate_selector_value(candidate, selector_family=selector_family, field_name=field_name)
                return
            raise RawExecutionError(message=f"{field_name}.id must be an integer id.")
        self._validate_selector_value(value, selector_family=selector_family, field_name=field_name)

    def _validate_request_body_value(self, value: Any, raw_meta: dict[str, Any], field_name: str) -> None:
        validate_request_body_value(
            value,
            raw_meta=raw_meta,
            field_name=field_name,
            operation_id=raw_meta.get("operationId", "raw operation"),
            body_label="Explicit body",
        )

    def _validate_request_body_schema_value(
        self,
        value: Any,
        *,
        schema: dict[str, Any],
        field_name: str,
        operation_id: str,
        body_label: str = "Explicit body",
    ) -> None:
        validate_request_body_schema_value(
            value,
            schema=schema,
            field_name=field_name,
            operation_id=operation_id,
            body_label=body_label,
        )

    def _validate_body_bound_value(
        self,
        value: Any,
        *,
        schema: dict[str, Any],
        field_name: str,
        operation_id: str,
        semantic: dict[str, Any] | None = None,
        value_strategy: str | None = None,
    ) -> None:
        translated = self._translate_body_bound_value(value, semantic=semantic, value_strategy=value_strategy)
        candidate = translated if translated is not None else value
        schema_type = schema.get("type")
        if schema_type in {"object", "array"} or isinstance(candidate, (dict, list)):
            self._validate_request_body_schema_value(
                candidate,
                schema=schema,
                field_name=field_name,
                operation_id=operation_id,
                body_label="Translated body",
            )
            return
        self._validate_typed_value(candidate, field_name=field_name, schema=schema, value_strategy=value_strategy)

    def _translate_body_bound_value(
        self,
        value: Any,
        *,
        semantic: dict[str, Any] | None,
        value_strategy: str | None,
    ) -> Any | None:
        if semantic:
            kind = semantic.get("kind")
            if kind == "payload":
                return to_raw_payload_value(semantic.get("payloadFamily"), value)
            if kind == "array_payload":
                return to_raw_payload_value(semantic.get("itemFamily"), value)
        if value_strategy == "ref_object":
            return self._coerce_ref_object_candidate(value)
        if value_strategy == "ref_list":
            if isinstance(value, list):
                return [self._coerce_ref_object_candidate(item) for item in value]
            return [self._coerce_ref_object_candidate(value)]
        if isinstance(value, (dict, list)):
            return value
        return None

    def _coerce_ref_object_candidate(self, value: Any) -> Any:
        if isinstance(value, dict):
            if "id" in value and is_int_like(value["id"]):
                identifier = value["id"]
                return {"id": int(str(identifier).strip()) if isinstance(identifier, str) else identifier}
            return value
        if is_int_like(value):
            return {"id": int(str(value).strip()) if isinstance(value, str) else value}
        return value

    def _validate_control_input(self, field_name: str, value: Any) -> None:
        self._validate_typed_value(value, field_name=field_name, schema={})

    def _validate_date_window(self, value: Any, field_name: str) -> None:
        if not isinstance(value, dict):
            raise RawExecutionError(message=f"{field_name} must be an object with from/to.")
        if value.get("from") is not None:
            self._validate_date_value(value.get("from"), f"{field_name}.from")
        if value.get("to") is not None:
            self._validate_date_value(value.get("to"), f"{field_name}.to")

    def _validate_date_value(self, value: Any, field_name: str) -> None:
        if not is_iso_date_string(value):
            raise RawExecutionError(message=f"{field_name} must be an ISO date string YYYY-MM-DD.")

    def _attachment_ids(self, bridge: LLMBridgeDocument) -> set[str]:
        return {
            item.get("attachmentId")
            for item in bridge.sources.attachments
            if isinstance(item, dict) and item.get("attachmentId")
        }

    def _canonicalize_admissibility(self, bridge: LLMBridgeDocument) -> None:
        if not bridge.validation.isExecutable:
            return
        if self._attachment_ids(bridge):
            return
        if not self._attachment_dependent_routes(bridge):
            return
        bridge.validation.isExecutable = False
        issue = "Selected attachment-dependent routes require at least one attachment in sources.attachments."
        if issue not in bridge.validation.blockingIssues:
            bridge.validation.blockingIssues.append(issue)

    def _validate_attachment_reference(self, value: Any, attachment_ids: set[str]) -> None:
        if not isinstance(value, str) or value not in attachment_ids:
            raise RawExecutionError(message=f"attachment_id must reference one of the known attachments: {sorted(attachment_ids)}.")

    def _attachment_dependent_routes(self, bridge: LLMBridgeDocument) -> list[str]:
        routes: list[str] = []
        for flow in bridge.executionPlan.selectedFlows:
            payload = dict(bridge.flatBridge.flowArguments.get(flow.resolved_name, {}))
            payload.update(flow.inputs)
            if self._payload_contains_key(payload, "attachment_id"):
                routes.append(flow.resolved_name)
                continue
            if not self.wrapper_catalog.has_flow(flow.resolved_name):
                continue
            flow_meta = self.wrapper_catalog.get_flow(flow.resolved_name)
            if any(
                self.wrapper_catalog.has_command(command_name)
                and self.wrapper_catalog.get_command(command_name).get("conformancePolicyKey") == "attachment_accounting"
                for command_name in flow_meta.get("commandNames", [])
            ):
                routes.append(flow.resolved_name)
        for command in bridge.executionPlan.selectedCommands:
            payload: dict[str, Any] = {}
            for key in (command.resolved_name, command.operationId):
                if key:
                    payload.update(bridge.flatBridge.commandArguments.get(key, {}))
            payload.update(command.inputs)
            if self._payload_contains_key(payload, "attachment_id"):
                routes.append(command.resolved_name)
                continue
            if self.wrapper_catalog.has_command(command.resolved_name):
                if self.wrapper_catalog.get_command(command.resolved_name).get("conformancePolicyKey") == "attachment_accounting":
                    routes.append(command.resolved_name)
        for command in bridge.executionPlan.fallbackRawCommands:
            operation_id = command.operationId or command.resolved_name
            payload: dict[str, Any] = {}
            for key in (operation_id, command.resolved_name):
                if key:
                    payload.update(bridge.flatBridge.commandArguments.get(key, {}))
            payload.update(command.inputs)
            if self._payload_contains_key(payload, "attachment_id"):
                routes.append(operation_id)
                continue
            if operation_id and self.raw_catalog.has(operation_id):
                if self.raw_catalog.get(operation_id).get("conformancePolicyKey") == "attachment_accounting":
                    routes.append(operation_id)
        return sorted(dict.fromkeys(name for name in routes if name))

    def _payload_contains_key(self, value: Any, target_key: str) -> bool:
        if isinstance(value, dict):
            if target_key in value and value[target_key] is not None:
                return True
            return any(self._payload_contains_key(item, target_key) for item in value.values())
        if isinstance(value, list):
            return any(self._payload_contains_key(item, target_key) for item in value)
        return False

    def _has_meaningful_selector_content(self, value: dict[str, Any]) -> bool:
        for key, item in value.items():
            if key == "id":
                continue
            if item is None:
                continue
            if isinstance(item, str) and not item.strip():
                continue
            if isinstance(item, (list, dict, tuple, set)) and not item:
                continue
            return True
        return False

    def _validate_policy_requirements(self, bridge: LLMBridgeDocument) -> None:
        policy_keys = set()
        for flow in bridge.executionPlan.selectedFlows:
            if self.wrapper_catalog.has_flow(flow.resolved_name):
                flow_meta = self.wrapper_catalog.get_flow(flow.resolved_name)
                for command_name in flow_meta.get("commandNames", []):
                    if self.wrapper_catalog.has_command(command_name):
                        policy_key = self.wrapper_catalog.get_command(command_name).get("conformancePolicyKey")
                        if policy_key:
                            policy_keys.add(policy_key)
        for command in bridge.executionPlan.selectedCommands:
            if self.wrapper_catalog.has_command(command.resolved_name):
                policy_key = self.wrapper_catalog.get_command(command.resolved_name).get("conformancePolicyKey")
                if policy_key:
                    policy_keys.add(policy_key)
        for command in bridge.executionPlan.fallbackRawCommands:
            operation_id = command.operationId or command.resolved_name
            if operation_id and self.raw_catalog.has(operation_id):
                policy_key = self.raw_catalog.get(operation_id).get("conformancePolicyKey")
                if policy_key:
                    policy_keys.add(policy_key)
        if "attachment_accounting" in policy_keys and bridge.validation.isExecutable and not self._attachment_ids(bridge):
            raise RawExecutionError(message="Attachment-accounting routes require at least one attachment in sources.attachments.")
