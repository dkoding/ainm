from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExecutionContext:
    base_url: str
    session_token: str
    request_id: str
    current_date: str
    timezone: str


@dataclass(slots=True)
class StepTrace:
    step_id: str
    step_type: str
    name: str
    operation_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: Any = None


@dataclass(slots=True)
class ExecutionResult:
    traces: list[StepTrace] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)

    def add_trace(self, trace: StepTrace) -> None:
        self.traces.append(trace)
        self.outputs[trace.step_id] = trace.outputs
