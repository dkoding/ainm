from __future__ import annotations

import re
from typing import Any

from app.llm.contract_utils import input_names, split_required_inputs
from app.raw import load_raw_catalog
from app.wrapper import load_wrapper_catalog


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower().replace("/", " ").replace("-", " ")) if len(token) > 2}


TOKEN_EQUIVALENTS = {
    "attachment": {"attachment", "attachments", "vedlegg", "adjunto", "anhang", "piece"},
    "employee": {"employee", "employees", "ansatt", "empleado", "mitarbeiter", "employe"},
    "invoice": {"invoice", "invoices", "faktura", "fakturaer", "factura", "facturas", "rechnung", "rechnungen"},
    "payment": {"payment", "payments", "betaling", "betale", "pago", "pagar", "zahl", "paid"},
    "supplier": {"supplier", "suppliers", "leverandor", "leverandør", "fornecedor", "proveedor", "lieferant", "fournisseur"},
    "timesheet": {"timesheet", "time", "timer", "horas", "heures", "stunden"},
    "voucher": {"voucher", "vouchers", "bilag", "postering", "ledger", "journal"},
}


class ContextCatalog:
    def __init__(self) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()

    def build_slice(self, prompt: str) -> dict[str, Any]:
        prompt_tokens = self._expanded_prompt_tokens(prompt)
        flows = list(self.wrapper_catalog.flows.values())
        commands = list(self.wrapper_catalog.commands.values())
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
            "apiContract": {
                "contractVersion": "tripletex.api_contract.v1",
                "authority": (
                    "This is the authoritative allow-list. Only flow names in legalFlows and command names in legalCommands are valid. "
                    "Only listed inputs are allowed. Required inputs must be present before selecting that flow or command. "
                    "If a name is not listed exactly here, it is illegal."
                ),
                "legalFlowNames": [item["flowName"] for item in sorted(flows, key=lambda item: item["flowName"])],
                "legalCommandNames": [item["commandName"] for item in sorted(commands, key=lambda item: item["commandName"])],
                "legalFlows": [self._flow_contract_pack(item) for item in sorted(flows, key=lambda item: item["flowName"])],
                "legalCommands": [self._command_contract_pack(item) for item in sorted(commands, key=lambda item: item["commandName"])],
            },
            "rawApiContract": {
                "authority": "Every exact raw operationId listed here is legal, but only exact names are valid.",
                "legalOperationIds": sorted(self.raw_catalog.operations.keys()),
                "technicalFlowFamilies": sorted(
                    {item["technicalFlowFamily"] for item in self.raw_catalog.operations.values() if item.get("technicalFlowFamily")}
                ),
            },
            "policyCatalog": self.wrapper_catalog.policies,
            "flows": [self._flow_pack(item) for item in sorted(flows, key=lambda item: item["flowName"])],
            "commands": [self._command_pack(item) for item in sorted(commands, key=lambda item: item["commandName"])],
            "rawOperations": [self._raw_pack(item) for item in raw_operations[:80]],
        }

    def _rank(self, values: Any, prompt_tokens: set[str], render: Any) -> list[dict[str, Any]]:
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in values:
            haystack_tokens = _tokens(render(item))
            score = len(prompt_tokens & haystack_tokens)
            domain_tokens = _tokens(
                f"{item.get('domain', '')} {item.get('subdomain', '')} {' '.join(item.get('technicalFlowFamilies', []))}"
            )
            score += len(prompt_tokens & domain_tokens) * 2
            if item.get("domain") in prompt_tokens:
                score += 3
            if item.get("subdomain") in prompt_tokens:
                score += 2
            if score:
                scored.append((score, item))
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        return [value for _, value in scored]

    def _expanded_prompt_tokens(self, prompt: str) -> set[str]:
        tokens = _tokens(prompt)
        expanded = set(tokens)
        for canonical, synonyms in TOKEN_EQUIVALENTS.items():
            if tokens & synonyms:
                expanded.add(canonical)
                expanded.update(synonyms)
        return expanded

    def _flow_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "flowName": item["flowName"],
            "inputs": item["inputs"],
            "useWhen": item["useWhen"],
            "steps": item["steps"],
            "commandNames": item["commandNames"],
            "policyKeys": self._flow_policy_keys(item),
        }

    def _command_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        body_fields = self._command_body_fields(item)
        return {
            "commandName": item["commandName"],
            "operationId": item["operationId"],
            "purpose": item["purpose"],
            "wrapperInputs": item["inputs"],
            "bodyFields": body_fields,
            "allInputs": self._command_legal_inputs(item),
            "inputSpec": item.get("inputSpec"),
            "technicalFlowFamily": item["technicalFlowFamily"],
            "safetyClass": item["safetyClass"],
            "conformancePolicyKey": item.get("conformancePolicyKey"),
        }

    def _command_contract_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        body_fields = self._command_body_fields(item)
        legal_inputs = self._command_legal_inputs(item)
        required_inputs, optional_inputs = split_required_inputs(legal_inputs, item.get("inputSpec"))
        return {
            "commandName": item["commandName"],
            "operationId": item["operationId"],
            "purpose": item["purpose"],
            "wrapperInputs": input_names(item["inputs"]),
            "bodyFields": body_fields,
            "requiredInputs": required_inputs,
            "optionalInputs": optional_inputs,
            "allInputs": legal_inputs,
            "inputSpec": item.get("inputSpec"),
            "technicalFlowFamily": item["technicalFlowFamily"],
            "safetyClass": item["safetyClass"],
            "allowsBodyPassthrough": bool(item.get("allowsBodyPassthrough")),
            "conformancePolicyKey": item.get("conformancePolicyKey"),
        }

    def _flow_contract_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        legal_inputs = input_names(item["inputs"])
        required_inputs, optional_inputs = split_required_inputs(legal_inputs, item.get("inputSpec"))
        return {
            "flowName": item["flowName"],
            "useWhen": item["useWhen"],
            "requiredInputs": required_inputs,
            "optionalInputs": optional_inputs,
            "allInputs": legal_inputs,
            "inputSpec": item.get("inputSpec"),
            "commandNames": item["commandNames"],
            "policyKeys": self._flow_policy_keys(item),
        }

    def _command_body_fields(self, item: dict[str, Any]) -> list[str]:
        if not item.get("allowsBodyPassthrough"):
            return []
        raw_meta = self.raw_catalog.get(item["operationId"])
        body_schema = next(iter(raw_meta.get("requestBody", {}).get("content", {}).values()), {})
        return sorted(
            name
            for name, value in body_schema.get("properties", {}).items()
            if not value.get("readOnly")
        )

    def _command_legal_inputs(self, item: dict[str, Any]) -> list[str]:
        legal_inputs = list(input_names(item["inputs"]))
        if item.get("allowsBodyPassthrough"):
            legal_inputs.extend(["body", "payload"])
            legal_inputs.extend(self._command_body_fields(item))
        return sorted(dict.fromkeys(name for name in legal_inputs if name))

    def _raw_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        body_schema = next(iter(item.get("requestBody", {}).get("content", {}).values()), {})
        body_fields = sorted(
            name
            for name, value in body_schema.get("properties", {}).items()
            if not value.get("readOnly")
        )
        required_query = sorted(param["name"] for param in item["queryParams"] if param["required"])
        optional_query = sorted(param["name"] for param in item["queryParams"] if not param["required"])
        required_body = sorted(body_schema.get("required", []))
        return {
            "operationId": item["operationId"],
            "method": item["method"],
            "path": item["path"],
            "purpose": item["purpose"],
            "technicalFlowFamilies": item["technicalFlowFamilies"],
            "pathParams": [param["name"] for param in item["pathParams"]],
            "queryParams": [param["name"] for param in item["queryParams"]],
            "requiredQueryParams": required_query,
            "optionalQueryParams": optional_query,
            "bodyFields": body_fields,
            "requiredBodyFields": required_body,
            "allowedInputs": sorted(
                dict.fromkeys(
                    [*[param["name"] for param in item["pathParams"]], *[param["name"] for param in item["queryParams"]], *body_fields]
                    + (["body"] if item.get("requestBody") else [])
                )
            ),
            "requestBodyKind": item.get("requestBody", {}).get("kind"),
            "conformancePolicyKey": item.get("conformancePolicyKey"),
        }

    def _flow_policy_keys(self, item: dict[str, Any]) -> list[str]:
        policy_keys = {
            self.wrapper_catalog.get_command(command_name).get("conformancePolicyKey")
            for command_name in item.get("commandNames", [])
            if self.wrapper_catalog.has_command(command_name)
        }
        return sorted(policy_key for policy_key in policy_keys if policy_key)
