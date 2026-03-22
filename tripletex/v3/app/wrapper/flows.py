from __future__ import annotations

from typing import Any

from app.contracts.execution import ExecutionContext
from app.llm.contract_utils import split_required_inputs
from app.raw.errors import RawExecutionError
from app.wrapper.catalog import WrapperCatalog, load_wrapper_catalog
from app.wrapper.commands import CommandExecutor
from app.wrapper.helpers import (
    coerce_int_like,
    default_date_window,
    ensure_single_result,
    extract_values,
    id_ref,
    is_int_like,
    merge_maps,
    to_selector_dict,
)


SEARCH_COMMANDS = {
    "currency": "currency.search",
    "customer": "customer.search",
    "department": "department.search",
    "employee": "employee.search",
    "invoice": "invoice.search",
    "invoice_payment_type": "invoice_payment_type.search",
    "ledger_account": "ledger.account.search",
    "product": "product.search",
    "product_unit": "product_unit.search",
    "project": "project.search",
    "supplier": "supplier.search",
    "supplier_invoice": "supplier_invoice.search",
    "travel_cost_category": "travel_cost_category.search",
    "travel_payment_type": "travel_payment_type.search",
    "travel_rate": "travel_rate.search",
    "travel_rate_category": "travel_rate_category.search",
    "travel_zone": "travel_zone.search",
    "travel_expense": "travel_expense.search",
    "vat_type": "vat_type.search",
    "voucher": "voucher.search",
    "voucher_type": "ledger.voucher_type.search",
}

GET_COMMANDS = {
    "customer": "customer.get",
    "department": "department.get",
    "employee": "employee.get",
    "invoice": "invoice.get",
    "product": "product.get",
    "project": "project.get",
    "supplier": "supplier.get",
    "supplier_invoice": "supplier_invoice.get",
    "travel_expense": "travel_expense.get",
    "voucher": "voucher.get",
}


