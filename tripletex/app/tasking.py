from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AttachmentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    media_kind: Literal["text", "pdf", "image", "other"]
    path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    text_excerpt: str = ""
    extraction_notes: list[str] = Field(default_factory=list)


class TaskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1)
    task_family: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    target_resource: str | None = None
    method_name: str = "UnknownMethod"
    method_arguments: dict[str, Any] = Field(default_factory=dict)
    missing_required_arguments: list[str] = Field(default_factory=list)
    detected_language: str = "unknown"
    search_hints: dict[str, Any] = Field(default_factory=dict)
    payload_fields: dict[str, Any] = Field(default_factory=dict)
    attachment_required: bool = False
    ambiguity_notes: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "medium"
    completion_signals: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class TripletexCommand:
    method: str
    path: str
    reason: str
    params: dict[str, Any] | None = None
    json_body: Any | None = None


class PlannedAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str = Field(min_length=1)
    params: dict[str, Any] | None = None
    json_body: Any | None = Field(default=None, alias="json")

    def to_command(self, *, reason: str) -> TripletexCommand:
        return TripletexCommand(
            method=self.method,
            path=self.path,
            reason=reason,
            params=self.params,
            json_body=self.json_body,
        )


class MethodCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class PlannerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["action", "method", "finish"]
    reason: str = Field(min_length=1)
    action: PlannedAction | None = None
    method_call: MethodCall | None = None

    def to_command(self) -> TripletexCommand:
        if self.kind != "action":
            raise ValueError("Only action decisions can be converted into commands.")
        if self.action is None:
            raise ValueError("Planner returned kind=action without an action payload.")
        return self.action.to_command(reason=self.reason)

    def to_method_call(self) -> MethodCall:
        if self.kind != "method":
            raise ValueError("Only method decisions can be converted into method calls.")
        if self.method_call is None:
            raise ValueError("Planner returned kind=method without a method_call payload.")
        return self.method_call
