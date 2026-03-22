from __future__ import annotations

import logging
from typing import Any

from app.contracts import ExecutionContext, ExecutionResult, LLMBridgeDocument, StepTrace
from app.raw import RawExecutor, load_raw_catalog
from app.raw.errors import RawExecutionError
from app.wrapper import CommandExecutor, FlowExecutor, load_wrapper_catalog
from app.wrapper.helpers import merge_maps


logger = logging.getLogger("tripletex_router")


class BridgeRouter:
    def __init__(
        self,
        flow_executor: FlowExecutor | None = None,
        command_executor: CommandExecutor | None = None,
        raw_executor: RawExecutor | None = None,
    ) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()
        self.raw_executor = raw_executor or RawExecutor(catalog=self.raw_catalog)
        self.command_executor = command_executor or CommandExecutor(
            raw_executor=self.raw_executor,
            wrapper_catalog=self.wrapper_catalog,
            raw_catalog=self.raw_catalog,
        )
        self.flow_executor = flow_executor or FlowExecutor(
            command_executor=self.command_executor,
            wrapper_catalog=self.wrapper_catalog,
        )

    def validate(self, bridge: LLMBridgeDocument) -> None:
        if not bridge.validation.isExecutable:
            raise RawExecutionError(message="Bridge JSON is blocked.", details={"blockingIssues": bridge.validation.blockingIssues})
        if bridge.validation.blockingIssues:
            raise RawExecutionError(message="Bridge JSON contains blocking issues.", details={"blockingIssues": bridge.validation.blockingIssues})

        steps = self._step_index(bridge)
        if not steps:
            raise RawExecutionError(message="Bridge JSON did not contain any executable steps.")
        for step_id, step in steps.items():
            if not step_id:
                raise RawExecutionError(message="Every selected flow/command must have a step id.")
            if step["kind"] == "flow":
                flow_name = step["name"]
                flow_type = step["object"].resolved_kind
                if flow_type == "business_flow" and not self.wrapper_catalog.has_flow(flow_name):
                    raise RawExecutionError(message=f"Unknown business flow: {flow_name}")
            else:
                operation_id = step["operation_id"]
                if step["kind"] == "command":
                    if step["object"].resolved_kind == "friendly_alias":
                        if not self.wrapper_catalog.has_command(step["name"]):
                            raise RawExecutionError(message=f"Unknown wrapper command: {step['name']}")
                        if operation_id and not self.raw_catalog.has(operation_id):
                            raise RawExecutionError(message=f"Unknown raw operationId referenced by command step: {operation_id}")
                    else:
                        if not operation_id or not self.raw_catalog.has(operation_id):
                            raise RawExecutionError(message=f"Unknown raw operationId: {operation_id}")
                parent_flow_step_id = getattr(step["object"], "parentFlowStepId", None)
                if parent_flow_step_id and parent_flow_step_id not in steps:
                    raise RawExecutionError(message=f"Command step {step_id} referenced unknown parent flow step {parent_flow_step_id}.")
        if bridge.executionPlan.stepOrder:
            missing = [step_id for step_id in bridge.executionPlan.stepOrder if step_id not in steps]
            if missing:
                raise RawExecutionError(message=f"stepOrder referenced unknown step ids: {', '.join(missing)}")

    def execute(self, bridge: LLMBridgeDocument, context: ExecutionContext) -> ExecutionResult:
        self.validate(bridge)
        result = ExecutionResult()
        steps = self._step_index(bridge)
        execution_order = bridge.executionPlan.stepOrder or self._default_order(bridge, steps)
        logger.info(
            "bridge.execute request_id=%s flows=%s commands=%s raw_ops=%s policy_keys=%s step_order=%s",
            context.request_id,
            [step["name"] for step in steps.values() if step["kind"] == "flow"],
            [
                step["name"]
                for step in steps.values()
                if step["kind"] == "command" and step["object"].resolved_kind == "friendly_alias"
            ],
            [
                step["operation_id"]
                for step in steps.values()
                if step["kind"] == "command" and step["object"].resolved_kind != "friendly_alias"
            ],
            self._selected_policy_keys(bridge),
            execution_order,
        )
        for step_id in execution_order:
            step = steps[step_id]
            if step["kind"] == "flow":
                payload = self.flow_executor.execute(
                    step["name"],
                    self._bind_flow_inputs(bridge, step["object"], context),
                    context,
                )
                result.add_trace(StepTrace(step_id=step_id, step_type="flow", name=step["name"], outputs=payload))
                continue
            if step["object"].resolved_kind == "friendly_alias":
                inputs = self._bind_command_inputs(bridge, step["object"], context)
                payload = self.command_executor.execute(
                    step["name"],
                    inputs,
                    context,
                )
                result.add_trace(
                    StepTrace(
                        step_id=step_id,
                        step_type="command",
                        name=step["name"],
                        operation_id=step["operation_id"],
                        inputs=inputs,
                        outputs=payload,
                    )
                )
                continue
            inputs = self._bind_command_inputs(bridge, step["object"], context)
            payload = self.raw_executor.execute(step["operation_id"], inputs, context)
            result.add_trace(
                StepTrace(
                    step_id=step_id,
                    step_type="raw_operation",
                    name=step["operation_id"],
                    operation_id=step["operation_id"],
                    inputs=inputs,
                    outputs=payload,
                )
            )
        return result

    def _step_index(self, bridge: LLMBridgeDocument) -> dict[str, dict[str, Any]]:
        steps: dict[str, dict[str, Any]] = {}
        for index, flow in enumerate(bridge.executionPlan.selectedFlows, start=1):
            step_id = flow.stepId or f"flow_{index}"
            steps[step_id] = {"kind": "flow", "name": flow.resolved_name, "object": flow, "operation_id": None}
        command_index = 1
        for command in [*bridge.executionPlan.selectedCommands, *bridge.executionPlan.fallbackRawCommands]:
            step_id = command.stepId or f"cmd_{command_index}"
            command_index += 1
            steps[step_id] = {
                "kind": "command",
                "name": command.resolved_name,
                "object": command,
                "operation_id": command.operationId,
            }
        return steps

    def _default_order(self, bridge: LLMBridgeDocument, steps: dict[str, dict[str, Any]]) -> list[str]:
        ordered: list[str] = []
        for step_id, step in steps.items():
            if step["kind"] == "flow":
                ordered.append(step_id)
        for step_id, step in steps.items():
            if step["kind"] != "command":
                continue
            if getattr(step["object"], "parentFlowStepId", None):
                continue
            ordered.append(step_id)
        return ordered

    def _entity_layer(self, bridge: LLMBridgeDocument) -> dict[str, Any]:
        data: dict[str, Any] = {}
        rich_entities = bridge.richData.entities or {}
        for family, entity_id in bridge.flatBridge.primaryEntityRefs.items():
            denormalized = bridge.flatBridge.byEntityId.get(entity_id, {})
            data.update(denormalized)
            family_entities = rich_entities.get(family, [])
            if isinstance(family_entities, list):
                for entity in family_entities:
                    if entity.get("entityId") == entity_id:
                        data.update(entity.get("denormalizedAliases", {}))
                        data.update(entity.get("selectors", {}))
                        data.update(entity.get("payload", {}))
        return data

    def _bind_flow_inputs(self, bridge: LLMBridgeDocument, step: Any, context: ExecutionContext) -> dict[str, Any]:
        flow_name = step.resolved_name
        merged = merge_maps(
            self._entity_layer(bridge),
            bridge.flatBridge.fieldBag,
            bridge.flatBridge.flowArguments.get(flow_name, {}),
            step.inputs,
        )
        return self._filter_inputs(merged, self._legal_flow_inputs(flow_name))

    def _bind_command_inputs(self, bridge: LLMBridgeDocument, step: Any, context: ExecutionContext) -> dict[str, Any]:
        keys = [step.resolved_name]
        if step.operationId:
            keys.append(step.operationId)
        command_inputs: dict[str, Any] = {}
        for key in keys:
            command_inputs.update(bridge.flatBridge.commandArguments.get(key, {}))
        merged = merge_maps(
            self._entity_layer(bridge),
            bridge.flatBridge.fieldBag,
            command_inputs,
            step.inputs,
        )
        if step.resolved_kind == "friendly_alias":
            return self._filter_inputs(merged, self._legal_command_inputs(step.resolved_name))
        if step.operationId:
            return self._filter_inputs(merged, self._legal_raw_inputs(step.operationId))
        return {}

    def _filter_inputs(self, payload: dict[str, Any], allowed_inputs: list[str]) -> dict[str, Any]:
        allowed = set(allowed_inputs)
        return {key: value for key, value in payload.items() if key in allowed}

    def _legal_flow_inputs(self, flow_name: str) -> list[str]:
        meta = self.wrapper_catalog.get_flow(flow_name)
        return [name for name in meta.get("inputs", []) if name]

    def _legal_command_inputs(self, command_name: str) -> list[str]:
        meta = self.wrapper_catalog.get_command(command_name)
        legal_inputs = [name for name in meta.get("inputs", []) if name]
        if meta.get("allowsBodyPassthrough"):
            legal_inputs.extend(["body", "payload"])
            raw_meta = self.raw_catalog.get(meta["operationId"])
            legal_inputs.extend(self._raw_body_fields(raw_meta))
        return sorted(dict.fromkeys(legal_inputs))

    def _legal_raw_inputs(self, operation_id: str) -> list[str]:
        raw_meta = self.raw_catalog.get(operation_id)
        legal_inputs = [item["name"] for item in raw_meta["pathParams"]]
        legal_inputs.extend(item["name"] for item in raw_meta["queryParams"])
        if raw_meta.get("requestBody"):
            legal_inputs.append("body")
            legal_inputs.extend(self._raw_body_fields(raw_meta))
        return sorted(dict.fromkeys(name for name in legal_inputs if name))

    def _raw_body_fields(self, raw_meta: dict[str, Any]) -> list[str]:
        body_schema = next(iter(raw_meta.get("requestBody", {}).get("content", {}).values()), {})
        return sorted(
            name
            for name, value in body_schema.get("properties", {}).items()
            if not value.get("readOnly")
        )

    def _selected_policy_keys(self, bridge: LLMBridgeDocument) -> list[str]:
        policy_keys: set[str] = set()
        for flow in bridge.executionPlan.selectedFlows:
            if flow.resolved_kind != "business_flow" or not self.wrapper_catalog.has_flow(flow.resolved_name):
                continue
            flow_meta = self.wrapper_catalog.get_flow(flow.resolved_name)
            for command_name in flow_meta.get("commandNames", []):
                if self.wrapper_catalog.has_command(command_name):
                    policy_key = self.wrapper_catalog.get_command(command_name).get("conformancePolicyKey")
                    if policy_key:
                        policy_keys.add(policy_key)
        for command in bridge.executionPlan.selectedCommands:
            if command.resolved_kind == "friendly_alias" and self.wrapper_catalog.has_command(command.resolved_name):
                policy_key = self.wrapper_catalog.get_command(command.resolved_name).get("conformancePolicyKey")
                if policy_key:
                    policy_keys.add(policy_key)
        for command in bridge.executionPlan.fallbackRawCommands:
            if command.operationId and self.raw_catalog.has(command.operationId):
                policy_key = self.raw_catalog.get(command.operationId).get("conformancePolicyKey")
                if policy_key:
                    policy_keys.add(policy_key)
        return sorted(policy_keys)
