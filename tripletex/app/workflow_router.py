from __future__ import annotations

import re
from typing import Any

from .internal_tasks import FlowKind, InternalTask
from .spec_runtime import (
    best_effort_amount,
    best_effort_date_window,
    best_effort_payment_type_description,
    best_effort_payment_type_id,
    combine_analysis_text,
    default_action_date,
    infer_entitlement_template,
    is_employee_admin_task,
    is_invoice_payment_task,
    lookup_analysis_value,
    resolved_invoice_from_history,
)
from .tasking import PlannedAction, PlannerDecision, TaskAnalysis


class DeterministicWorkflowRouter:
    def next_step(
        self,
        *,
        internal_task: InternalTask,
        task_prompt: str,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if not internal_task.is_supported:
            return None

        if internal_task.flow_kind is FlowKind.SALES_WORKFLOW:
            return self._next_sales_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        if internal_task.flow_kind is FlowKind.INVOICE_REGISTER_PAYMENT:
            return self._next_invoice_payment(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        if internal_task.flow_kind is FlowKind.EMPLOYEE_ADMIN:
            return self._next_employee_admin(
                internal_task=internal_task,
                history=history,
            )
        if internal_task.flow_kind is FlowKind.EMPLOYEE_UPSERT:
            return self._next_employee_upsert(internal_task=internal_task, history=history)
        if internal_task.flow_kind is FlowKind.CUSTOMER_UPSERT:
            return self._next_customer_upsert(internal_task=internal_task, history=history)
        if internal_task.flow_kind is FlowKind.PRODUCT_UPSERT:
            return self._next_product_upsert(internal_task=internal_task, history=history)
        if internal_task.flow_kind is FlowKind.DEPARTMENT_UPSERT:
            return self._next_department_upsert(internal_task=internal_task, history=history)
        if internal_task.flow_kind is FlowKind.PROJECT_UPSERT:
            return self._next_project_upsert(internal_task=internal_task, history=history)
        if internal_task.flow_kind is FlowKind.LEDGER_DIMENSION_WORKFLOW:
            return self._next_ledger_dimension_workflow(internal_task=internal_task, history=history)

        return None

    def _next_customer_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="customer",
            resource_path="/customer",
            resolver=_resolved_customer_from_internal,
            allowed_fields=(
                "name",
                "organizationNumber",
                "email",
                "invoiceEmail",
                "phoneNumber",
                "phoneNumberMobile",
                "description",
            ),
        )

    def _next_product_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="product",
            resource_path="/product",
            resolver=_resolved_product_from_internal,
            allowed_fields=(
                "name",
                "number",
                "description",
                "orderLineDescription",
                "priceExcludingVatCurrency",
            ),
        )

    def _next_department_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="department",
            resource_path="/department",
            resolver=_resolved_department_from_internal,
            allowed_fields=("name", "departmentNumber"),
        )

    def _next_employee_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="employee",
            resource_path="/employee",
            resolver=_resolved_employee_from_internal,
            allowed_fields=(
                "firstName",
                "lastName",
                "email",
                "employeeNumber",
                "phoneNumberMobile",
                "phoneNumberWork",
                "comments",
                "userType",
            ),
        )

    def _next_project_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        payload = dict(internal_task.payload)
        customer_ref = payload.pop("customerRef", None)
        department_ref = payload.pop("departmentRef", None)
        manager_ref = payload.pop("projectManagerRef", None)

        customer = _resolved_customer_by_ref(history, customer_ref)
        if customer_ref and customer is None:
            search_params = _drop_empty(dict(customer_ref))
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the project customer before creating or updating the project.",
                    method="GET",
                    path="/customer",
                    params=search_params,
                )
            return None

        department = _resolved_department_by_ref(history, department_ref)
        if department_ref and department is None:
            search_params = _drop_empty(dict(department_ref))
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/department",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the department before creating or updating the project.",
                    method="GET",
                    path="/department",
                    params=search_params,
                )
            return None

        manager = _resolved_employee_by_ref(history, manager_ref)
        if manager_ref and manager is None:
            search_params = _drop_empty(dict(manager_ref))
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the project manager before creating or updating the project.",
                    method="GET",
                    path="/employee",
                    params=search_params,
                )
            return None

        desired = dict(payload)
        if customer is not None and customer.get("id") not in {None, ""}:
            desired["customer"] = {"id": customer["id"]}
        if department is not None and department.get("id") not in {None, ""}:
            desired["department"] = {"id": department["id"]}
        if manager is not None and manager.get("id") not in {None, ""}:
            desired["projectManager"] = {"id": manager["id"]}

        if not desired:
            return None

        project = _resolved_project_from_internal(history, internal_task)
        if project is None:
            if internal_task.search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/project",
                predicate=lambda request: _request_contains_params(request, internal_task.search),
            ):
                return _action(
                    reason="Resolve the project before mutating it or creating a duplicate.",
                    method="GET",
                    path="/project",
                    params=internal_task.search,
                )

            if internal_task.operation == "update":
                return None

            return _action(
                reason="Create the project using the canonical OpenAPI fields and resolved linked entities.",
                method="POST",
                path="/project",
                json=desired,
            )

        if _entity_matches(project, desired):
            return PlannerDecision(kind="finish", reason="The project already satisfies the requested state.")

        project_id = project.get("id")
        if project_id in {None, ""}:
            return None

        update_payload = _build_update_payload(
            project,
            desired,
            allowed_fields=(
                "name",
                "number",
                "description",
                "reference",
                "startDate",
                "endDate",
                "invoiceReceiverEmail",
                "overdueNoticeEmail",
                "isFixedPrice",
                "fixedprice",
                "customer",
                "department",
                "projectManager",
            ),
        )
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"/project/{project_id}",
            predicate=lambda request: _request_json_contains(request, update_payload),
        ):
            return None

        return _action(
            reason="Update the resolved project with the requested canonical fields.",
            method="PUT",
            path=f"/project/{project_id}",
            json=update_payload,
        )

    def _next_sales_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        create_invoice = bool(internal_task.payload.get("createInvoice"))
        register_payment = bool(internal_task.payload.get("registerPayment"))

        if create_invoice and _has_success(history, method="PUT", path_suffix="/:invoice"):
            return PlannerDecision(kind="finish", reason="The sales workflow already completed its invoice step.")
        if not create_invoice and _has_success_exact(history, method="POST", path="/order"):
            return PlannerDecision(kind="finish", reason="The order has already been created.")

        customer = _resolved_customer_by_ref(history, internal_task.search or internal_task.payload.get("customer"))
        customer_payload = dict(internal_task.payload.get("customer") or {})
        if customer is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the customer before creating the sales order.",
                    method="GET",
                    path="/customer",
                    params=search_params,
                )
            if not customer_payload:
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/customer",
                predicate=lambda request: _request_json_contains(request, customer_payload),
            ):
                return None
            return _action(
                reason="Create the customer because the workflow did not find an exact match in the fresh account.",
                method="POST",
                path="/customer",
                json=customer_payload,
            )

        order_lines = list(internal_task.payload.get("orderLines") or [])
        if not order_lines:
            return None

        for line in order_lines:
            product = _resolved_product_by_ref(
                history,
                {
                    "productNumber": line.get("productNumber"),
                    "name": line.get("description"),
                },
            )
            if product is not None:
                continue

            search_params = _drop_empty({"productNumber": line.get("productNumber"), "count": 10})
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/product",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason=f"Resolve product {line.get('productNumber')} before creating the order.",
                    method="GET",
                    path="/product",
                    params=search_params,
                )

            product_payload = _product_payload_from_order_line(line)
            if not product_payload:
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/product",
                predicate=lambda request: _request_json_contains(request, product_payload),
            ):
                return None
            return _action(
                reason=f"Create product {line.get('productNumber')} because it does not exist in the fresh account.",
                method="POST",
                path="/product",
                json=product_payload,
            )

        order = _resolved_order_from_history(history)
        if order is None:
            order_payload = _build_order_payload_from_internal(internal_task, customer=customer, history=history)
            if order_payload is None:
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/order",
                predicate=lambda request: _request_json_contains(request, order_payload),
            ):
                return None
            return _action(
                reason="Create the order with the resolved customer and products.",
                method="POST",
                path="/order",
                json=order_payload,
            )

        if not create_invoice:
            return PlannerDecision(kind="finish", reason="The order workflow is complete.")

        order_id = order.get("id")
        if order_id in {None, ""}:
            return None

        params: dict[str, Any] = {
            "invoiceDate": internal_task.payload.get("invoiceDate") or task_analysis.payload_fields.get("invoiceDate"),
        }

        if register_payment:
            payment_type_id = best_effort_payment_type_id(task_analysis, history)
            if payment_type_id in {None, ""}:
                payment_type_params: dict[str, Any] = {"count": 10, "fields": "id,description"}
                description = (
                    internal_task.payload.get("paymentTypeDescription")
                    or best_effort_payment_type_description(task_analysis)
                )
                if description:
                    payment_type_params["description"] = description
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/invoice/paymentType",
                    predicate=lambda request: _request_contains_params(request, payment_type_params),
                ):
                    return _action(
                        reason="Resolve an outgoing invoice payment type before invoicing the order as fully paid.",
                        method="GET",
                        path="/invoice/paymentType",
                        params=payment_type_params,
                    )
                payment_type_id = _fallback_first_payment_type_id(history)
                if payment_type_id in {None, ""}:
                    return None

            total_amount = _sales_total_amount(internal_task)
            if total_amount in {None, ""}:
                return None
            params["paymentTypeId"] = payment_type_id
            params["paidAmount"] = total_amount

        return _action(
            reason="Convert the resolved order into an invoice using the canonical Tripletex action endpoint.",
            method="PUT",
            path=f"/order/{order_id}/:invoice",
            params=_drop_empty(params),
        )

    def _next_invoice_payment(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if _has_success(history, method="PUT", path_suffix="/:payment"):
            return PlannerDecision(kind="finish", reason="Invoice payment action already completed.")

        invoice = resolved_invoice_from_history(history, task_analysis)
        if invoice is None:
            if _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice",
                predicate=lambda request: _request_contains_params(request, _invoice_search_params(task_analysis) or {}),
            ):
                return None
            search_params = _invoice_search_params(task_analysis)
            if internal_task.search.get("invoiceNumber") not in {None, ""}:
                search_params = {
                    **(search_params or {}),
                    "invoiceNumber": internal_task.search["invoiceNumber"],
                }
            if search_params is None:
                return None
            return _action(
                reason="Resolve the target invoice with a spec-valid invoice search before registering payment.",
                method="GET",
                path="/invoice",
                params=search_params,
            )

        invoice_id = invoice.get("id")
        if invoice_id in {None, ""}:
            return None

        payment_type_id = best_effort_payment_type_id(task_analysis, history)
        if payment_type_id in {None, ""}:
            params: dict[str, Any] = {"count": 10}
            description = internal_task.payload.get("paymentTypeDescription") or best_effort_payment_type_description(task_analysis)
            if description:
                params["description"] = description
            if _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice/paymentType",
                predicate=lambda request: _request_contains_params(request, params),
            ):
                payment_type_id = _fallback_first_payment_type_id(history)
                if payment_type_id in {None, ""}:
                    return None
            else:
                return _action(
                    reason="Resolve paymentTypeId through the dedicated invoice payment-type endpoint before registering payment.",
                    method="GET",
                    path="/invoice/paymentType",
                    params=params,
                )

        paid_amount = internal_task.payload.get("paidAmount") or best_effort_amount(task_analysis, history)
        if paid_amount in {None, ""}:
            return None

        return _action(
            reason="Register payment on the resolved invoice using the canonical Tripletex payment action.",
            method="PUT",
            path=f"/invoice/{invoice_id}/:payment",
            params={
                "paymentDate": internal_task.payload.get("paymentDate"),
                "paymentTypeId": payment_type_id,
                "paidAmount": paid_amount,
            },
        )

    def _next_employee_admin(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        template = internal_task.payload.get("template")
        if template is None:
            return None

        if _has_success(history, method="PUT", path_prefix="/employee/entitlement/"):
            return PlannerDecision(kind="finish", reason="Employee entitlement action already completed.")

        employee = _resolved_employee_from_internal(history, internal_task)
        if employee is None:
            if internal_task.operation != "update":
                payload = dict(internal_task.payload)
                if payload is None:
                    return None
                payload["userType"] = "EXTENDED"
                payload.pop("template", None)
                if _has_attempt_exact_where(
                    history,
                    method="POST",
                    path="/employee",
                    predicate=lambda request: _request_json_contains(request, payload),
                ):
                    return None
                return _action(
                    reason="Create the employee with EXTENDED access so entitlement templates can be applied safely.",
                    method="POST",
                    path="/employee",
                    json=payload,
                )

            search_params = internal_task.search
            if search_params is None:
                return None
            if _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return None
            return _action(
                reason="Resolve the employee before applying administrator entitlements.",
                method="GET",
                path="/employee",
                params=search_params,
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return None

        if employee.get("userType") != "EXTENDED":
            if employee.get("version") in {None, ""}:
                return _action(
                    reason="Fetch the employee record with version information before upgrading userType.",
                    method="GET",
                    path=f"/employee/{employee_id}",
                )

            updated_employee = _build_update_payload(
                employee,
                {"userType": "EXTENDED"},
                allowed_fields=(
                    "firstName",
                    "lastName",
                    "email",
                    "employeeNumber",
                    "phoneNumberMobile",
                    "phoneNumberWork",
                    "comments",
                    "userType",
                ),
            )
            return _action(
                reason="Upgrade the employee to EXTENDED access before applying administrator entitlements.",
                method="PUT",
                path=f"/employee/{employee_id}",
                json=updated_employee,
            )

        return _action(
            reason="Grant the entitlement template needed for the requested administrator-style role.",
            method="PUT",
            path="/employee/entitlement/:grantEntitlementsByTemplate",
            params={
                "employeeId": employee_id,
                "template": template,
            },
        )

    def _next_ledger_dimension_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        dimension_name = internal_task.payload.get("dimensionName")
        if dimension_name in {None, ""}:
            return None

        dimension = _resolved_dimension_name_from_history(history, dimension_name=str(dimension_name))
        if dimension is None:
            if not _has_attempt_exact(history, method="GET", path="/ledger/accountingDimensionName"):
                return _action(
                    reason="List existing accounting dimensions before creating a new one.",
                    method="GET",
                    path="/ledger/accountingDimensionName",
                    params={"count": 20, "fields": "id,dimensionName,dimensionIndex,active"},
                )

            create_payload = {
                "dimensionName": dimension_name,
                "description": dimension_name,
                "active": True,
            }
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/ledger/accountingDimensionName",
                predicate=lambda request: _request_json_contains(request, create_payload),
            ):
                return None
            return _action(
                reason="Create the requested free accounting dimension using the canonical OpenAPI field names.",
                method="POST",
                path="/ledger/accountingDimensionName",
                json=create_payload,
            )

        dimension_index = dimension.get("dimensionIndex")
        if dimension_index in {None, ""}:
            return None

        values = list(internal_task.payload.get("dimensionValues") or [])
        for value_name in values:
            existing_value = _resolved_dimension_value_from_history(
                history,
                dimension_index=dimension_index,
                display_name=str(value_name),
            )
            if existing_value is not None:
                continue

            search_params = {
                "dimensionIndex": dimension_index,
                "count": 50,
                "fields": "id,displayName,dimensionIndex,active",
            }
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/accountingDimensionValue/search",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason=f"List existing values for accounting dimension {dimension_name} before creating {value_name}.",
                    method="GET",
                    path="/ledger/accountingDimensionValue/search",
                    params=search_params,
                )

            create_payload = {
                "displayName": value_name,
                "dimensionIndex": dimension_index,
                "active": True,
                "showInVoucherRegistration": True,
                "number": str(value_name),
            }
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/ledger/accountingDimensionValue",
                predicate=lambda request: _request_json_contains(request, create_payload),
            ):
                return None
            return _action(
                reason=f"Create accounting dimension value {value_name} on dimension {dimension_name}.",
                method="POST",
                path="/ledger/accountingDimensionValue",
                json=create_payload,
            )

        if not internal_task.payload.get("requiresVoucher"):
            return PlannerDecision(kind="finish", reason="The accounting dimension workflow is complete.")

        return None

    def _next_simple_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
        resource_name: str,
        resource_path: str,
        resolver: Any,
        allowed_fields: tuple[str, ...],
    ) -> PlannerDecision | None:
        desired = dict(internal_task.payload)
        if not desired:
            return None

        entity = resolver(history, internal_task)
        if entity is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path=resource_path,
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason=f"Resolve the {resource_name} before mutating it or creating a duplicate.",
                    method="GET",
                    path=resource_path,
                    params=search_params,
                )
            if internal_task.operation == "update":
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path=resource_path,
                predicate=lambda request: _request_json_contains(request, desired),
            ):
                return None
            return _action(
                reason=f"Create the {resource_name} using the canonical OpenAPI fields.",
                method="POST",
                path=resource_path,
                json=desired,
            )

        if _entity_matches(entity, desired):
            return PlannerDecision(kind="finish", reason=f"The {resource_name} already satisfies the requested state.")

        entity_id = entity.get("id")
        if entity_id in {None, ""}:
            return None

        update_payload = _build_update_payload(entity, desired, allowed_fields=allowed_fields)
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"{resource_path}/{entity_id}",
            predicate=lambda request: _request_json_contains(request, update_payload),
        ):
            return None

        return _action(
            reason=f"Update the resolved {resource_name} to the requested state.",
            method="PUT",
            path=f"{resource_path}/{entity_id}",
            json=update_payload,
        )


