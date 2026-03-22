from __future__ import annotations

import re
from typing import Any

from app.benchmark.models import BenchmarkRouteContract, TaskFamilyManifest
from app.llm.contract_utils import input_name
from app.openapi_catalog import load_openapi_catalog
from app.raw import load_raw_catalog
from app.semantic_contract import (
    command_input_semantics,
    copy_payload_families,
    copy_selector_families,
    flow_input_semantics,
)
from app.utils import normalize_key
from app.wrapper import load_wrapper_catalog
from app.wrapper.helpers import match_name


TOKEN_RE = re.compile(r"`([^`]+)`")


class RouteContractBuilder:
    def __init__(self) -> None:
        self.wrapper_catalog = load_wrapper_catalog()
        self.raw_catalog = load_raw_catalog()
        self.openapi_catalog = load_openapi_catalog()
        self.selector_families = copy_selector_families()
        self.payload_families = copy_payload_families()

    def build(self, manifest: TaskFamilyManifest) -> BenchmarkRouteContract | None:
        if manifest.preferred_flow_name:
            return self._build_flow_contract(manifest, manifest.preferred_flow_name)
        if manifest.preferred_command_names:
            return self._build_command_contract(manifest, manifest.preferred_command_names[0])
        if manifest.preferred_raw_operation_id:
            return self._build_raw_contract(manifest, manifest.preferred_raw_operation_id)
        return None

    def _build_flow_contract(self, manifest: TaskFamilyManifest, flow_name: str) -> BenchmarkRouteContract:
        meta = self.wrapper_catalog.get_flow(flow_name)
        legal_inputs = tuple(input_name(item) for item in meta.get("inputs", []) if input_name(item))
        input_semantics = {
            name: dict(meta.get("inputSemantics", {}).get(name) or flow_input_semantics(flow_name, name))
            for name in legal_inputs
        }
        selector_families, payload_families = self._family_context(input_semantics)
        return BenchmarkRouteContract(
            route_kind="flow",
            route_name=flow_name,
            legal_inputs=legal_inputs,
            required_input_groups=self._parse_required_input_groups(meta.get("inputSpec"), legal_inputs),
            input_semantics=input_semantics,
            selector_families=selector_families,
            payload_families=payload_families,
            create_payload_contracts=self._create_payload_contracts(input_semantics),
            openapi_hints=self._flow_openapi_hints(meta.get("commandNames", [])),
            notes=tuple(str(item) for item in meta.get("steps", []) if str(item).strip()),
        )

    def _build_command_contract(self, manifest: TaskFamilyManifest, command_name: str) -> BenchmarkRouteContract:
        meta = self.wrapper_catalog.get_command(command_name)
        legal_inputs = tuple(input_name(item) for item in meta.get("inputs", []) if input_name(item))
        input_semantics = {
            name: dict(meta.get("inputSemantics", {}).get(name) or command_input_semantics(command_name, name))
            for name in legal_inputs
        }
        selector_families, payload_families = self._family_context(input_semantics)
        required_groups = self._parse_required_input_groups(meta.get("inputSpec"), legal_inputs)
        if not required_groups:
            required_groups = self._required_groups_from_operation(meta.get("operationId"), legal_inputs)
        return BenchmarkRouteContract(
            route_kind="command",
            route_name=command_name,
            legal_inputs=legal_inputs,
            required_input_groups=required_groups,
            input_semantics=input_semantics,
            selector_families=selector_families,
            payload_families=payload_families,
            create_payload_contracts=self._create_payload_contracts(input_semantics),
            openapi_hints=self._command_openapi_hints(command_name, meta.get("operationId"), legal_inputs),
            notes=(),
        )

    def _build_raw_contract(self, manifest: TaskFamilyManifest, operation_id: str) -> BenchmarkRouteContract:
        raw_meta = self.raw_catalog.get(operation_id)
        legal_inputs = [
            str(item.get("name", "")).strip()
            for item in [*raw_meta.get("pathParams", []), *raw_meta.get("queryParams", [])]
            if str(item.get("name", "")).strip()
        ]
        if raw_meta.get("requestBody"):
            legal_inputs.append("body")
        return BenchmarkRouteContract(
            route_kind="raw_operation",
            route_name=operation_id,
            legal_inputs=tuple(legal_inputs),
            required_input_groups=self._required_groups_from_raw_meta(raw_meta, legal_inputs),
            input_semantics={},
            selector_families={},
            payload_families={},
            create_payload_contracts={},
            openapi_hints=self._raw_openapi_hints(raw_meta),
            notes=tuple(
                item
                for item in (
                    str(raw_meta.get("purpose") or "").strip(),
                    str(raw_meta.get("parameterSemantics", {})),
                )
                if item
            ),
        )

    def _family_context(
        self,
        input_semantics: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
        selector_subset: dict[str, dict[str, object]] = {}
        payload_subset: dict[str, dict[str, object]] = {}
        for semantic in input_semantics.values():
            selector_family = semantic.get("selectorFamily")
            if isinstance(selector_family, str) and selector_family in self.selector_families:
                selector_subset[selector_family] = self.selector_families[selector_family]
            payload_family = semantic.get("payloadFamily")
            if isinstance(payload_family, str) and payload_family in self.payload_families:
                payload_subset[payload_family] = self.payload_families[payload_family]
            item_family = semantic.get("itemFamily")
            if isinstance(item_family, str) and item_family in self.payload_families:
                payload_subset[item_family] = self.payload_families[item_family]
        return selector_subset, payload_subset

    def _create_payload_contracts(self, input_semantics: dict[str, dict[str, Any]]) -> dict[str, dict[str, object]]:
        contracts: dict[str, dict[str, object]] = {}
        for input_name_key, semantic in input_semantics.items():
            create_command_name = semantic.get("createCommandName")
            if not isinstance(create_command_name, str) or not create_command_name.strip():
                continue
            if not self.wrapper_catalog.has_command(create_command_name):
                continue
            command_meta = self.wrapper_catalog.get_command(create_command_name)
            command_inputs = tuple(input_name(item) for item in command_meta.get("inputs", []) if input_name(item))
            contracts[input_name_key] = {
                "commandName": create_command_name,
                "legalInputs": command_inputs,
                "inputSemantics": {
                    name: dict(command_meta.get("inputSemantics", {}).get(name) or command_input_semantics(create_command_name, name))
                    for name in command_inputs
                },
                "openapiHints": self._command_openapi_hints(
                    create_command_name,
                    command_meta.get("operationId"),
                    command_inputs,
                ),
            }
        return contracts

    def _command_openapi_hints(
        self,
        command_name: str,
        operation_id: str | None,
        legal_inputs: tuple[str, ...],
    ) -> dict[str, dict[str, object]]:
        if not operation_id:
            return {}
        command_meta = self.wrapper_catalog.get_command(command_name)
        bindings = command_meta.get("inputBindings", {})
        hints: dict[str, dict[str, object]] = {}
        for input_name_key in legal_inputs:
            binding = bindings.get(input_name_key)
            if not isinstance(binding, dict):
                continue
            target_section = binding.get("targetSection")
            target_name = binding.get("targetName")
            if not isinstance(target_name, str) or target_section == "control":
                continue
            info = self.openapi_catalog.input_info(operation_id, target_name, section=target_section)
            if info is None:
                continue
            schema = info.get("schema") if isinstance(info, dict) else {}
            if not isinstance(schema, dict):
                schema = {}
            hints[input_name_key] = {
                "section": target_section,
                "targetName": target_name,
                "required": bool(info.get("required")),
                "type": schema.get("type"),
                "format": schema.get("format"),
                "description": info.get("description", ""),
            }
        return hints

    def _flow_openapi_hints(self, command_names: list[str]) -> dict[str, dict[str, object]]:
        hints: dict[str, dict[str, object]] = {}
        for command_name in command_names:
            if not self.wrapper_catalog.has_command(command_name):
                continue
            command_meta = self.wrapper_catalog.get_command(command_name)
            operation_id = command_meta.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                continue
            hints[command_name] = {
                "operationId": operation_id,
                "summary": self.openapi_catalog.operation_summary(operation_id),
                "description": self.openapi_catalog.operation_description(operation_id),
            }
        return hints

    def _raw_openapi_hints(self, raw_meta: dict[str, Any]) -> dict[str, dict[str, object]]:
        hints: dict[str, dict[str, object]] = {}
        for parameter in [*raw_meta.get("pathParams", []), *raw_meta.get("queryParams", [])]:
            name = str(parameter.get("name", "")).strip()
            if not name:
                continue
            hints[name] = {
                "section": parameter.get("in"),
                "required": bool(parameter.get("required")),
                "type": parameter.get("type"),
                "format": parameter.get("format"),
                "description": parameter.get("description", ""),
                "default": parameter.get("default"),
            }
        return hints

    def _required_groups_from_operation(
        self,
        operation_id: str | None,
        legal_inputs: tuple[str, ...],
    ) -> tuple[tuple[str, ...], ...]:
        if not operation_id:
            return ()
        raw_meta = self.raw_catalog.get(operation_id)
        return self._required_groups_from_raw_meta(raw_meta, list(legal_inputs))

    def _required_groups_from_raw_meta(
        self,
        raw_meta: dict[str, Any],
        legal_inputs: list[str] | tuple[str, ...],
    ) -> tuple[tuple[str, ...], ...]:
        allowed = set(legal_inputs)
        groups: list[tuple[str, ...]] = []
        for parameter in [*raw_meta.get("pathParams", []), *raw_meta.get("queryParams", [])]:
            if not parameter.get("required"):
                continue
            name = str(parameter.get("name", "")).strip()
            if name and name in allowed:
                groups.append((name,))
        return tuple(groups)

    def _parse_required_input_groups(
        self,
        input_spec: str | list[str] | None,
        legal_inputs: tuple[str, ...],
    ) -> tuple[tuple[str, ...], ...]:
        if not input_spec:
            return ()
        lines = [input_spec] if isinstance(input_spec, str) else list(input_spec)
        groups: list[tuple[str, ...]] = []
        for line in lines:
            if not isinstance(line, str):
                continue
            tokens = TOKEN_RE.findall(line)
            if not tokens:
                continue
            resolved_names: list[str] = []
            all_optional = True
            for token in tokens:
                cleaned = token.strip()
                optional = cleaned.endswith("?")
                canonical = cleaned.removesuffix("?").replace("[]", "").strip()
                resolved = match_name(canonical, list(legal_inputs)) or self._lookup_legal_input(canonical, legal_inputs)
                if not resolved:
                    continue
                resolved_names.append(resolved)
                if not optional:
                    all_optional = False
            if all_optional or not resolved_names:
                continue
            groups.append(tuple(dict.fromkeys(resolved_names)))
        return tuple(groups)

    def _lookup_legal_input(self, candidate: str, legal_inputs: tuple[str, ...]) -> str | None:
        target = normalize_key(candidate)
        for legal_input in legal_inputs:
            if normalize_key(legal_input) == target:
                return legal_input
        return None
