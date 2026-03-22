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