def _action(
    *,
    reason: str,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json: Any | None = None,
) -> PlannerDecision:
    return PlannerDecision(
        kind="action",
        reason=reason,
        action=PlannedAction(
            method=method,
            path=path,
            params=params,
            json=json,
        ),
    )


def _request_contains_params(request: dict[str, Any], expected: dict[str, Any]) -> bool:
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return False
    return all(params.get(key) == value for key, value in expected.items())


def _request_json_contains(request: dict[str, Any], expected: dict[str, Any]) -> bool:
    return _entity_matches(request.get("json") or {}, expected)


def _entity_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for key, value in expected.items():
            if key not in actual:
                return False
            if not _entity_matches(actual.get(key), value):
                return False
        return True
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all(_entity_matches(left, right) for left, right in zip(actual, expected))
    return actual == expected


def _build_update_payload(
    current: dict[str, Any],
    desired: dict[str, Any],
    *,
    allowed_fields: tuple[str, ...],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": current.get("id"),
    }
    if current.get("version") not in {None, ""}:
        payload["version"] = current["version"]
    for field in allowed_fields:
        value = desired[field] if field in desired else current.get(field)
        if value in {None, ""}:
            continue
        payload[field] = value
    return payload


def _drop_empty(mapping: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in mapping.items():
        if _is_blank(value):
            continue
        if isinstance(value, dict):
            nested = _drop_empty(value)
            if nested:
                cleaned[key] = nested
            continue
        if isinstance(value, list):
            if value:
                cleaned[key] = value
            continue
        cleaned[key] = value
    return cleaned


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _resolved_customer_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_org = ref.get("organizationNumber")
    target_name = ref.get("customerName") or ref.get("name")
    target_email = ref.get("email")

    target_org = str(target_org) if not _is_blank(target_org) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None
    target_email = str(target_email).lower() if not _is_blank(target_email) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/customer" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/customer" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/customer/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_org and str(candidate.get("organizationNumber")) == target_org:
                return candidate
            if target_email and str(candidate.get("email") or "").lower() == target_email:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_org, target_name, target_email)):
            return candidates[0]
    return None


