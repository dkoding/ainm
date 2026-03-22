from __future__ import annotations

from typing import Any

from app.contracts.execution import ExecutionContext
from app.raw import RawCatalog, RawExecutor, load_raw_catalog
from app.raw.errors import RawExecutionError
from app.utils import camel_case
from app.wrapper.catalog import WrapperCatalog, load_wrapper_catalog
from app.wrapper.helpers import (
    CONTROL_FIELDS,
    choose_date_window_pair,
    coerce_int_like,
    flatten_special_inputs,
    id_ref,
)

class CommandExecutor:
    def __init__(
        self,
        raw_executor: RawExecutor | None = None,
        wrapper_catalog: WrapperCatalog | None = None,
        raw_catalog: RawCatalog | None = None,
    ) -> None:
        self.raw_catalog = raw_catalog or load_raw_catalog()
        self.wrapper_catalog = wrapper_catalog or load_wrapper_catalog()
        self.raw_executor = raw_executor or RawExecutor(catalog=self.raw_catalog)

    def execute(self, command_name: str, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        command_meta = self.wrapper_catalog.get_command(command_name)
        raw_meta = self.raw_catalog.get(command_meta["operationId"])
        raw_arguments = self._prepare_arguments(command_meta, raw_meta, inputs, context)
        return self.raw_executor.execute(command_meta["operationId"], raw_arguments, context)

    def _prepare_arguments(
        self,
        command_meta: dict[str, Any],
        raw_meta: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        flattened = flatten_special_inputs(inputs)
        query_names = [item["name"] for item in raw_meta["queryParams"]]
        body_meta = raw_meta["requestBody"]
        body_schema = next(iter(body_meta.get("content", {}).values()), {})
        body_properties = body_schema.get("properties", {})
        body_type = body_schema.get("type")
        bindings = command_meta.get("inputBindings", {})

        date_window = flattened.pop("date_window", None)
        if isinstance(date_window, dict):
            pair = choose_date_window_pair(query_names)
            if pair:
                start_key, end_key = pair
                if date_window.get("from") is not None:
                    flattened[start_key] = date_window.get("from")
                if date_window.get("to") is not None:
                    flattened[end_key] = date_window.get("to")

        raw_arguments: dict[str, Any] = {}
        body: Any = [] if body_type == "array" else {}
        explicit_body = flattened.pop("body", None)
        if explicit_body is not None:
            if body_meta.get("kind") == "multipart" and not isinstance(explicit_body, dict):
                raise RawExecutionError(message="Explicit multipart command body must be a dict.")
            if body_meta.get("kind") != "multipart" and not isinstance(explicit_body, (dict, list)):
                raise RawExecutionError(message="Explicit command body must be a dict or list.")
            body = explicit_body

        for key, value in flattened.items():
            if value is None:
                continue
            binding = bindings.get(key)
            if binding is None:
                if key in CONTROL_FIELDS:
                    continue
                if command_meta.get("allowsBodyPassthrough"):
                    if key in {"body", "payload"} and isinstance(value, dict):
                        body.update(value)
                        continue
                    passthrough_target = self._resolve_body_passthrough_target(key, body_properties)
                    if passthrough_target is not None:
                        converted = self._convert_value(
                            key,
                            value,
                            passthrough_target,
                            "body",
                            "ref_object" if key.endswith("_ref") else "plain",
                            body_properties.get(passthrough_target),
                            context,
                        )
                        body[passthrough_target] = converted
                        continue
                raise RawExecutionError(message=f"Unsupported input for command {command_meta['commandName']}: {key}")
            section = binding["targetSection"]
            raw_name = binding["targetName"]
            if section == "control":
                raw_arguments[raw_name] = value
                continue
            converted = self._convert_value(
                key,
                value,
                raw_name,
                section,
                binding.get("valueStrategy"),
                body_properties.get(raw_name),
                context,
            )
            if section in {"path", "query"}:
                raw_arguments[raw_name] = converted
            else:
                body = self._merge_body_value(body, converted, binding.get("valueStrategy"), raw_name, body_type, key)

        if body_meta:
            raw_arguments["body"] = body
        return raw_arguments

    def _merge_body_value(
        self,
        body: Any,
        converted: Any,
        value_strategy: str | None,
        raw_name: str,
        body_type: str | None,
        source_key: str,
    ) -> Any:
        if value_strategy == "body_merge":
            if body_type == "array":
                if not isinstance(converted, list):
                    raise RawExecutionError(message=f"{source_key} must be a list body payload.")
                return converted
            if not isinstance(converted, dict):
                raise RawExecutionError(message=f"{source_key} must be a dict body fragment.")
            if not isinstance(body, dict):
                raise RawExecutionError(message=f"{source_key} cannot merge into a non-dict body.")
            body.update(converted)
            return body
        if body_type == "array":
            raise RawExecutionError(message=f"{source_key} must be supplied through body/payload for array request bodies.")
        if not isinstance(body, dict):
            raise RawExecutionError(message=f"{source_key} cannot write into a non-dict body.")
        body[raw_name] = converted
        return body

    def _resolve_body_passthrough_target(self, key: str, body_properties: dict[str, Any]) -> str | None:
        candidates = [key, camel_case(key)]
        if key.endswith("_ref"):
            stem = key[:-4]
            candidates.extend([stem, camel_case(stem)])
        for candidate in candidates:
            if candidate in body_properties:
                return candidate
        return None

    def _convert_value(
        self,
        source_key: str,
        value: Any,
        target_key: str,
        target_section: str,
        value_strategy: str | None,
        body_property_meta: dict[str, Any] | None,
        context: ExecutionContext,
    ) -> Any:
        if value_strategy == "body_merge":
            return value
        if value_strategy == "attachment_file":
            if not isinstance(value, str):
                raise RawExecutionError(message=f"{source_key} must be an attachment id string.")
            attachment = context.attachments_by_id.get(value)
            if attachment is None:
                raise RawExecutionError(message=f"Unknown attachment id {value} for {source_key}.")
            return attachment
        if value_strategy == "ref_id":
            if isinstance(value, dict):
                if "id" not in value:
                    raise RawExecutionError(message=f"{source_key} must contain an id field.")
                return coerce_int_like(value["id"], field_name=source_key)
            return coerce_int_like(value, field_name=source_key)
        if value_strategy == "ref_object":
            if isinstance(value, dict) and "id" in value:
                return {"id": coerce_int_like(value["id"], field_name=source_key)}
            return id_ref(value)
        if value_strategy == "ref_list":
            if isinstance(value, list):
                return [id_ref(item) for item in value]
            return [id_ref(value)]
        if source_key.endswith("_ref"):
            if target_section in {"path", "query"} or target_key.endswith("Id") or target_key.endswith("Ids"):
                if isinstance(value, dict):
                    if "id" not in value:
                        raise RawExecutionError(message=f"{source_key} must contain an id field.")
                    return coerce_int_like(value["id"], field_name=source_key)
                return coerce_int_like(value, field_name=source_key)
            if isinstance(value, dict) and "id" in value:
                return {"id": coerce_int_like(value["id"], field_name=source_key)}
            return id_ref(value)
        if body_property_meta and body_property_meta.get("type") == "object" and isinstance(value, (int, str)):
            return {"id": coerce_int_like(value, field_name=source_key)}
        return value
