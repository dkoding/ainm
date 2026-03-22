from __future__ import annotations

from typing import Protocol


class BenchmarkExecutor(Protocol):
    family_id: str


class ExecutorRegistry:
    def __init__(self, executors: tuple[BenchmarkExecutor, ...] | None = None) -> None:
        self._executors = {executor.family_id: executor for executor in executors or ()}

    def supports(self, family_id: str | None) -> bool:
        if not family_id:
            return False
        return family_id in self._executors

    def list_supported_families(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))