def _resolved_product_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_number = ref.get("productNumber") or ref.get("number")
    target_name = ref.get("name")
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/product" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/product" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/product/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_number and str(candidate.get("number")) == target_number:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_number, target_name)):
            return candidates[0]
    return None


def _resolved_employee_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_email = ref.get("email")
    target_first = ref.get("firstName")
    target_last = ref.get("lastName")
    target_email = str(target_email).lower() if not _is_blank(target_email) else None
    target_first = str(target_first).lower() if not _is_blank(target_first) else None
    target_last = str(target_last).lower() if not _is_blank(target_last) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/employee" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/employee" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/employee/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_email and str(candidate.get("email") or "").lower() == target_email:
                return candidate
            if target_first and target_last:
                if (
                    str(candidate.get("firstName") or "").lower() == target_first
                    and str(candidate.get("lastName") or "").lower() == target_last
                ):
                    return candidate
        if len(candidates) == 1 and not any((target_email, target_first, target_last)):
            return candidates[0]
    return None


def _resolved_department_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_number = ref.get("departmentNumber")
    target_name = ref.get("name")
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/department" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/department" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/department/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_number and str(candidate.get("departmentNumber")) == target_number:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_number, target_name)):
            return candidates[0]
    return None


def _resolved_project_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_number = ref.get("number")
    target_name = ref.get("name")
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/project" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/project" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/project/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_number and str(candidate.get("number")) == target_number:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_number, target_name)):
            return candidates[0]
    return None


