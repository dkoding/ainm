from __future__ import annotations

import os
from typing import Any


SUPPORTED_PLANNER_LANGUAGES = (
    "English",
    "Norwegian",
    "Nynorsk",
    "German",
    "French",
    "Spanish",
    "Portuguese",
)

SUPPORTED_ATTACHMENT_KINDS = (
    "text",
    "pdf",
    "image",
)


def build_competition_dashboard(
    *,
    coverage_report: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if coverage_report.get("documented_task_category_gaps"):
        reasons.append("Documented task category gaps remain.")
    if not bool(verification.get("compile", {}).get("passed")):
        reasons.append("Static compilation checks failed.")
    if not bool(verification.get("tests", {}).get("passed")):
        reasons.append("Unit tests failed.")

    return {
        "contract_version": coverage_report.get("contract_version"),
        "documented_task_categories": coverage_report.get("documented_task_category_coverage", {}),
        "coded_workflow_status": {
            "method_count": coverage_report.get("method_count", 0),
            "coded_method_count": coverage_report.get("coded_method_count", 0),
            "wrapper_only_method_count": coverage_report.get("wrapper_only_method_count", 0),
            "unsupported_method_count": coverage_report.get("unsupported_method_count", 0),
        },
        "test_status": verification.get("tests", {}),
        "compile_status": verification.get("compile", {}),
        "language_coverage": {language: True for language in SUPPORTED_PLANNER_LANGUAGES},
        "attachment_coverage": {kind: True for kind in SUPPORTED_ATTACHMENT_KINDS},
        "api_call_budget": {
            "max_api_calls_per_solve": int(os.getenv("TRIPLETEX_MAX_API_CALLS", os.getenv("TRIPLETEX_MAX_STEPS", "12"))),
            "max_planner_steps": int(
                os.getenv("TRIPLETEX_MAX_PLANNER_STEPS", os.getenv("TRIPLETEX_MAX_STEPS", "12"))
            ),
            "request_timeout_seconds": float(os.getenv("TRIPLETEX_REQUEST_TIMEOUT", "30")),
        },
        "release_gate": {
            "ready": not reasons,
            "reasons": reasons,
        },
    }
