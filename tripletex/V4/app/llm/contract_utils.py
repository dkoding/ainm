from __future__ import annotations

import re
from typing import Any


def input_name(input_item: Any) -> str:
    if isinstance(input_item, dict):
        return str(input_item.get("name", ""))
    return str(input_item)


def input_names(inputs: list[Any]) -> list[str]:
    return [input_name(item) for item in inputs]


def _input_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _extract_contract_tokens(spec: str | list[str] | None) -> list[tuple[str, bool]]:
    values: list[str] = []
    if isinstance(spec, str):
        values.extend(re.findall(r"`([^`]+)`", spec))
    elif isinstance(spec, list):
        for item in spec:
            values.extend(re.findall(r"`([^`]+)`", item))
    tokens: list[tuple[str, bool]] = []
    for value in values:
        cleaned = value.strip()
        optional = cleaned.endswith("?")
        cleaned = cleaned.removesuffix("?").replace("[]", "").strip()
        if cleaned:
            tokens.append((cleaned, optional))
    return tokens


def split_required_inputs(input_names_list: list[str], spec: str | list[str] | None) -> tuple[list[str], list[str]]:
    lookup = {_input_key(name): name for name in input_names_list}
    required: list[str] = []
    optional: list[str] = []
    seen: set[str] = set()
    for raw_name, is_optional in _extract_contract_tokens(spec):
        resolved_name = lookup.get(_input_key(raw_name))
        if not resolved_name or resolved_name in seen:
            continue
        if is_optional:
            optional.append(resolved_name)
        else:
            required.append(resolved_name)
        seen.add(resolved_name)
    for name in input_names_list:
        if name not in seen:
            optional.append(name)
    return required, optional