def _resolved_customer_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_customer_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_product_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_product_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_employee_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_employee_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_department_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_department_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_project_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_project_by_ref(history, internal_task.search or internal_task.payload)


def _product_payload_from_order_line(line: dict[str, Any]) -> dict[str, Any] | None:
    product_number = line.get("productNumber")
    description = line.get("description")
    if _is_blank(product_number) or _is_blank(description):
        return None
    payload = {
        "name": description,
        "number": product_number,
    }
    if line.get("unitPriceExcludingVatCurrency") not in {None, ""}:
        payload["priceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
    return payload


def _build_order_payload_from_internal(
    internal_task: InternalTask,
    *,
    customer: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    customer_id = customer.get("id")
    if customer_id in {None, ""}:
        return None

    order_lines: list[dict[str, Any]] = []
    for line in internal_task.payload.get("orderLines") or []:
        product = _resolved_product_by_ref(
            history,
            {"productNumber": line.get("productNumber"), "name": line.get("description")},
        )
        if product is None or product.get("id") in {None, ""}:
            return None
        order_line = {
            "product": {"id": product["id"]},
            "count": line.get("count") or 1,
        }
        if not _is_blank(line.get("description")):
            order_line["description"] = line["description"]
        if line.get("unitPriceExcludingVatCurrency") not in {None, ""}:
            order_line["unitPriceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
        order_lines.append(order_line)

    if not order_lines:
        return None

    return {
        "customer": {"id": customer_id},
        "orderDate": internal_task.payload.get("orderDate"),
        "orderLines": order_lines,
    }


def _sales_total_amount(internal_task: InternalTask) -> float | None:
    total = 0.0
    order_lines = list(internal_task.payload.get("orderLines") or [])
    if not order_lines:
        return None
    for line in order_lines:
        unit_price = line.get("unitPriceExcludingVatCurrency")
        if unit_price in {None, ""}:
            return None
        total += float(unit_price) * float(line.get("count") or 1)
    return total


def _resolved_dimension_name_from_history(
    history: list[dict[str, Any]],
    *,
    dimension_name: str,
) -> dict[str, Any] | None:
    target = dimension_name.lower()
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/ledger/accountingDimensionName" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/ledger/accountingDimensionName" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/ledger/accountingDimensionName/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if str(candidate.get("dimensionName") or "").lower() == target:
                return candidate
    return None


def _resolved_dimension_value_from_history(
    history: list[dict[str, Any]],
    *,
    dimension_index: Any,
    display_name: str,
) -> dict[str, Any] | None:
    target_name = display_name.lower()
    target_index = str(dimension_index)
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/ledger/accountingDimensionValue" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/ledger/accountingDimensionValue/search" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/ledger/accountingDimensionValue/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if str(candidate.get("dimensionIndex")) != target_index:
                continue
            if str(candidate.get("displayName") or "").lower() == target_name:
                return candidate
    return None


def _invoice_search_params(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    invoice_number = lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number")
    customer_id = lookup_analysis_value(task_analysis, "customerId", "customer_id")
    if invoice_number in {None, ""} and customer_id in {None, ""}:
        return None

    date_from, date_to = best_effort_date_window(
        task_analysis,
        start_key="invoiceDateFrom",
        end_key="invoiceDateTo",
    )
    params: dict[str, Any] = {
        "invoiceDateFrom": date_from,
        "invoiceDateTo": date_to,
        "count": 10,
    }
    if invoice_number not in {None, ""}:
        params["invoiceNumber"] = invoice_number
    if customer_id not in {None, ""}:
        params["customerId"] = customer_id
    return params


def _customer_search_params(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    organization_number = lookup_analysis_value(
        task_analysis,
        "organizationNumber",
        "customer_organizationNumber",
        "customerOrganizationNumber",
    )
    customer_name = lookup_analysis_value(
        task_analysis,
        "customerName",
        "customer_name",
        "name",
    )

    params: dict[str, Any] = {"count": 10, "fields": "id,name,organizationNumber"}
    if organization_number not in {None, ""}:
        params["organizationNumber"] = organization_number
        return params
    if customer_name not in {None, ""}:
        params["customerName"] = customer_name
        return params
    return None


def _build_customer_create_payload(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    organization_number = lookup_analysis_value(
        task_analysis,
        "organizationNumber",
        "customer_organizationNumber",
        "customerOrganizationNumber",
    )
    customer_name = lookup_analysis_value(
        task_analysis,
        "customerName",
        "customer_name",
        "name",
    )
    if customer_name in {None, ""}:
        return None
    payload: dict[str, Any] = {
        "name": customer_name,
        "isCustomer": True,
    }
    if organization_number not in {None, ""}:
        payload["organizationNumber"] = organization_number
    return payload


def _extract_order_line_specs(task_analysis: TaskAnalysis) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for key, value in task_analysis.payload_fields.items():
        match = re.fullmatch(r"orderLine(\d+)_(.+)", str(key))
        if not match:
            continue
        line_number = int(match.group(1))
        grouped.setdefault(line_number, {"line_number": line_number})[match.group(2)] = value

    specs: list[dict[str, Any]] = []
    for line_number in sorted(grouped):
        entry = grouped[line_number]
        product_number = entry.get("productNumber")
        description = entry.get("description")
        unit_price = entry.get("unitPrice")
        if product_number in {None, ""}:
            continue
        specs.append(
            {
                "line_number": line_number,
                "product_number": str(product_number),
                "description": str(description or ""),
                "unit_price": float(unit_price) if unit_price not in {None, ""} else None,
                "count": float(entry.get("count") or 1),
            }
        )
    return specs


def _build_product_create_payload(spec: dict[str, Any]) -> dict[str, Any] | None:
    if not spec.get("description"):
        return None
    payload: dict[str, Any] = {
        "name": spec["description"],
        "number": spec["product_number"],
    }
    if spec.get("unit_price") not in {None, ""}:
        payload["priceExcludingVatCurrency"] = spec["unit_price"]
    return payload


def _build_order_create_payload(
    task_analysis: TaskAnalysis,
    *,
    customer: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    customer_id = customer.get("id")
    if customer_id in {None, ""}:
        return None

    line_specs = _extract_order_line_specs(task_analysis)
    order_lines: list[dict[str, Any]] = []
    for spec in line_specs:
        product = _resolved_product_from_history(history, task_analysis, line_number=spec["line_number"])
        if product is None or product.get("id") in {None, ""}:
            return None
        line: dict[str, Any] = {
            "product": {"id": product["id"]},
            "description": spec["description"] or product.get("name"),
            "count": spec["count"],
        }
        if spec.get("unit_price") not in {None, ""}:
            line["unitPriceExcludingVatCurrency"] = spec["unit_price"]
        order_lines.append(line)

    if not order_lines:
        return None

    return {
        "customer": {"id": customer_id},
        "orderDate": default_action_date(task_analysis, "orderDate", "date"),
        "orderLines": order_lines,
    }


def _resolved_customer_from_history(history: list[dict[str, Any]], task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    target_org = lookup_analysis_value(
        task_analysis,
        "organizationNumber",
        "customer_organizationNumber",
        "customerOrganizationNumber",
    )
    target_name = lookup_analysis_value(task_analysis, "customerName", "customer_name", "name")
    target_org = str(target_org) if target_org not in {None, ""} else None
    target_name = str(target_name).lower() if target_name not in {None, ""} else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if path == "/customer" and method == "POST" and isinstance(response.get("value"), dict):
            return response["value"]
        if path == "/customer" and method == "GET":
            values = response.get("values") or []
            if not isinstance(values, list):
                continue
            for candidate in values:
                if not isinstance(candidate, dict):
                    continue
                if target_org and str(candidate.get("organizationNumber")) == target_org:
                    return candidate
                if target_name and str(candidate.get("name") or "").lower() == target_name:
                    return candidate
            if len(values) == 1 and isinstance(values[0], dict):
                return values[0]
    return None


def _resolved_product_from_history(
    history: list[dict[str, Any]],
    task_analysis: TaskAnalysis,
    *,
    line_number: int,
) -> dict[str, Any] | None:
    specs = {spec["line_number"]: spec for spec in _extract_order_line_specs(task_analysis)}
    spec = specs.get(line_number)
    if spec is None:
        return None
    target_number = spec["product_number"]

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if path == "/product" and method == "POST" and isinstance(response.get("value"), dict):
            candidate = response["value"]
            if str(candidate.get("number")) == target_number:
                return candidate
        if path == "/product" and method == "GET":
            values = response.get("values") or []
            if not isinstance(values, list):
                continue
            for candidate in values:
                if isinstance(candidate, dict) and str(candidate.get("number")) == target_number:
                    return candidate
    return None


def _resolved_order_from_history(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("path") or "") != "/order" or str(request.get("method") or "").upper() != "POST":
            continue
        if isinstance(response.get("value"), dict):
            return response["value"]
    return None


def _order_total_amount(task_analysis: TaskAnalysis) -> float | None:
    total = 0.0
    line_specs = _extract_order_line_specs(task_analysis)
    if not line_specs:
        return None
    for spec in line_specs:
        unit_price = spec.get("unit_price")
        if unit_price in {None, ""}:
            return None
        total += float(unit_price) * float(spec.get("count") or 1)
    return total


def _fallback_first_payment_type_id(history: list[dict[str, Any]]) -> Any | None:
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("path") or "") != "/invoice/paymentType":
            continue
        for candidate in response.get("values") or []:
            if isinstance(candidate, dict) and candidate.get("id") not in {None, ""}:
                return candidate["id"]
    return None


def _is_order_invoice_workflow(task_analysis: TaskAnalysis, *, combined_text: str) -> bool:
    family = task_analysis.task_family.lower()
    if "order" not in family and (task_analysis.target_resource or "").lower() != "order":
        return False
    return any(token in combined_text for token in ("invoice", "payment", "paid", "full payment", "register full payment"))


def _looks_like_create(task_analysis: TaskAnalysis) -> bool:
    return task_analysis.operation == "create" or task_analysis.task_family.lower().endswith(".create")


def _build_employee_create_payload(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    first_name = lookup_analysis_value(task_analysis, "firstName", "first_name")
    last_name = lookup_analysis_value(task_analysis, "lastName", "last_name")

    if first_name in {None, ""} or last_name in {None, ""}:
        full_name = lookup_analysis_value(task_analysis, "name", "fullName", "displayName")
        if full_name not in {None, ""}:
            parts = str(full_name).strip().split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])

    if first_name in {None, ""} or last_name in {None, ""}:
        return None

    payload: dict[str, Any] = {
        "firstName": first_name,
        "lastName": last_name,
    }
    for source_key, target_key in (
        ("email", "email"),
        ("employeeNumber", "employeeNumber"),
        ("phoneNumberMobile", "phoneNumberMobile"),
        ("phoneNumber", "phoneNumberWork"),
    ):
        value = lookup_analysis_value(task_analysis, source_key)
        if value not in {None, ""}:
            payload[target_key] = value
    return payload


def _employee_search_params(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    email = lookup_analysis_value(task_analysis, "email")
    if email not in {None, ""}:
        return {
            "email": email,
            "count": 10,
        }

    first_name = lookup_analysis_value(task_analysis, "firstName", "first_name")
    last_name = lookup_analysis_value(task_analysis, "lastName", "last_name")
    if first_name not in {None, ""} or last_name not in {None, ""}:
        params = {"count": 10}
        if first_name not in {None, ""}:
            params["firstName"] = first_name
        if last_name not in {None, ""}:
            params["lastName"] = last_name
        return params
    return None


def _resolved_employee_from_history(history: list[dict[str, Any]], task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    target_email = lookup_analysis_value(task_analysis, "email")
    target_email = str(target_email).lower() if target_email not in {None, ""} else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if path == "/employee" and method in {"POST"} and isinstance(response.get("value"), dict):
            return response["value"]
        if path.startswith("/employee/") and method == "GET" and isinstance(response.get("value"), dict):
            return response["value"]
        if path == "/employee" and method == "GET":
            values = response.get("values") or []
            if not isinstance(values, list):
                continue
            if target_email:
                for candidate in values:
                    if isinstance(candidate, dict) and str(candidate.get("email") or "").lower() == target_email:
                        return candidate
            if len(values) == 1 and isinstance(values[0], dict):
                return values[0]
    return None


def _has_success(
    history: list[dict[str, Any]],
    *,
    method: str,
    path_prefix: str | None = None,
    path_suffix: str | None = None,
) -> bool:
    for entry in reversed(history):
        if "response" not in entry:
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        path = str(request.get("path") or "")
        if path_prefix is not None and not path.startswith(path_prefix):
            continue
        if path_suffix is not None and not path.endswith(path_suffix):
            continue
        return True
    return False


def _has_attempt_exact(history: list[dict[str, Any]], *, method: str, path: str) -> bool:
    return _has_attempt_exact_where(history, method=method, path=path, predicate=None)


def _has_attempt_exact_where(
    history: list[dict[str, Any]],
    *,
    method: str,
    path: str,
    predicate: Any | None,
) -> bool:
    for entry in reversed(history):
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        if str(request.get("path") or "") != path:
            continue
        if predicate is not None and not predicate(request):
            continue
        return True
    return False


def _has_success_exact(history: list[dict[str, Any]], *, method: str, path: str) -> bool:
    return _has_success_exact_where(history, method=method, path=path, predicate=None)


def _has_success_exact_where(
    history: list[dict[str, Any]],
    *,
    method: str,
    path: str,
    predicate: Any | None,
) -> bool:
    for entry in reversed(history):
        if "response" not in entry:
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        if str(request.get("path") or "") != path:
            continue
        if predicate is not None and not predicate(request):
            continue
        return True
    return False
