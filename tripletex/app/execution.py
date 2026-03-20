from __future__ import annotations

from typing import Any

from .client import TripletexClient
from .openapi_registry import TripletexOpenAPIRegistry
from .tasking import TripletexCommand


class CommandExecutionError(RuntimeError):
    pass


class TripletexCommandExecutor:
    def __init__(self, client: TripletexClient, registry: TripletexOpenAPIRegistry):
        self.client = client
        self.registry = registry

    def execute(self, command: TripletexCommand) -> Any:
        self.validate(command)
        return self.execute_prevalidated(command)

    def validate(self, command: TripletexCommand) -> None:
        self._validate(command)

    def execute_prevalidated(self, command: TripletexCommand) -> Any:
        return self.client.request(
            command.method,
            command.path,
            params=_clean_mapping(command.params),
            json_body=command.json_body,
        )

    def _validate(self, command: TripletexCommand) -> None:
        if command.method not in {"GET", "POST", "PUT", "DELETE"}:
            raise CommandExecutionError(f"Unsupported command method: {command.method!r}")
        if not command.path.startswith("/"):
            raise CommandExecutionError(f"Command path must start with '/': {command.path!r}")
        try:
            self.registry.validate_command(command)
        except Exception as exc:
            raise CommandExecutionError(str(exc)) from exc


def _clean_mapping(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None
    return {key: item for key, item in value.items() if item is not None}
