from __future__ import annotations

import re
from typing import Any

from app.utils import normalize_key


TOKEN_OWNER_EMPLOYEE_ALIASES = {
    "tokenowner",
    "tokenowneremployee",
    "tokenowneremployeeid",
    "currentuser",
    "currentemployee",
    "authenticateduser",
    "authenticatedemployee",
    "loggedinuser",
    "loggedinemployee",
    "sessionuser",
    "sessionemployee",
    "self",
    "myself",
    "me",
}

EMPLOYEE_ID_FIELDS = {
    "employeeid",
    "employee_id",
    "projectmanagerid",
    "project_manager_id",
    "accountmanagerid",
    "account_manager_id",
    "departmentmanagerid",
    "department_manager_id",
}

EMPLOYEE_IDS_FIELDS = {
    "employeeids",
    "employee_ids",
}

EMPLOYEE_OBJECT_FIELDS = {
    "employee",
    "employee_ref",
    "employeeref",
    "employeeselector",
    "employee_selector",
    "projectmanager",
    "project_manager",
    "projectmanagerref",
    "project_manager_ref",
    "accountmanager",
    "account_manager",
    "accountmanagerref",
    "account_manager_ref",
    "departmentmanager",
    "department_manager",
    "departmentmanagerref",
    "department_manager_ref",
}

STEP_OUTPUT_REFERENCE_RE = re.compile(r"^(?:step|flow|cmd)[A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
STEP_OUTPUT_BINDING_KEY = "$fromStep"
STEP_OUTPUT_BINDING_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])*(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])*)*$"
)
STEP_OUTPUT_PATH_SEGMENT_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\[\d+\])*")


def canonical_token_owner_employee_alias(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = normalize_key(value)
    if normalized in TOKEN_OWNER_EMPLOYEE_ALIASES:
        return "token_owner"
    return None


def is_token_owner_employee_alias(value: Any) -> bool:
    return canonical_token_owner_employee_alias(value) is not None


def normalize_runtime_employee_value(value: Any) -> Any:
    canonical = canonical_token_owner_employee_alias(value)
    return canonical or value


def is_employee_id_field(field_name: str) -> bool:
    normalized = normalize_key(field_name)
    return normalized in {normalize_key(item) for item in EMPLOYEE_ID_FIELDS}


def is_employee_ids_field(field_name: str) -> bool:
    normalized = normalize_key(field_name)
    return normalized in {normalize_key(item) for item in EMPLOYEE_IDS_FIELDS}


def is_employee_object_field(field_name: str) -> bool:
    normalized = normalize_key(field_name)
    return normalized in {normalize_key(item) for item in EMPLOYEE_OBJECT_FIELDS}


def canonical_step_output_reference(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if not STEP_OUTPUT_REFERENCE_RE.fullmatch(candidate):
        return None
    return candidate


def is_step_output_reference(value: Any) -> bool:
    return canonical_step_output_reference(value) is not None


def canonical_step_output_binding(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    if any(key not in {STEP_OUTPUT_BINDING_KEY, "path"} for key in value):
        return None
    step_id = value.get(STEP_OUTPUT_BINDING_KEY)
    path = value.get("path", "")
    if not isinstance(step_id, str) or not step_id.strip():
        return None
    if not isinstance(path, str):
        return None
    normalized_step = step_id.strip()
    normalized_path = path.strip()
    if normalized_path and not STEP_OUTPUT_BINDING_PATH_RE.fullmatch(normalized_path):
        return None
    return {
        "stepId": normalized_step,
        "path": normalized_path,
    }


def is_step_output_binding(value: Any) -> bool:
    return canonical_step_output_binding(value) is not None


def iter_step_output_bindings(value: Any, *, path: str = "") -> list[tuple[str, dict[str, str]]]:
    binding = canonical_step_output_binding(value)
    if binding is not None:
        return [(path or "$", binding)]
    bindings: list[tuple[str, dict[str, str]]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            bindings.extend(iter_step_output_bindings(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            bindings.extend(iter_step_output_bindings(item, path=child_path))
    return bindings


def resolve_step_output_binding(binding: dict[str, str], outputs: dict[str, Any]) -> Any:
    step_id = binding["stepId"]
    if step_id not in outputs:
        raise KeyError(step_id)
    value = outputs[step_id]
    path = binding.get("path", "")
    if not path:
        return value
    current = value
    for raw_segment in path.split("."):
        match = STEP_OUTPUT_PATH_SEGMENT_RE.fullmatch(raw_segment)
        if match is None:
            raise KeyError(path)
        key = match.group(1)
        if not isinstance(current, dict) or key not in current:
            raise KeyError(path)
        current = current[key]
        for index_token in re.findall(r"\[(\d+)\]", raw_segment):
            index = int(index_token)
            if not isinstance(current, list) or index >= len(current):
                raise KeyError(path)
            current = current[index]
    return current