class FlowExecutor:
    def __init__(
        self,
        command_executor: CommandExecutor | None = None,
        wrapper_catalog: WrapperCatalog | None = None,
    ) -> None:
        self.wrapper_catalog = wrapper_catalog or load_wrapper_catalog()
        self.commands = command_executor or CommandExecutor(wrapper_catalog=self.wrapper_catalog)
        self._handlers = {
            "bootstrap.inspect_context": self._bootstrap_inspect_context,
            "employee.create_basic": self._employee_create_basic,
            "employee.create_with_access": self._employee_create_with_access,
            "employee.update_contact": self._employee_update_contact,
            "customer.create_or_update": self._customer_create_or_update,
            "product.create_or_update": self._product_create_or_update,
            "invoice.order_first": self._invoice_order_first,
            "invoice.direct": self._invoice_direct,
            "invoice.register_payment": self._invoice_register_payment,
            "invoice.credit_note": self._invoice_credit_note,
            "travel_expense.create_basic": self._travel_expense_create_basic,
            "travel_expense.create_with_rows": self._travel_expense_create_with_rows,
            "travel_expense.delete": self._travel_expense_delete,
            "travel_expense.finalize_to_accounting": self._travel_expense_finalize_to_accounting,
            "project.create_for_customer": self._project_create_for_customer,
            "supplier.create_or_update": self._supplier_create_or_update,
            "department.create_with_manager": self._department_create_with_manager,
            "department.enable_accounting_module": self._department_enable_accounting_module,
            "voucher.manual_adjustment": self._voucher_manual_adjustment,
            "voucher.reverse_or_correct": self._voucher_reverse_or_correct,
            "ledger.verify_effect": self._ledger_verify_effect,
            "supplier_invoice.register_payment": self._supplier_invoice_register_payment,
            "supplier_invoice.import_from_attachment": self._supplier_invoice_import_from_attachment,
        }

    def execute(self, flow_name: str, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        try:
            handler = self._handlers[flow_name]
        except KeyError as exc:
            raise RawExecutionError(message=f"Unknown wrapper flow: {flow_name}") from exc
        return handler(inputs, context)

    def _search(
        self,
        family: str,
        selector: Any,
        context: ExecutionContext,
        *,
        search_date_window: dict[str, Any] | None = None,
    ) -> Any:
        search_inputs, _, has_searchable_criteria = self._prepare_search_inputs(
            family,
            selector,
            context,
            search_date_window=search_date_window,
        )
        if not has_searchable_criteria:
            raise RawExecutionError(message=f"{SEARCH_COMMANDS[family]} requires at least one searchable selector field.")
        return self.commands.execute(
            SEARCH_COMMANDS[family],
            search_inputs,
            context,
        )

    def _resolve_record(
        self,
        family: str,
        selector: Any,
        context: ExecutionContext,
        *,
        search_date_window: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(selector, dict) and "id" in selector and is_int_like(selector["id"]) and family in GET_COMMANDS:
            return self._get(family, coerce_int_like(selector["id"], field_name=f"{family}.id"), context)
        return ensure_single_result(
            self._search(family, selector, context, search_date_window=search_date_window),
            family=family,
            selector=selector,
        )

    def _resolve_id(
        self,
        family: str,
        selector: Any,
        context: ExecutionContext,
        *,
        search_date_window: dict[str, Any] | None = None,
    ) -> int:
        if isinstance(selector, int):
            return selector
        if isinstance(selector, dict) and "id" in selector and is_int_like(selector["id"]):
            return coerce_int_like(selector["id"], field_name=f"{family}.id")
        record = self._resolve_record(family, selector, context, search_date_window=search_date_window)
        if "id" not in record:
            raise RawExecutionError(message=f"Resolved {family} record did not include an id.")
        return record["id"]

    def _get(self, family: str, object_id: int, context: ExecutionContext) -> dict[str, Any]:
        command = GET_COMMANDS.get(family)
        if not command:
            return {"id": object_id}
        payload = self.commands.execute(command, {"id": object_id}, context)
        values = extract_values(payload)
        if not values:
            raise RawExecutionError(message=f"{family} id {object_id} did not exist.")
        if not isinstance(values[0], dict):
            raise RawExecutionError(message=f"Unexpected {family} payload for id {object_id}.")
        return values[0]

    def _ensure_customer_id(self, customer: Any, context: ExecutionContext) -> int:
        try:
            return self._resolve_id("customer", customer, context)
        except RawExecutionError:
            if not isinstance(customer, dict):
                raise
            payload = self.commands.execute("customer.create", customer, context)
            return self._extract_id(payload, "customer.create")

    def _ensure_supplier_id(self, supplier: Any, context: ExecutionContext) -> int:
        try:
            return self._resolve_id("supplier", supplier, context)
        except RawExecutionError:
            if not isinstance(supplier, dict):
                raise
            created = self.commands.execute("supplier.create", dict(supplier), context)
            return self._extract_id(created, "supplier.create")

    def _extract_id(self, payload: Any, source: str) -> int:
        values = extract_values(payload)
        if not values or not isinstance(values[0], dict) or "id" not in values[0]:
            raise RawExecutionError(message=f"{source} did not return a created object with id.")
        return values[0]["id"]

    def _build_line_item(self, item: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        payload = dict(item)
        if "product_ref" in payload and payload["product_ref"] is not None:
            payload["product_ref"] = id_ref(self._resolve_id("product", payload["product_ref"], context))
        if "vat_type_ref" in payload and payload["vat_type_ref"] is not None:
            payload["vat_type_ref"] = id_ref(self._resolve_id("vat_type", payload["vat_type_ref"], context))
        if "currency_ref" in payload and payload["currency_ref"] is not None:
            payload["currency_ref"] = id_ref(self._resolve_id("currency", payload["currency_ref"], context))
        return payload

    def _build_posting_line(self, line: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        payload = dict(line)
        reference_map = {
            "account_ref": "ledger_account",
            "vat_type_ref": "vat_type",
            "currency_ref": "currency",
            "customer_ref": "customer",
            "supplier_ref": "supplier",
            "employee_ref": "employee",
            "project_ref": "project",
            "department_ref": "department",
        }
        for key, family in reference_map.items():
            if payload.get(key) is not None:
                payload[key] = id_ref(self._resolve_id(family, payload[key], context))
        return payload

    def _bootstrap_inspect_context(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        result = {
            "identity": self.commands.execute(
                "session.who_am_i",
                {"fields": inputs.get("fields_for_identity")},
                context,
            )
        }
        if inputs.get("include_sales_modules"):
            result["salesModules"] = self.commands.execute("company.sales_modules.list", {}, context)
        return result

    def _prepare_search_inputs(
        self,
        family: str,
        selector: Any,
        context: ExecutionContext,
        *,
        search_date_window: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[str], bool]:
        payload = to_selector_dict(family, selector)
        command_name = SEARCH_COMMANDS[family]
        command_meta = self.wrapper_catalog.get_command(command_name)
        legal_inputs = {name for name in command_meta.get("inputs", []) if name}
        required_inputs, _ = split_required_inputs(command_meta.get("inputs", []), command_meta.get("inputSpec"))
        explicit_window = (
            search_date_window
            if isinstance(search_date_window, dict)
            else payload.get("date_window")
            if isinstance(payload.get("date_window"), dict)
            else None
        )
        projected: dict[str, Any] = {}
        dropped_fields: list[str] = []
        for key, value in payload.items():
            if value is None:
                continue
            if key == "date_window":
                projected[key] = value
                continue
            if key in legal_inputs:
                projected[key] = value
                continue
            dropped_fields.append(key)
        has_searchable_criteria = any(key != "date_window" for key in projected) or explicit_window is not None
        pair = self._required_search_window_pair(required_inputs)
        if not pair:
            projected.pop("date_window", None)
            return projected, dropped_fields, has_searchable_criteria
        start_key, end_key = pair
        if projected.get(start_key) is None or projected.get(end_key) is None:
            window = (
                search_date_window
                or projected.pop("date_window", None)
                or default_date_window(context.current_date)
            )
            if not isinstance(window, dict):
                raise RawExecutionError(message=f"{command_name} requires a date window.")
            projected.setdefault(start_key, window.get("from"))
            projected.setdefault(end_key, window.get("to"))
        projected.pop("date_window", None)
        return projected, dropped_fields, has_searchable_criteria

    def _required_search_window_pair(self, required_inputs: list[str]) -> tuple[str, str] | None:
        pairs = [
            ("invoice_date_from", "invoice_date_to"),
            ("date_from", "date_to"),
        ]
        for start_key, end_key in pairs:
            if start_key in required_inputs and end_key in required_inputs:
                return start_key, end_key
        return None

    def _resolve_attachment(self, attachment_id: Any, context: ExecutionContext) -> dict[str, Any]:
        if not isinstance(attachment_id, str) or not attachment_id:
            raise RawExecutionError(message="attachment_id must reference one of the request attachments.")
        attachment = context.attachments_by_id.get(attachment_id)
        if attachment is None:
            raise RawExecutionError(message=f"Unknown attachment_id {attachment_id}.")
        return attachment

    def _employee_create_basic(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        if inputs.get("duplicate_check") and inputs.get("email"):
            existing = extract_values(self.commands.execute("employee.search", {"email": inputs["email"]}, context))
            if existing:
                return {"value": existing[0]}
        payload = dict(inputs)
        payload.pop("duplicate_check", None)
        if payload.get("department") is not None:
            payload["department_ref"] = id_ref(self._resolve_id("department", payload.pop("department"), context))
        return self.commands.execute("employee.create", payload, context)

    def _employee_create_with_access(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        created = self._employee_create_basic(inputs, context)
        employee_id = self._extract_id(created, "employee.create")
        if inputs.get("entitlement_template"):
            self.commands.execute(
                "employee.entitlements.grant_template",
                {"employee_id": employee_id, "template": inputs["entitlement_template"]},
                context,
            )
        if inputs.get("entitlement_template"):
            self.commands.execute("employee.entitlements.search", {"employee_id": employee_id}, context)
        return created

    def _employee_update_contact(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        selector = inputs.get("employee_selector")
        if not selector:
            raise RawExecutionError(message="employee.update_contact requires employee_selector.")
        employee = self._resolve_record("employee", selector, context)
        current = self._get("employee", employee["id"], context)
        patch = dict(inputs.get("patch", {}))
        patch["id"] = current["id"]
        if current.get("version") is not None:
            patch["version"] = current["version"]
        return self.commands.execute("employee.update", patch, context)

    def _customer_create_or_update(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        payload = dict(inputs)
        selector = payload.pop("customer_selector", None)
        patch_mode = payload.pop("patch_mode", "auto")
        if payload.get("department") is not None:
            payload["department_ref"] = id_ref(self._resolve_id("department", payload.pop("department"), context))
        if payload.get("account_manager") is not None:
            payload["account_manager_ref"] = id_ref(self._resolve_id("employee", payload.pop("account_manager"), context))
        lookup = selector or {key: payload[key] for key in ("name", "organization_number", "email", "invoice_email") if payload.get(key)}
        if lookup and patch_mode != "create":
            matches = self._search_matches_for_upsert("customer", lookup, context)
            if matches is not None:
                if len(matches) == 1:
                    current = self._get("customer", matches[0]["id"], context)
                    update_payload = merge_maps(payload, {"id": current["id"], "version": current.get("version")})
                    return self.commands.execute("customer.update", update_payload, context)
                if len(matches) > 1:
                    raise RawExecutionError(message="customer.create_or_update matched multiple customers.")
        return self.commands.execute("customer.create", payload, context)

    def _product_create_or_update(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        payload = dict(inputs)
        selector = payload.pop("product_selector", None)
        if payload.get("vat_type") is not None:
            payload["vat_type_ref"] = id_ref(self._resolve_id("vat_type", payload.pop("vat_type"), context))
        if payload.get("product_unit") is not None:
            payload["product_unit_ref"] = id_ref(self._resolve_id("product_unit", payload.pop("product_unit"), context))
        if payload.get("account") is not None:
            payload["account_ref"] = id_ref(self._resolve_id("ledger_account", payload.pop("account"), context))
        if payload.get("currency") is not None:
            payload["currency_ref"] = id_ref(self._resolve_id("currency", payload.pop("currency"), context))
        lookup = selector or {key: payload[key] for key in ("name", "number") if payload.get(key)}
        if lookup:
            matches = self._search_matches_for_upsert("product", lookup, context)
            if matches is not None:
                if len(matches) == 1:
                    current = self._get("product", matches[0]["id"], context)
                    update_payload = merge_maps(payload, {"id": current["id"], "version": current.get("version")})
                    return self.commands.execute("product.update", update_payload, context)
                if len(matches) > 1:
                    raise RawExecutionError(message="product.create_or_update matched multiple products.")
        return self.commands.execute("product.create", payload, context)

    def _invoice_order_first(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        customer_id = self._ensure_customer_id(inputs.get("customer"), context)
        payload = {
            "customer_ref": id_ref(customer_id),
            "order_date": inputs.get("order_date"),
            "invoice_comment": inputs.get("invoice_comment"),
            "order_lines": [self._build_line_item(item, context) for item in inputs.get("line_items", [])],
        }
        if inputs.get("project") is not None:
            payload["project_ref"] = id_ref(self._resolve_id("project", inputs["project"], context))
        if inputs.get("department") is not None:
            payload["department_ref"] = id_ref(self._resolve_id("department", inputs["department"], context))
        if inputs.get("due_term") is not None:
            payload["invoices_due_in"] = inputs["due_term"]
        order = self.commands.execute("order.create", payload, context)
        order_id = self._extract_id(order, "order.create")
        invoice_inputs = merge_maps(
            {"id": order_id, "invoice_date": inputs.get("invoice_date")},
            inputs.get("send_options", {}),
            inputs.get("payment_spec", {}),
            inputs.get("prepayment", {}),
        )
        return self.commands.execute("order.invoice", invoice_inputs, context)

    def _invoice_direct(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        customer_id = self._ensure_customer_id(inputs.get("customer"), context)
        orders = inputs.get("orders")
        if not orders:
            orders = [{"orderLines": [self._build_line_item(item, context) for item in inputs.get("invoiceable_lines", [])]}]
        payload = {
            "customer_ref": id_ref(customer_id),
            "invoice_date": inputs.get("invoice_date"),
            "invoice_due_date": inputs.get("invoice_due_date"),
            "invoice_comment": inputs.get("invoice_comment"),
            "orders": orders,
        }
        if inputs.get("payment_spec"):
            payment_spec = dict(inputs["payment_spec"])
            if payment_spec.get("payment_type_ref") is not None:
                payment_spec["payment_type_id"] = self._resolve_id(
                    "invoice_payment_type",
                    payment_spec.pop("payment_type_ref"),
                    context,
                )
            payload.update(payment_spec)
        return self.commands.execute("invoice.create", payload, context)

    def _invoice_register_payment(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        invoice = self._resolve_record(
            "invoice",
            inputs.get("invoice_selector"),
            context,
            search_date_window=inputs.get("search_date_window"),
        )
        payment_spec = dict(inputs.get("payment_spec", {}))
        if payment_spec.get("payment_type_ref") is not None:
            payment_spec["payment_type_id"] = self._resolve_id(
                "invoice_payment_type",
                payment_spec.pop("payment_type_ref"),
                context,
            )
        return self.commands.execute("invoice.register_payment", {"id": invoice["id"], "payment_spec": payment_spec}, context)

    def _invoice_credit_note(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        invoice = self._resolve_record(
            "invoice",
            inputs.get("invoice_selector"),
            context,
            search_date_window=inputs.get("search_date_window"),
        )
        return self.commands.execute(
            "invoice.create_credit_note",
            {
                "id": invoice["id"],
                "date": inputs.get("credit_note_date"),
                "comment": inputs.get("comment"),
                **inputs.get("send_options", {}),
            },
            context,
        )

    def _travel_expense_create_basic(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        payload = {
            "employee_ref": id_ref(self._resolve_id("employee", inputs.get("employee"), context)),
            "travel_details": inputs.get("travel_details"),
            "title": inputs.get("title"),
        }
        if inputs.get("project") is not None:
            payload["project_ref"] = id_ref(self._resolve_id("project", inputs["project"], context))
        if inputs.get("department") is not None:
            payload["department_ref"] = id_ref(self._resolve_id("department", inputs["department"], context))
        return self.commands.execute("travel_expense.create", payload, context)

    def _travel_expense_create_with_rows(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        created = self._travel_expense_create_basic(inputs, context)
        travel_expense_id = self._extract_id(created, "travel_expense.create")
        for row in inputs.get("cost_rows", []):
            payload = dict(row)
            payload["travel_expense_ref"] = id_ref(travel_expense_id)
            if payload.get("cost_category_ref") is not None:
                payload["cost_category_ref"] = id_ref(self._resolve_id("travel_cost_category", payload["cost_category_ref"], context))
            if payload.get("payment_type_ref") is not None:
                payload["payment_type_ref"] = id_ref(self._resolve_id("travel_payment_type", payload["payment_type_ref"], context))
            if payload.get("vat_type_ref") is not None:
                payload["vat_type_ref"] = id_ref(self._resolve_id("vat_type", payload["vat_type_ref"], context))
            self.commands.execute("travel_expense.cost.create", payload, context)
        for row in inputs.get("mileage_rows", []):
            payload = dict(row)
            payload["travel_expense_ref"] = id_ref(travel_expense_id)
            if payload.get("rate_category_ref") is not None:
                payload["rate_category_ref"] = id_ref(self._resolve_id("travel_rate_category", payload["rate_category_ref"], context))
            rate_selector = payload.pop("rate_ref", payload.get("rate_type_ref"))
            if rate_selector is not None:
                payload["rate_type_ref"] = id_ref(self._resolve_id("travel_rate", rate_selector, context))
            self.commands.execute("travel_expense.mileage.create", payload, context)
        for row in inputs.get("per_diem_rows", []):
            payload = dict(row)
            payload["travel_expense_ref"] = id_ref(travel_expense_id)
            zone_selector = payload.pop("zone_ref", None)
            if zone_selector is not None:
                payload["travel_expense_zone_id"] = self._resolve_id("travel_zone", zone_selector, context)
            if payload.get("rate_category_ref") is not None:
                payload["rate_category_ref"] = id_ref(self._resolve_id("travel_rate_category", payload["rate_category_ref"], context))
            rate_selector = payload.pop("rate_ref", payload.get("rate_type_ref"))
            if rate_selector is not None:
                payload["rate_type_ref"] = id_ref(self._resolve_id("travel_rate", rate_selector, context))
            self.commands.execute("travel_expense.per_diem.create", payload, context)
        for row in inputs.get("accommodation_rows", []):
            payload = dict(row)
            payload["travel_expense_ref"] = id_ref(travel_expense_id)
            if payload.get("rate_category_ref") is not None:
                payload["rate_category_ref"] = id_ref(self._resolve_id("travel_rate_category", payload["rate_category_ref"], context))
            rate_selector = payload.pop("rate_ref", payload.get("rate_type_ref"))
            if rate_selector is not None:
                payload["rate_type_ref"] = id_ref(self._resolve_id("travel_rate", rate_selector, context))
            self.commands.execute("travel_expense.accommodation.create", payload, context)
        return created

    def _travel_expense_delete(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        record = self._resolve_record("travel_expense", inputs.get("travel_expense_selector"), context)
        return self.commands.execute("travel_expense.delete", {"id": record["id"]}, context)

    def _travel_expense_finalize_to_accounting(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        ids = inputs.get("travel_expense_ids")
        if ids is None:
            record = self._resolve_record("travel_expense", inputs.get("travel_expense_selector"), context)
            ids = [record["id"]]
        if isinstance(ids, int):
            ids = [ids]
        id_argument = ",".join(str(value) for value in ids)
        self.commands.execute("travel_expense.deliver", {"id": id_argument}, context)
        self.commands.execute(
            "travel_expense.approve",
            {"id": id_argument, "override_approval_flow": inputs.get("override_approval_flow")},
            context,
        )
        return self.commands.execute(
            "travel_expense.create_vouchers",
            {"id": id_argument, "date": inputs.get("voucher_date")},
            context,
        )

    def _project_create_for_customer(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        payload = dict(inputs)
        if payload.get("customer") is not None:
            payload["customer_ref"] = id_ref(self._ensure_customer_id(payload.pop("customer"), context))
        if payload.get("project_manager") is not None:
            payload["project_manager_ref"] = id_ref(self._resolve_id("employee", payload.pop("project_manager"), context))
        if payload.get("department") is not None:
            payload["department_ref"] = id_ref(self._resolve_id("department", payload.pop("department"), context))
        return self.commands.execute("project.create", payload, context)

    def _supplier_create_or_update(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        payload = dict(inputs)
        selector = payload.pop("supplier_selector", None)
        patch_mode = payload.pop("patch_mode", "auto")
        if payload.get("account_manager") is not None:
            payload["account_manager_ref"] = id_ref(self._resolve_id("employee", payload.pop("account_manager"), context))
        lookup = selector or {
            key: payload[key]
            for key in ("name", "organization_number", "email", "invoice_email")
            if payload.get(key)
        }
        if lookup and patch_mode != "create":
            matches = self._search_matches_for_upsert("supplier", lookup, context)
            if matches is not None:
                if len(matches) == 1:
                    current = self._get("supplier", matches[0]["id"], context)
                    update_payload = merge_maps(payload, {"id": current["id"], "version": current.get("version")})
                    return self.commands.execute("supplier.update", update_payload, context)
                if len(matches) > 1:
                    raise RawExecutionError(message="supplier.create_or_update matched multiple suppliers.")
        return self.commands.execute("supplier.create", payload, context)

    def _search_matches_for_upsert(
        self,
        family: str,
        selector: Any,
        context: ExecutionContext,
    ) -> list[dict[str, Any]] | None:
        search_inputs, _, has_searchable_criteria = self._prepare_search_inputs(family, selector, context)
        if not has_searchable_criteria:
            return None
        matches = extract_values(self.commands.execute(SEARCH_COMMANDS[family], search_inputs, context))
        return [item for item in matches if isinstance(item, dict)]

    def _department_create_with_manager(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        payload = dict(inputs)
        if payload.get("department_manager") is not None:
            payload["department_manager_ref"] = id_ref(
                self._resolve_id("employee", payload.pop("department_manager"), context)
            )
        return self.commands.execute("department.create", payload, context)

    def _department_enable_accounting_module(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        modules = extract_values(self.commands.execute("company.sales_modules.list", {}, context))
        desired = inputs.get("desired_module_name")
        already_active = any(isinstance(item, dict) and item.get("name") == desired for item in modules)
        if not already_active:
            self.commands.execute(
                "company.sales_modules.activate",
                {"name": desired, "cost_start_date": inputs.get("cost_start_date")},
                context,
            )
        if inputs.get("department_payload"):
            return self.commands.execute("department.create", inputs["department_payload"], context)
        return {"value": {"moduleActivated": desired}}

    def _voucher_manual_adjustment(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        payload = {
            "date": inputs.get("date"),
            "description": inputs.get("description"),
            "postings": [self._build_posting_line(line, context) for line in inputs.get("postings", [])],
            "send_to_ledger": inputs.get("send_to_ledger"),
        }
        if inputs.get("voucher_type") is not None:
            payload["voucher_type_ref"] = id_ref(self._resolve_id("voucher_type", inputs["voucher_type"], context))
        return self.commands.execute("voucher.create", payload, context)

    def _voucher_reverse_or_correct(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        voucher = self._resolve_record(
            "voucher",
            inputs.get("voucher_selector"),
            context,
            search_date_window=inputs.get("search_date_window"),
        )
        if inputs.get("correction_mode") == "reverse" or not inputs.get("correction_postings"):
            return self.commands.execute(
                "voucher.reverse",
                {"id": voucher["id"], "date": inputs.get("reverse_date")},
                context,
            )
        return self._voucher_manual_adjustment(
            {
                "date": inputs.get("reverse_date"),
                "description": inputs.get("description", "Manual voucher correction"),
                "voucher_type": inputs.get("voucher_type"),
                "postings": inputs.get("correction_postings", []),
            },
            context,
        )

    def _ledger_verify_effect(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        filters = dict(inputs.get("posting_filters", {}))
        if inputs.get("voucher_selector") is not None:
            voucher = self._resolve_record(
                "voucher",
                inputs["voucher_selector"],
                context,
                search_date_window=inputs.get("search_date_window") or inputs.get("posting_filters", {}).get("date_window"),
            )
            filters["voucher_id"] = voucher["id"]
        if filters.get("date_window") and not filters.get("date_from") and not filters.get("date_to"):
            window = filters.pop("date_window")
            if isinstance(window, dict):
                filters.setdefault("date_from", window.get("from"))
                filters.setdefault("date_to", window.get("to"))
        return self.commands.execute("ledger.posting.search", filters, context)

    def _supplier_invoice_register_payment(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        supplier_invoice = self._resolve_record(
            "supplier_invoice",
            inputs.get("supplier_invoice_selector"),
            context,
            search_date_window=inputs.get("search_date_window"),
        )
        payload = {
            "invoice_id": supplier_invoice["id"],
            "payment_type": inputs.get("payment_type"),
            "amount": inputs.get("amount"),
            "payment_date": inputs.get("payment_date"),
            "kid_or_receiver_reference": inputs.get("kid_or_receiver_reference"),
            "bban": inputs.get("bban"),
            "use_default_payment_type": inputs.get("use_default_payment_type"),
            "partial_payment": inputs.get("partial_payment"),
        }
        return self.commands.execute("supplier_invoice.add_payment", payload, context)

    def _supplier_invoice_import_from_attachment(self, inputs: dict[str, Any], context: ExecutionContext) -> Any:
        attachment_id = inputs.get("attachment_id")
        self._resolve_attachment(attachment_id, context)
        supplier_id = None
        if inputs.get("supplier") is not None:
            supplier_id = self._ensure_supplier_id(inputs.get("supplier"), context)
        imported = self.commands.execute(
            "ledger.voucher.import_document",
            {
                "attachment_id": attachment_id,
                "description": inputs.get("description"),
                "split": inputs.get("split"),
            },
            context,
        )
        voucher_id = self._extract_id(imported, "ledger.voucher.import_document")
        result: dict[str, Any] = {"imported": imported}
        incoming_invoice = self.commands.execute("incoming_invoice.get", {"voucher_id": voucher_id}, context)
        result["incomingInvoice"] = incoming_invoice
        if inputs.get("invoice_header") is not None or inputs.get("order_lines") is not None or inputs.get("send_to") is not None:
            invoice_header = dict(inputs.get("invoice_header", {}))
            if supplier_id is not None and "supplier" not in invoice_header:
                invoice_header["supplier"] = {"id": supplier_id}
            version = self._extract_version(incoming_invoice)
            update_payload = {
                "voucher_id": voucher_id,
                "send_to": inputs.get("send_to"),
                "version": version,
                "invoice_header": invoice_header or None,
                "order_lines": inputs.get("order_lines"),
            }
            result["updatedIncomingInvoice"] = self.commands.execute("incoming_invoice.update", update_payload, context)
        if inputs.get("postings"):
            result["postings"] = self.commands.execute(
                "supplier_invoice.voucher.update_postings",
                {
                    "id": voucher_id,
                    "voucher_date": inputs.get("voucher_date"),
                    "send_to_ledger": inputs.get("send_to_ledger"),
                    "postings": [self._build_posting_line(line, context) for line in inputs.get("postings", [])],
                },
                context,
            )
        return result

    def _extract_version(self, payload: Any) -> int | None:
        values = extract_values(payload)
        if not values or not isinstance(values[0], dict):
            return None
        version = values[0].get("version")
        return version if isinstance(version, int) else None
