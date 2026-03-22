from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.utils import APP_ROOT, load_json


COMMAND_CATALOG_PATH = APP_ROOT / "generated" / "command_catalog.json"
FLOW_CATALOG_PATH = APP_ROOT / "generated" / "flow_catalog.json"
POLICY_CATALOG_PATH = APP_ROOT / "generated" / "conformance_policies.json"


class WrapperCatalog:
    def __init__(self, commands: dict[str, Any], flows: dict[str, Any], policies: dict[str, Any]) -> None:
        self.commands = commands["commands"]
        self.flows = flows["flows"]
        self.policies = policies["policies"]
        self.command_count = commands["commandCount"]
        self.flow_count = flows["flowCount"]

    def get_command(self, name: str) -> dict[str, Any]:
        try:
            return self.commands[name]
        except KeyError as exc:
            raise KeyError(f"Unknown wrapper command: {name}") from exc

    def has_command(self, name: str) -> bool:
        return name in self.commands

    def get_flow(self, name: str) -> dict[str, Any]:
        try:
            return self.flows[name]
        except KeyError as exc:
            raise KeyError(f"Unknown wrapper flow: {name}") from exc

    def has_flow(self, name: str) -> bool:
        return name in self.flows

    def list_commands(self) -> list[dict[str, Any]]:
        return [self.commands[name] for name in sorted(self.commands)]

    def list_flows(self) -> list[dict[str, Any]]:
        return [self.flows[name] for name in sorted(self.flows)]


@lru_cache(maxsize=1)
def load_wrapper_catalog(
    commands_path: Path = COMMAND_CATALOG_PATH,
    flows_path: Path = FLOW_CATALOG_PATH,
    policies_path: Path = POLICY_CATALOG_PATH,
) -> WrapperCatalog:
    return WrapperCatalog(load_json(commands_path), load_json(flows_path), load_json(policies_path))
