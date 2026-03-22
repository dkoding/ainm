from __future__ import annotations

from functools import lru_cache
from typing import Any


def _object_schema(*, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object"}
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return schema


def _array_schema(*, items: dict[str, Any] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array"}
    if items:
        schema["items"] = items
    return schema


def _bridge_root_properties(*, detailed_containers: bool) -> dict[str, Any]:
    execution_plan_schema = (
        _object_schema(
            properties={
                "selectedFlows": _array_schema(),
                "selectedCommands": _array_schema(),
                "fallbackRawCommands": _array_schema(),
                "stepOrder": _array_schema(),
            },
            required=["selectedFlows", "selectedCommands", "fallbackRawCommands", "stepOrder"],
        )
        if detailed_containers
        else _object_schema()
    )
    validation_properties: dict[str, Any] | None = {"isExecutable": {"type": "boolean"}} if detailed_containers else None
    validation_required = ["isExecutable"] if detailed_containers else None
    return {
        "contractVersion": {"type": "string"},
        "requestContext": _object_schema(),
        "language": _object_schema(),
        "understanding": _object_schema(),
        "sources": _object_schema(),
        "richData": _object_schema(),
        "flatBridge": _object_schema(),
        "executionPlan": execution_plan_schema,
        "validation": _object_schema(properties=validation_properties, required=validation_required),
        "completion": _object_schema(),
    }


@lru_cache(maxsize=1)
def bridge_response_json_schema() -> dict[str, Any]:
    return _object_schema(
        properties=_bridge_root_properties(detailed_containers=True),
        required=[
            "contractVersion",
            "requestContext",
            "language",
            "understanding",
            "sources",
            "richData",
            "flatBridge",
            "executionPlan",
            "validation",
            "completion",
        ],
    )


@lru_cache(maxsize=1)
def bridge_fallback_response_json_schema() -> dict[str, Any]:
    return _object_schema(
        properties=_bridge_root_properties(detailed_containers=False),
        required=[
            "contractVersion",
            "requestContext",
            "language",
            "understanding",
            "sources",
            "richData",
            "flatBridge",
            "executionPlan",
            "validation",
            "completion",
        ],
    )


@lru_cache(maxsize=1)
def intent_response_json_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "contractVersion": {"type": "string"},
            "intentSummary": {"type": "string"},
            "taskFamilies": _array_schema(),
            "targetResources": _array_schema(),
            "operations": _array_schema(),
            "routeHints": _object_schema(),
            "needsMutation": {"type": "boolean"},
            "needsResolution": {"type": "boolean"},
            "attachmentRelevant": {"type": "boolean"},
            "confidence": {"type": "number"},
            "ambiguities": _array_schema(),
            "missingData": _array_schema(),
        },
        required=["contractVersion", "routeHints"],
    )


@lru_cache(maxsize=1)
def intent_fallback_response_json_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "contractVersion": {"type": "string"},
            "intentSummary": {"type": "string"},
            "routeHints": _object_schema(),
            "needsMutation": {"type": "boolean"},
            "needsResolution": {"type": "boolean"},
            "attachmentRelevant": {"type": "boolean"},
            "taskFamilies": _array_schema(),
            "targetResources": _array_schema(),
            "operations": _array_schema(),
            "ambiguities": _array_schema(),
            "missingData": _array_schema(),
        },
        required=["contractVersion", "routeHints"],
    )


@lru_cache(maxsize=1)
def attachment_facts_response_json_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "attachments": _array_schema(items=_object_schema()),
        },
        required=["attachments"],
    )


@lru_cache(maxsize=1)
def attachment_facts_fallback_response_json_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "attachments": _array_schema(),
        },
        required=["attachments"],
    )
