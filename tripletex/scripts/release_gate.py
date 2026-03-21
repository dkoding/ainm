from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "app" / "generated"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load(name: str) -> dict:
    return json.loads((GENERATED / name).read_text(encoding="utf-8"))


def load_flow_handler_names() -> set[str]:
    text = (ROOT / "app" / "wrapper" / "flows.py").read_text(encoding="utf-8")
    handlers: set[str] = set()
    inside_handlers = False
    for line in text.splitlines():
        if "self._handlers = {" in line:
            inside_handlers = True
            continue
        if inside_handlers and line.strip() == "}":
            break
        if inside_handlers:
            stripped = line.strip()
            if stripped.startswith('"') or stripped.startswith("'"):
                flow_name = stripped.split(":", 1)[0].strip().strip('",\'')
                if flow_name:
                    handlers.add(flow_name)
    return handlers


def main() -> None:
    operation_catalog = load("operation_catalog.json")
    command_catalog = load("command_catalog.json")
    flow_catalog = load("flow_catalog.json")

    assert operation_catalog["operationCount"] == 800, operation_catalog["operationCount"]
    assert command_catalog["commandCount"] == 78, command_catalog["commandCount"]
    assert flow_catalog["flowCount"] == 21, flow_catalog["flowCount"]

    operations = operation_catalog["operations"]
    commands = command_catalog["commands"]
    flows = flow_catalog["flows"]

    missing_families = [name for name, meta in operations.items() if not meta.get("technicalFlowFamily")]
    assert not missing_families, missing_families[:10]

    unknown_command_ops = [name for name, meta in commands.items() if meta["operationId"] not in operations]
    assert not unknown_command_ops, unknown_command_ops[:10]

    unknown_flow_commands = [
        (name, command_name)
        for name, meta in flows.items()
        for command_name in meta["commandNames"]
        if command_name not in commands
    ]
    assert not unknown_flow_commands, unknown_flow_commands[:10]

    unmapped_inputs = {
        name: meta["unmappedInputs"]
        for name, meta in commands.items()
        if meta.get("unmappedInputs")
    }
    assert not unmapped_inputs, list(unmapped_inputs.items())[:10]

    missing_handlers = sorted(set(flows) - load_flow_handler_names())
    assert not missing_handlers, missing_handlers

    print(
        json.dumps(
            {
                "operations": operation_catalog["operationCount"],
                "commands": command_catalog["commandCount"],
                "flows": flow_catalog["flowCount"],
                "technicalFamiliesComplete": True,
                "commandBindingsComplete": True,
                "flowHandlersComplete": True,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
