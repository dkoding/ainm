from __future__ import annotations

from app.benchmark.manifests import TASK_FAMILY_MANIFESTS
from app.benchmark.models import TaskFamilyManifest


class TaskRegistry:
    def __init__(self, manifests: tuple[TaskFamilyManifest, ...] | None = None) -> None:
        self._manifests = manifests or TASK_FAMILY_MANIFESTS
        self._by_id = {item.family_id: item for item in self._manifests}
        if len(self._by_id) != len(self._manifests):
            raise ValueError("Task family manifests must have unique ids.")

    def all(self) -> tuple[TaskFamilyManifest, ...]:
        return self._manifests

    def get(self, family_id: str) -> TaskFamilyManifest | None:
        return self._by_id.get(family_id)

    def list_family_ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)
