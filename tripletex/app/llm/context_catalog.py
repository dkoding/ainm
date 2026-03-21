from __future__ import annotations

from typing import Any

from app.raw import load_raw_catalog
from app.wrapper import load_wrapper_catalog


def _tokens(text: str) -> set[str]:
    return {token for token in text.lower().replace("/", " ").replace("_", " ").split() if len(token) > 2}


class ContextCatalog:
    def __init__(self) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()

    def build_slice(self, prompt: str) -> dict[str, Any]:
        prompt_tokens = _tokens(prompt)
        flows = [self._flow_pack(item) for item in self.wrapper_catalog.flows.values()]
        commands = [self._command_pack(item) for item in self.wrapper_catalog.commands.values()]
        raw_operations = self._rank(
            self.raw_catalog.operations.values(),
            prompt_tokens,
            lambda item: f"{item['operationId']} {item['purpose']} {' '.join(item['semanticAliases'])}",
        )
        return {
            "routingRules": {
                "priority": [
                    "business_flow",
                    "friendly_alias",
                    "raw_operation",
                ],
                "ruleText": "Choose a business flow first when one fits, then a friendly command, then exact raw operationId fallback.",
            },
            "flows": flows,
            "commands": commands,
            "rawOperations": [self._raw_pack(item) for item in raw_operations[:40]],
        }

    def _rank(self, values: Any, prompt_tokens: set[str], render: Any) -> list[dict[str, Any]]:
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in values:
            haystack_tokens = _tokens(render(item))
            score = len(prompt_tokens & haystack_tokens)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        return [value for _, value in scored]

    def _flow_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "flowName": item["flowName"],
            "inputs": item["inputs"],
            "useWhen": item["useWhen"],
            "steps": item["steps"],
            "commandNames": item["commandNames"],
        }

    def _command_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "commandName": item["commandName"],
            "operationId": item["operationId"],
            "purpose": item["purpose"],
            "inputs": item["inputs"],
            "technicalFlowFamily": item["technicalFlowFamily"],
            "safetyClass": item["safetyClass"],
        }

    def _raw_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "operationId": item["operationId"],
            "method": item["method"],
            "path": item["path"],
            "purpose": item["purpose"],
            "technicalFlowFamilies": item["technicalFlowFamilies"],
            "pathParams": [param["name"] for param in item["pathParams"]],
            "queryParams": [param["name"] for param in item["queryParams"]],
        }
