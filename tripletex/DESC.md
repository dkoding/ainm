# Tripletex Flow And Command Description

This document defines the wrapper API that should sit in front of a raw Tripletex client.

This document is intended to be the canonical wrapper contract for the LLM.

- Every exposed `COMMAND` must be listed here.
- Every exposed `FLOW` must be listed here.
- Every raw Tripletex operation in `docs/openapi.json` is in scope.
- Every raw Tripletex operation is callable as a low-level command through its exact OpenAPI `operationId`.
- Hand-authored friendly commands and business flows are additional aliases and orchestration layers on top of the full raw command surface.

It is based on:

- `ANALYSIS.md`
- `API.md`
- `docs/task-overview.html`
- `docs/task-endpoint.html`
- `docs/task-scoring.html`
- `docs/task-examples.html`
- `docs/task-sandbox.html`
- `docs/openapi.json`

The downloaded OpenAPI spec identifies itself as Tripletex API `2.74.00` and contains `546` paths. This document treats the entire OpenAPI surface as in scope. The hand-authored prose focuses on the most important business flows and friendly aliases, while full raw coverage is provided through the exact OpenAPI `operationId` model.

In the current canonical design described below, the wrapper surface consists of:

- `800` raw-operation commands, one per OpenAPI HTTP operation, addressed by exact `operationId`
- `78` hand-authored friendly command aliases for the most important operations
- `21` hand-authored business flows
- auto-derived technical flow families that cover the full remaining OpenAPI surface

## 1. Mental Model

The wrapper API should expose two layers:

- `COMMAND`
  One deterministic wrapper around one Tripletex API method, or around one very small family of methods with identical semantics. A command does not decide business intent. It only executes one concrete action or lookup.
- `FLOW`
  An ordered series of commands. A flow represents a business operation such as "create invoice from customer and lines" or "register payment on invoice".

The planner should work like this:

1. classify the prompt into a flow family
2. resolve or create prerequisites
3. run the smallest correct flow
4. verify only what is necessary

The most important design rule is: choose the `FLOW` first, then execute `COMMANDS`.

## 2. Global Rules For All Commands

### 2.1 Authentication and transport

- Always use `tripletex_credentials.base_url` from the solve request.
- Always use HTTP Basic Auth with username `0` and password `session_token`.
- Never hardcode the normal public Tripletex base URL in competition execution.

### 2.2 Response shape

Tripletex mostly uses:

- list/search responses: `{ fullResultSize, from, count, versionDigest, values }`
- single-entity responses: `{ value }`
- creates: usually HTTP `201`
- updates/actions: usually HTTP `200`
- deletes: usually HTTP `204`

### 2.3 Search behavior

- Prefer exact filters over broad search.
- Always use `fields` to reduce payload and avoid unnecessary rereads.
- Use `count` and `from` to keep result sets small.
- Several important search methods require date windows:
  - `GET /order`
  - `GET /invoice`
  - `GET /supplierInvoice`
  - `GET /ledger/posting`
  - `GET /ledger/voucher`

The wrapper should make those date windows explicit instead of pretending they are optional.

### 2.4 Update behavior

- Treat Tripletex `PUT` as full-enough update, not patch.
- If an entity has been read first, carry `id` and `version` into the update payload when practical.
- Search before update or delete unless the target ID is already known.

### 2.5 Action endpoints

Tripletex uses action-style endpoints with `:` in the path. These should be preferred over simulating the same outcome with multiple generic mutations.

Important examples:

- `PUT /order/{id}/:invoice`
- `PUT /invoice/{id}/:payment`
- `PUT /invoice/{id}/:createCreditNote`
- `PUT /travelExpense/:deliver`
- `PUT /travelExpense/:approve`
- `PUT /travelExpense/:createVouchers`
- `PUT /ledger/voucher/{id}/:reverse`

### 2.6 Delete vs reverse vs credit note

- Use `DELETE` only when the object type supports safe deletion and the prompt explicitly asks for deletion.
- For charged invoices, prefer credit note flow.
- For vouchers and accounting corrections, prefer reverse/correct flow over destructive deletion.

## 3. Shared Parameter Vocabulary

The wrapper should normalize business-shaped inputs into Tripletex-shaped parameters.

### 3.1 Common control parameters

- `fields`
  Sparse field selection. Should support raw Tripletex field syntax, including nested forms such as `project(name)`.
- `from`
  Pagination start offset.
- `count`
  Pagination size.
- `sorting`
  Tripletex sort expression.
- `date_window`
  Business-facing object with `from` and `to`, translated to endpoint-specific parameter names.

### 3.2 Selector objects

A selector is how the planner identifies an existing object before updating, deleting, linking, paying, or reversing it.

Recommended selector families:

- `employee_selector`
  `id`, `email`, `employee_number`, `first_name`, `last_name`, `department_id`
- `customer_selector`
  `id`, `organization_number`, `customer_account_number`, `email`, `invoice_email`, `name`
- `product_selector`
  `id`, `number`, `product_number`, `name`, `ean`
- `order_selector`
  `id`, `number`, `customer_id`, `date_window`
- `invoice_selector`
  `id`, `invoice_number`, `customer_id`, `voucher_id`, `kid`, `date_window`
- `travel_expense_selector`
  `id`, `employee_id`, `project_id`, `department_id`, `state`, `departure_date_from`, `return_date_to`
- `project_selector`
  `id`, `name`, `number`, `customer_id`, `project_manager_id`, `department_id`
- `department_selector`
  `id`, `name`, `department_number`, `department_manager_id`
- `voucher_selector`
  `id`, `number`, `type_id`, `date_window`
- `supplier_invoice_selector`
  `id`, `invoice_number`, `supplier_id`, `voucher_id`, `kid`, `date_window`

### 3.3 Reference objects

Many create/update commands should accept either:

- a direct ID reference, or
- a selector that can be resolved first

Recommended reference families:

- `employee_ref`
- `customer_ref`
- `product_ref`
- `project_ref`
- `department_ref`
- `account_ref`
- `vat_type_ref`
- `currency_ref`
- `product_unit_ref`
- `payment_type_ref`
- `voucher_type_ref`

### 3.4 Reusable business payloads

- `line_item`
  `product_ref?`, `description`, `count`, `unit_price_ex_vat?`, `unit_price_inc_vat?`, `vat_type_ref?`, `currency_ref?`
- `payment_spec`
  `payment_date`, `payment_type_ref`, `paid_amount`, `paid_amount_currency?`
- `posting_line`
  `account_ref`, `amount`, `amount_currency?`, `currency_ref?`, `date`, `description?`, `vat_type_ref?`, `customer_ref?`, `supplier_ref?`, `employee_ref?`, `project_ref?`, `department_ref?`
- `travel_details`
  `departure_date`, `return_date`, `departure_time?`, `return_time?`, `departure_from?`, `destination`, `purpose?`, `is_foreign_travel?`, `is_day_trip?`, `is_compensation_from_rates?`

## 4. Planner Guidance

### 4.1 When to choose each flow family

- Use a single-entity create flow when the prompt only asks to create one object and there are no required dependencies.
- Use a search-then-update flow when the prompt clearly refers to an existing object.
- Use order-first invoicing when the prompt describes a sale with customer plus lines/products/services.
- Use direct invoice creation when the prompt is explicitly invoice-centric and an order would add no value.
- Use invoice payment flow when the prompt refers to payment of an already existing invoice.
- Use credit note flow when the prompt says cancel, reverse, credit, or correct an already issued invoice.
- Use travel-expense base flow first, then add rows with dedicated commands for mileage, cost, per diem, and accommodation.
- Use voucher flows only for manual accounting corrections or bookkeeping operations that do not have a safer domain-specific endpoint.

### 4.2 Important raw API nuances the planner must know

- `GET /customer` uses raw query parameter `customerName`, not `name`. The wrapper should expose `name` and translate it.
- `POST /invoice` can work directly, but the most reliable shape is usually `invoice -> orders -> orderLines`. `Invoice.orderLines` itself is read-only in the schema.
- `TravelExpense.mileageAllowances` and `TravelExpense.accommodationAllowances` are read-only in the schema. Prefer dedicated row commands after base travel-expense creation.
- `Department.businessActivityTypeId` is read-only. It is not a normal create-time input.
- Employee privilege handling is partly split between `Employee.userType` and entitlement action endpoints. Natural-language role mapping is not fully obvious from the public docs.
- Sales-module activation uses `POST /company/salesmodules` with sales-module names such as `SMART`, `KOMPLETT`, `PROJECT`, not boolean flags like `moduleDepartmentAccounting`.

## 5. Command Catalog

The commands below are the hand-authored friendly command aliases for the wrapper. They sit on top of the full raw `operationId` command surface described later in this document.

### 5.1 Context and capability commands

- `session.who_am_i`
  - Raw Tripletex method: `GET /token/session/>whoAmI`
  - Purpose: resolve the logged-in employee and company for the current credentials.
  - Workflows: `bootstrap.inspect_context`, diagnostics, capability gating.
  - Inputs: `fields?`

- `company.sales_modules.list`
  - Raw Tripletex method: `GET /company/salesmodules`
  - Purpose: inspect which purchasable/activated sales modules are already active.
  - Workflows: `department.enable_accounting_module`, capability checks.
  - Inputs: `fields?`, `from?`, `count?`, `sorting?`

- `company.sales_modules.activate`
  - Raw Tripletex method: `POST /company/salesmodules`
  - Purpose: activate a named sales module.
  - Workflows: `department.enable_accounting_module`
  - Inputs: `name`, `cost_start_date?`
  - Notes: `name` is an enum in the spec, including values such as `SMART`, `KOMPLETT`, `PROJECT`, `API_V2`, `WAGE`, `FIXED_ASSETS_REGISTER`, `ZTL`.

### 5.2 Reference-data commands

- `currency.search`
  - Raw Tripletex method: `GET /currency`
  - Purpose: resolve currency IDs from codes such as `NOK`, `EUR`, `USD`.
  - Workflows: product create/update, invoice, voucher, travel, supplier-invoice payment.
  - Inputs: `id?`, `code?`, `fields?`, `from?`, `count?`, `sorting?`

- `vat_type.search`
  - Raw Tripletex method: `GET /ledger/vatType`
  - Purpose: resolve VAT type IDs before product, order-line, voucher, or travel-cost creation.
  - Workflows: `product.create_or_update`, `invoice.order_first`, `voucher.manual_adjustment`, `travel_expense.create_with_rows`
  - Inputs: `id?`, `number?`, `type_of_vat?`, `vat_date?`, `should_include_specification_types?`, `fields?`, `from?`, `count?`, `sorting?`

- `product_unit.search`
  - Raw Tripletex method: `GET /product/unit`
  - Purpose: resolve product-unit IDs such as pieces, hours, days.
  - Workflows: `product.create_or_update`
  - Inputs: `id?`, `name?`, `name_short?`, `common_code?`, `fields?`, `from?`, `count?`, `sorting?`

- `invoice_payment_type.search`
  - Raw Tripletex method: `GET /invoice/paymentType`
  - Purpose: resolve outgoing-invoice payment type IDs.
  - Workflows: `invoice.register_payment`, `invoice.order_first`, `invoice.direct`
  - Inputs: `id?`, `description?`, `query?`, `fields?`, `from?`, `count?`, `sorting?`

- `travel_payment_type.search`
  - Raw Tripletex method: `GET /travelExpense/paymentType`
  - Purpose: resolve travel-expense payment types for travel cost rows.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `id?`, `description?`, `show_on_employee_expenses?`, `is_inactive?`, `query?`, `fields?`, `from?`, `count?`, `sorting?`

- `travel_cost_category.search`
  - Raw Tripletex method: `GET /travelExpense/costCategory`
  - Purpose: resolve cost-category IDs before creating travel-expense cost rows.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `id?`, `description?`, `show_on_employee_expenses?`, `is_inactive?`, `query?`, `fields?`, `from?`, `count?`, `sorting?`

- `travel_rate_category.search`
  - Raw Tripletex method: `GET /travelExpense/rateCategory`
  - Purpose: resolve travel rate-category IDs for mileage, per diem, and accommodation rows.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `type?`, `name?`, `travel_report_rate_category_group_id?`, `is_valid_day_trip?`, `is_valid_accommodation?`, `is_valid_domestic?`, `requires_zone?`, `requires_overnight_accommodation?`, `date_from?`, `date_to?`, `fields?`, `from?`, `count?`, `sorting?`

- `travel_rate.search`
  - Raw Tripletex method: `GET /travelExpense/rate`
  - Purpose: resolve the actual travel rate object to use once the category is known.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `rate_category_id?`, `type?`, `is_valid_day_trip?`, `is_valid_accommodation?`, `is_valid_domestic?`, `is_valid_foreign_travel?`, `requires_zone?`, `requires_overnight_accommodation?`, `date_from?`, `date_to?`, `fields?`, `from?`, `count?`, `sorting?`

- `travel_zone.search`
  - Raw Tripletex method: `GET /travelExpense/zone`
  - Purpose: resolve travel-expense zone IDs for foreign-travel per diem cases.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `id?`, `code?`, `query?`, `date?`, `is_disabled?`, `fields?`, `from?`, `count?`, `sorting?`

- `ledger.account.search`
  - Raw Tripletex method: `GET /ledger/account`
  - Purpose: resolve account IDs and account rules before voucher or product creation.
  - Workflows: `product.create_or_update`, `voucher.manual_adjustment`, `ledger.verify_effect`
  - Inputs: `id?`, `number?`, `is_bank_account?`, `is_inactive?`, `is_applicable_for_supplier_invoice?`, `ledger_type?`, `is_balance_account?`, `saft_code?`, `fields?`, `from?`, `count?`, `sorting?`

- `ledger.voucher_type.search`
  - Raw Tripletex method: `GET /ledger/voucherType`
  - Purpose: resolve voucher-type IDs before manual voucher creation.
  - Workflows: `voucher.manual_adjustment`, `voucher.reverse_or_correct`
  - Inputs: `name?`, `fields?`, `from?`, `count?`, `sorting?`

### 5.3 Employee commands

- `employee.search`
  - Raw Tripletex method: `GET /employee`
  - Purpose: resolve employees before create/update/link operations.
  - Workflows: employee flows, department/project manager resolution, travel-expense employee resolution.
  - Inputs: `id?`, `first_name?`, `last_name?`, `employee_number?`, `email?`, `department_id?`, `has_system_access?`, `only_project_managers?`, `fields?`, `from?`, `count?`, `sorting?`

- `employee.create`
  - Raw Tripletex method: `POST /employee`
  - Purpose: create a new employee.
  - Workflows: `employee.create_basic`, `employee.create_with_access`, prerequisites for project/department/travel flows.
  - Inputs: `first_name`, `last_name`, `email?`, `phone_number_mobile?`, `department_ref?`, `user_type?`, other employee payload fields when needed.
  - Notes: `user_type` enum is `STANDARD`, `EXTENDED`, `NO_ACCESS`.

- `employee.get`
  - Raw Tripletex method: `GET /employee/{id}`
  - Purpose: fetch one employee by ID for confirmation or version-aware update.
  - Workflows: `employee.update_contact`, linking flows.
  - Inputs: `id`, `fields?`

- `employee.update`
  - Raw Tripletex method: `PUT /employee/{id}`
  - Purpose: update an employee after target resolution.
  - Workflows: `employee.update_contact`, `employee.create_with_access`
  - Inputs: `id`, employee payload including changed fields, `version?`

- `employee.entitlements.search`
  - Raw Tripletex method: `GET /employee/entitlement`
  - Purpose: inspect current entitlements for an employee.
  - Workflows: `employee.create_with_access`, diagnostics.
  - Inputs: `employee_id?`, `fields?`, `from?`, `count?`, `sorting?`

- `employee.entitlements.grant_template`
  - Raw Tripletex method: `PUT /employee/entitlement/:grantEntitlementsByTemplate`
  - Purpose: apply a coarse entitlement template to an employee.
  - Workflows: `employee.create_with_access`
  - Inputs: `employee_id`, `template`
  - Notes: allowed templates are `NONE_PRIVILEGES`, `ALL_PRIVILEGES`, `INVOICING_MANAGER`, `PERSONELL_MANAGER`, `ACCOUNTANT`, `AUDITOR`, `DEPARTMENT_LEADER`. This is one of the main commands for admin-like access, but the exact mapping from natural-language roles to templates should be validated in sandbox.

- `employee.entitlements.grant_client_template`
  - Raw Tripletex method: `PUT /employee/entitlement/:grantClientEntitlementsByTemplate`
  - Purpose: grant client-account entitlements in accountant-style setups.
  - Workflows: advanced or accountant-specific flows, not core competition bootstrap.
  - Inputs: `employee_id`, `customer_id`, `template`, `add_to_existing?`

### 5.4 Customer commands

- `customer.search`
  - Raw Tripletex method: `GET /customer`
  - Purpose: resolve a customer before create/update/link/delete.
  - Workflows: customer flows, invoice flows, project flows, voucher flows.
  - Inputs: `id?`, `customer_account_number?`, `organization_number?`, `email?`, `invoice_email?`, `name?`, `account_manager_id?`, `fields?`, `from?`, `count?`, `sorting?`
  - Notes: wrapper input `name` should map to raw query parameter `customerName`.

- `customer.create`
  - Raw Tripletex method: `POST /customer`
  - Purpose: create a customer and optional related addresses.
  - Workflows: `customer.create_or_update`, invoice flows, project flows.
  - Inputs: `name`, `organization_number?`, `email?`, `invoice_email?`, `phone_number?`, `phone_number_mobile?`, `department_ref?`, `account_manager_ref?`, `language?`, `is_supplier?`, address fields as needed.

- `customer.get`
  - Raw Tripletex method: `GET /customer/{id}`
  - Purpose: fetch one customer by ID.
  - Workflows: update, verification, linking.
  - Inputs: `id`, `fields?`

- `customer.update`
  - Raw Tripletex method: `PUT /customer/{id}`
  - Purpose: update an existing customer.
  - Workflows: `customer.create_or_update`, invoice-email update, metadata changes.
  - Inputs: `id`, customer payload, `version?`

- `customer.delete`
  - Raw Tripletex method: `DELETE /customer/{id}`
  - Purpose: delete a customer when the business task explicitly requires deletion and the object is deletable.
  - Workflows: deletion/correction flows.
  - Inputs: `id`
  - Notes: beta endpoint. Prefer non-destructive correction flows when the customer is already linked into accounting artifacts.

### 5.5 Product commands

- `product.search`
  - Raw Tripletex method: `GET /product`
  - Purpose: resolve a product before create/update/use in order lines.
  - Workflows: `product.create_or_update`, `invoice.order_first`, `invoice.direct`
  - Inputs: `number?`, `product_number?`, `name?`, `ean?`, `supplier_id?`, `vat_type_id?`, `department_id?`, `account_id?`, `fields?`, `from?`, `count?`, `sorting?`

- `product.create`
  - Raw Tripletex method: `POST /product`
  - Purpose: create a product/service record.
  - Workflows: `product.create_or_update`, invoice flows.
  - Inputs: `name`, `number?`, `description?`, `order_line_description?`, `price_excluding_vat_currency?`, `price_including_vat_currency?`, `vat_type_ref?`, `department_ref?`, `account_ref?`, `product_unit_ref?`, `currency_ref?`

- `product.get`
  - Raw Tripletex method: `GET /product/{id}`
  - Purpose: fetch one product by ID.
  - Workflows: update, verification, linking.
  - Inputs: `id`, `fields?`

- `product.update`
  - Raw Tripletex method: `PUT /product/{id}`
  - Purpose: update an existing product.
  - Workflows: `product.create_or_update`
  - Inputs: `id`, product payload, `version?`

- `product.delete`
  - Raw Tripletex method: `DELETE /product/{id}`
  - Purpose: delete a product when the task explicitly requires removal and the product is not in use.
  - Workflows: deletion/correction flows.
  - Inputs: `id`

### 5.6 Order commands

- `order.search`
  - Raw Tripletex method: `GET /order`
  - Purpose: resolve an existing order.
  - Workflows: `invoice.order_first`, correction or deletion flows.
  - Inputs: `id?`, `number?`, `customer_id?`, `order_date_from`, `order_date_to`, `is_closed?`, `fields?`, `from?`, `count?`, `sorting?`

- `order.create`
  - Raw Tripletex method: `POST /order`
  - Purpose: create an order, optionally with embedded order lines.
  - Workflows: `invoice.order_first`
  - Inputs: `customer_ref`, `order_date`, `project_ref?`, `department_ref?`, `invoice_comment?`, `currency_ref?`, `invoices_due_in?`, `invoices_due_in_type?`, `order_lines[]?`
  - Notes: `Order.orderLines` can embed new lines. This is usually the preferred way to create invoiceable sales data.

- `order.get`
  - Raw Tripletex method: `GET /order/{id}`
  - Purpose: fetch one order by ID.
  - Workflows: invoice conversion, update, verification.
  - Inputs: `id`, `fields?`

- `order.update`
  - Raw Tripletex method: `PUT /order/{id}`
  - Purpose: update an existing order.
  - Workflows: order correction before invoicing.
  - Inputs: `id`, order payload, `version?`, `update_lines_and_groups?`

- `order.delete`
  - Raw Tripletex method: `DELETE /order/{id}`
  - Purpose: delete an order if the task explicitly asks for deletion and the order has not moved too far downstream.
  - Workflows: correction flows.
  - Inputs: `id`

- `order.invoice`
  - Raw Tripletex method: `PUT /order/{id}/:invoice`
  - Purpose: convert an existing order into an invoice.
  - Workflows: `invoice.order_first`
  - Inputs: `id`, `invoice_date`, `send_to_customer?`, `send_type?`, `payment_type_id?`, `paid_amount?`, `paid_amount_account_currency?`, `create_on_account?`, `amount_on_account?`, `on_account_comment?`, `create_backorder?`, `invoice_id_if_is_credit_note?`, `override_email_address?`
  - Notes: this is one of the most important action commands in the API. Prefer it over manually reconstructing an invoice from an already-created order.

### 5.7 Invoice commands

- `invoice.search`
  - Raw Tripletex method: `GET /invoice`
  - Purpose: resolve an existing outgoing invoice.
  - Workflows: `invoice.register_payment`, `invoice.credit_note`, read-only verification.
  - Inputs: `id?`, `invoice_number?`, `kid?`, `voucher_id?`, `customer_id?`, `invoice_date_from`, `invoice_date_to`, `fields?`, `from?`, `count?`, `sorting?`
  - Notes: this search covers charged outgoing invoices.

- `invoice.create`
  - Raw Tripletex method: `POST /invoice`
  - Purpose: create an invoice directly.
  - Workflows: `invoice.direct`
  - Inputs: `invoice_date`, `invoice_due_date?`, `customer_ref`, `orders[]?`, `payment_type_id?`, `paid_amount?`, `invoice_comment?`, `comment?`
  - Notes: the reliable create shape is usually `Invoice -> orders -> orderLines`. The top-level `Invoice.orderLines` property is read-only in the schema.

- `invoice.get`
  - Raw Tripletex method: `GET /invoice/{id}`
  - Purpose: fetch one invoice by ID.
  - Workflows: `invoice.register_payment`, `invoice.credit_note`, verification.
  - Inputs: `id`, `fields?`

- `invoice.register_payment`
  - Raw Tripletex method: `PUT /invoice/{id}/:payment`
  - Purpose: register payment on an outgoing invoice.
  - Workflows: `invoice.register_payment`
  - Inputs: `id`, `payment_date`, `payment_type_id`, `paid_amount`, `paid_amount_currency?`

- `invoice.create_credit_note`
  - Raw Tripletex method: `PUT /invoice/{id}/:createCreditNote`
  - Purpose: create a credit note that nullifies an existing invoice.
  - Workflows: `invoice.credit_note`
  - Inputs: `id`, `date`, `comment?`, `credit_note_email?`, `send_to_customer?`, `send_type?`
  - Notes: this is the preferred correction path for already issued outgoing invoices.

### 5.8 Travel-expense commands

- `travel_expense.search`
  - Raw Tripletex method: `GET /travelExpense`
  - Purpose: resolve an existing travel expense before update/delete/finalize.
  - Workflows: all travel-expense flows.
  - Inputs: `employee_id?`, `department_id?`, `project_id?`, `project_manager_id?`, `departure_date_from?`, `return_date_to?`, `state?`, `fields?`, `from?`, `count?`, `sorting?`

- `travel_expense.create`
  - Raw Tripletex method: `POST /travelExpense`
  - Purpose: create the base travel-expense object.
  - Workflows: `travel_expense.create_basic`, `travel_expense.create_with_rows`
  - Inputs: `employee_ref`, `project_ref?`, `department_ref?`, `title?`, `travel_details`, `costs[]?`, `per_diem_compensations[]?`
  - Notes: use this to create the container. Add mileage, accommodation, and most detailed travel rows through dedicated commands.

- `travel_expense.get`
  - Raw Tripletex method: `GET /travelExpense/{id}`
  - Purpose: fetch one travel expense by ID.
  - Workflows: update, finalize, verification.
  - Inputs: `id`, `fields?`

- `travel_expense.update`
  - Raw Tripletex method: `PUT /travelExpense/{id}`
  - Purpose: update an existing travel expense.
  - Workflows: `travel_expense.create_basic`, correction flows.
  - Inputs: `id`, travel-expense payload, `version?`

- `travel_expense.delete`
  - Raw Tripletex method: `DELETE /travelExpense/{id}`
  - Purpose: delete a travel expense.
  - Workflows: `travel_expense.delete`
  - Inputs: `id`

- `travel_expense.cost.create`
  - Raw Tripletex method: `POST /travelExpense/cost`
  - Purpose: add one reimbursable or chargeable cost row to an existing travel expense.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `travel_expense_ref`, `cost_category_ref`, `payment_type_ref?`, `date`, `comments?`, `amount_currency_inc_vat`, `vat_type_ref?`, `is_chargeable?`

- `travel_expense.mileage.create`
  - Raw Tripletex method: `POST /travelExpense/mileageAllowance`
  - Purpose: add a mileage allowance row.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `travel_expense_ref`, `rate_type_ref`, `rate_category_ref`, `date`, `departure_location`, `destination`, `km`, `is_company_car?`

- `travel_expense.per_diem.create`
  - Raw Tripletex method: `POST /travelExpense/perDiemCompensation`
  - Purpose: add a per diem row.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `travel_expense_ref`, `rate_type_ref`, `rate_category_ref`, `country_code?`, `travel_expense_zone_id?`, `overnight_accommodation?`, `location`, `address?`, `count`, `is_deduction_for_breakfast?`, `is_deduction_for_lunch?`, `is_deduction_for_dinner?`

- `travel_expense.accommodation.create`
  - Raw Tripletex method: `POST /travelExpense/accommodationAllowance`
  - Purpose: add an accommodation allowance row.
  - Workflows: `travel_expense.create_with_rows`
  - Inputs: `travel_expense_ref`, `rate_type_ref`, `rate_category_ref`, `zone?`, `location`, `address?`, `count`

- `travel_expense.deliver`
  - Raw Tripletex method: `PUT /travelExpense/:deliver`
  - Purpose: move one or more travel expenses into delivered state.
  - Workflows: `travel_expense.finalize_to_accounting`
  - Inputs: `id` or list-like `id` query representation

- `travel_expense.approve`
  - Raw Tripletex method: `PUT /travelExpense/:approve`
  - Purpose: approve one or more travel expenses.
  - Workflows: `travel_expense.finalize_to_accounting`
  - Inputs: `id` or list-like `id` query representation, `override_approval_flow?`

- `travel_expense.create_vouchers`
  - Raw Tripletex method: `PUT /travelExpense/:createVouchers`
  - Purpose: generate vouchers from one or more travel expenses.
  - Workflows: `travel_expense.finalize_to_accounting`
  - Inputs: `id` or list-like `id` query representation, `date`

### 5.9 Project commands

- `project.search`
  - Raw Tripletex method: `GET /project`
  - Purpose: resolve a project before create/update/link/delete.
  - Workflows: project flows, order/invoice linking, travel-expense linking, voucher dimensions.
  - Inputs: `id?`, `name?`, `number?`, `project_manager_id?`, `department_id?`, `customer_id?`, `is_closed?`, `is_fixed_price?`, `start_date_from?`, `start_date_to?`, `end_date_from?`, `end_date_to?`, `fields?`, `from?`, `count?`, `sorting?`

- `project.create`
  - Raw Tripletex method: `POST /project`
  - Purpose: create a project.
  - Workflows: `project.create_for_customer`
  - Inputs: `name`, `number?`, `description?`, `project_manager_ref?`, `department_ref?`, `customer_ref?`, `start_date?`, `end_date?`, `is_internal?`, `is_offer?`, `is_fixed_price?`, `fixedprice?`, `invoice_comment?`, `invoice_receiver_email?`, `currency_ref?`

- `project.get`
  - Raw Tripletex method: `GET /project/{id}`
  - Purpose: fetch one project by ID.
  - Workflows: update, verification, linking.
  - Inputs: `id`, `fields?`

- `project.update`
  - Raw Tripletex method: `PUT /project/{id}`
  - Purpose: update a project.
  - Workflows: `project.create_for_customer`, correction flows.
  - Inputs: `id`, project payload, `version?`
  - Notes: beta endpoint.

- `project.delete`
  - Raw Tripletex method: `DELETE /project/{id}`
  - Purpose: delete a project if explicitly requested.
  - Workflows: correction flows.
  - Inputs: `id`
  - Notes: beta endpoint.

### 5.10 Department commands

- `department.search`
  - Raw Tripletex method: `GET /department`
  - Purpose: resolve a department before create/update/link/delete.
  - Workflows: department flows, employee/project/customer/product linking.
  - Inputs: `id?`, `name?`, `department_number?`, `department_manager_id?`, `fields?`, `from?`, `count?`, `sorting?`

- `department.create`
  - Raw Tripletex method: `POST /department`
  - Purpose: create a department.
  - Workflows: `department.create_with_manager`, `department.enable_accounting_module`
  - Inputs: `name`, `department_number?`, `department_manager_ref?`

- `department.get`
  - Raw Tripletex method: `GET /department/{id}`
  - Purpose: fetch one department by ID.
  - Workflows: update, verification, linking.
  - Inputs: `id`, `fields?`

- `department.update`
  - Raw Tripletex method: `PUT /department/{id}`
  - Purpose: update an existing department.
  - Workflows: `department.create_with_manager`
  - Inputs: `id`, department payload, `version?`

- `department.delete`
  - Raw Tripletex method: `DELETE /department/{id}`
  - Purpose: delete a department if explicitly requested and safe.
  - Workflows: correction flows.
  - Inputs: `id`

### 5.11 Ledger and voucher commands

- `ledger.account.create`
  - Raw Tripletex method: `POST /ledger/account`
  - Purpose: create a new ledger account.
  - Workflows: advanced accounting setup, `voucher.manual_adjustment`
  - Inputs: `number`, `name`, `description?`, `ledger_type?`, `vat_type_ref?`, `currency_ref?`, `is_bank_account?`, `bank_account_number?`, `department_ref?`

- `ledger.posting.search`
  - Raw Tripletex method: `GET /ledger/posting`
  - Purpose: search postings to verify accounting effects or find targets for correction.
  - Workflows: `ledger.verify_effect`, `voucher.reverse_or_correct`, advanced reconciliation flows.
  - Inputs: `date_from`, `date_to`, `open_postings?`, `account_id?`, `supplier_id?`, `customer_id?`, `employee_id?`, `department_id?`, `project_id?`, `product_id?`, `account_number_from?`, `account_number_to?`, `type?`, `fields?`, `from?`, `count?`, `sorting?`

- `voucher.search`
  - Raw Tripletex method: `GET /ledger/voucher`
  - Purpose: resolve vouchers before inspection, reversal, update, or deletion.
  - Workflows: `voucher.manual_adjustment`, `voucher.reverse_or_correct`, `ledger.verify_effect`
  - Inputs: `id?`, `number?`, `number_from?`, `number_to?`, `type_id?`, `date_from`, `date_to`, `fields?`, `from?`, `count?`, `sorting?`

- `voucher.create`
  - Raw Tripletex method: `POST /ledger/voucher`
  - Purpose: create a manual voucher and its postings.
  - Workflows: `voucher.manual_adjustment`
  - Inputs: `date`, `description`, `voucher_type_ref`, `postings[]`, `send_to_ledger?`
  - Notes: use only when no safer domain-specific flow exists. This is the generic bookkeeping tool.

- `voucher.get`
  - Raw Tripletex method: `GET /ledger/voucher/{id}`
  - Purpose: fetch one voucher by ID.
  - Workflows: reversal, verification, update.
  - Inputs: `id`, `fields?`

- `voucher.update`
  - Raw Tripletex method: `PUT /ledger/voucher/{id}`
  - Purpose: update an existing voucher.
  - Workflows: advanced correction flows.
  - Inputs: `id`, voucher payload, `version?`, `send_to_ledger?`
  - Notes: updating regenerates postings with `guiRow == 0` according to the spec.

- `voucher.delete`
  - Raw Tripletex method: `DELETE /ledger/voucher/{id}`
  - Purpose: delete a voucher by ID.
  - Workflows: correction flows where deletion is legal.
  - Inputs: `id`
  - Notes: prefer `voucher.reverse` when accounting history should be preserved.

- `voucher.reverse`
  - Raw Tripletex method: `PUT /ledger/voucher/{id}/:reverse`
  - Purpose: reverse a voucher.
  - Workflows: `voucher.reverse_or_correct`
  - Inputs: `id`, `date`
  - Notes: preferred correction path for vouchers and other posted accounting mistakes.

### 5.12 Supplier-invoice and pilot incoming-invoice commands

- `supplier_invoice.search`
  - Raw Tripletex method: `GET /supplierInvoice`
  - Purpose: resolve an existing supplier invoice.
  - Workflows: `supplier_invoice.register_payment`
  - Inputs: `id?`, `invoice_number?`, `kid?`, `voucher_id?`, `supplier_id?`, `invoice_date_from`, `invoice_date_to`, `fields?`, `from?`, `count?`, `sorting?`

- `supplier_invoice.get`
  - Raw Tripletex method: `GET /supplierInvoice/{id}`
  - Purpose: fetch one supplier invoice by ID.
  - Workflows: payment registration, verification.
  - Inputs: `id`, `fields?`

- `supplier_invoice.add_payment`
  - Raw Tripletex method: `POST /supplierInvoice/{invoiceId}/:addPayment`
  - Purpose: register payment on a supplier invoice.
  - Workflows: `supplier_invoice.register_payment`
  - Inputs: `invoice_id`, `payment_type`, `amount?`, `kid_or_receiver_reference?`, `bban?`, `payment_date?`, `use_default_payment_type?`, `partial_payment?`
  - Notes: the spec explicitly says this requires payment-type setup done by Tripletex.

- `incoming_invoice.get`
  - Raw Tripletex method: `GET /incomingInvoice/{voucherId}`
  - Purpose: fetch an incoming invoice by voucher ID.
  - Workflows: advanced/pilot vendor-invoice flows.
  - Inputs: `voucher_id`, `fields?`
  - Notes: restricted API for pilot customers.

- `incoming_invoice.update`
  - Raw Tripletex method: `PUT /incomingInvoice/{voucherId}`
  - Purpose: update an incoming invoice aggregate.
  - Workflows: advanced/pilot vendor-invoice flows.
  - Inputs: `voucher_id`, `send_to?`, `version?`, `invoice_header?`, `order_lines[]?`
  - Notes: restricted API for pilot customers.

- `incoming_invoice.add_payment`
  - Raw Tripletex method: `POST /incomingInvoice/{voucherId}/addPayment`
  - Purpose: create payment on an incoming invoice.
  - Workflows: advanced/pilot vendor-invoice flows.
  - Inputs: `voucher_id`, `payment_type_client_uuid?`, `amount_currency?`, `payment_date?`, `creditor_iban_or_bban?`, `kid_or_receiver_reference?`, `use_default_payment_type?`, `partial_payment?`
  - Notes: restricted API for pilot customers.

## 6. Flow Catalog

The flows below are the hand-authored business flows for common human tasks. They sit on top of the full technical flow-family model described later in this document.

### 6.1 `bootstrap.inspect_context`

- Use when:
  - a run starts
  - module activation or privilege-sensitive operations are possible
- Inputs:
  - `fields_for_identity?`
  - `include_sales_modules?`
- Steps:
  1. `session.who_am_i`
  2. optionally `company.sales_modules.list`
- Result:
  - current employee ID
  - current company ID
  - optional active sales-module inventory

### 6.2 `employee.create_basic`

- Use when:
  - prompt asks to create an employee without special access/privilege language
- Inputs:
  - `first_name`
  - `last_name`
  - `email?`
  - `phone_number_mobile?`
  - `department?`
  - `duplicate_check?`
- Steps:
  1. optional `employee.search` if duplicate risk is real
  2. resolve department if needed
  3. `employee.create`
- Result:
  - employee created

### 6.3 `employee.create_with_access`

- Use when:
  - prompt asks for admin-like, manager-like, accountant-like, or system-access behavior
- Inputs:
  - all `employee.create_basic` inputs
  - `user_type`
  - `entitlement_template?`
- Steps:
  1. optional `employee.search`
  2. `employee.create` with `user_type`
  3. optional `employee.entitlements.grant_template`
  4. optional `employee.entitlements.search` for verification
- Result:
  - employee created with intended access model
- Notes:
  - this flow has an explicit ambiguity: the public docs do not fully explain how natural-language roles such as "kontoadministrator" should map to user type plus entitlement template. Keep that mapping in one maintained policy layer.

### 6.4 `employee.update_contact`

- Use when:
  - prompt refers to an existing employee and wants contact or metadata changes
- Inputs:
  - `employee_selector`
  - `patch`
- Steps:
  1. `employee.search`
  2. `employee.get`
  3. `employee.update`
- Result:
  - employee updated

### 6.5 `customer.create_or_update`

- Use when:
  - prompt asks to create a customer or modify contact/invoice information on an existing customer
- Inputs:
  - `customer_selector?`
  - `name?`
  - `organization_number?`
  - `email?`
  - `invoice_email?`
  - `phone_number?`
  - `phone_number_mobile?`
  - `department?`
  - `account_manager?`
  - `language?`
  - `patch_mode`
- Steps:
  1. if update-like: `customer.search`
  2. if exactly one target exists: `customer.get` -> `customer.update`
  3. otherwise `customer.create`
- Result:
  - customer created or updated

### 6.6 `product.create_or_update`

- Use when:
  - prompt asks to create or modify a product/service
- Inputs:
  - `product_selector?`
  - `name?`
  - `number?`
  - `description?`
  - `price_excluding_vat_currency?`
  - `price_including_vat_currency?`
  - `vat_type`
  - `product_unit?`
  - `account?`
  - `currency?`
- Steps:
  1. if update-like: `product.search`
  2. resolve VAT type, product unit, account, currency as needed
  3. update existing or create new
- Result:
  - product created or updated

### 6.7 `invoice.order_first`

- Use when:
  - prompt describes a sale with line items or products
  - customer may need to be created first
  - Tripletex order model is a natural fit
- Inputs:
  - `customer`
  - `order_date`
  - `invoice_date`
  - `line_items[]`
  - `project?`
  - `department?`
  - `invoice_comment?`
  - `due_term?`
  - `send_options?`
  - `prepayment?`
- Steps:
  1. `customer.search` or `customer.create`
  2. resolve or create referenced products
  3. resolve VAT, units, currency, project, department as needed
  4. `order.create`
  5. `order.invoice`
- Result:
  - invoice created from order
- Notes:
  - this should usually be the default invoicing flow when products or service lines are present.

### 6.8 `invoice.direct`

- Use when:
  - prompt is explicitly invoice-centric
  - an intermediate order would add no business value
- Inputs:
  - `customer`
  - `invoice_date`
  - `invoice_due_date?`
  - `orders[]` or `invoiceable_lines`
  - `payment_spec?`
  - `invoice_comment?`
- Steps:
  1. `customer.search` or `customer.create`
  2. resolve payment type and other references as needed
  3. `invoice.create`
- Result:
  - invoice created directly
- Notes:
  - structure the payload as invoice -> orders -> orderLines rather than relying on top-level `Invoice.orderLines`.

### 6.9 `invoice.register_payment`

- Use when:
  - prompt asks to register payment on an already existing outgoing invoice
- Inputs:
  - `invoice_selector`
  - `payment_spec`
- Steps:
  1. `invoice.search`
  2. resolve payment type with `invoice_payment_type.search` if needed
  3. `invoice.register_payment`
  4. optional `invoice.get` or `ledger.posting.search` for verification
- Result:
  - payment registered

### 6.10 `invoice.credit_note`

- Use when:
  - prompt says credit, cancel, reverse, or nullify an outgoing invoice
- Inputs:
  - `invoice_selector`
  - `credit_note_date`
  - `comment?`
  - `send_options?`
- Steps:
  1. `invoice.search`
  2. `invoice.create_credit_note`
  3. optional `invoice.get`
- Result:
  - credit note created

### 6.11 `travel_expense.create_basic`

- Use when:
  - prompt asks to create a travel expense without many sub-rows
- Inputs:
  - `employee`
  - `travel_details`
  - `title?`
  - `project?`
  - `department?`
- Steps:
  1. resolve employee/project/department
  2. `travel_expense.create`
- Result:
  - base travel expense created

### 6.12 `travel_expense.create_with_rows`

- Use when:
  - prompt includes receipts, mileage, per diem, accommodation, or multiple reimbursable elements
- Inputs:
  - `employee`
  - `travel_details`
  - `title?`
  - `project?`
  - `department?`
  - `cost_rows[]?`
  - `mileage_rows[]?`
  - `per_diem_rows[]?`
  - `accommodation_rows[]?`
- Steps:
  1. `travel_expense.create`
  2. for each cost: resolve cost category/payment type/VAT -> `travel_expense.cost.create`
  3. for each mileage row: resolve rate category/rate -> `travel_expense.mileage.create`
  4. for each per diem row: resolve zone/rate category/rate -> `travel_expense.per_diem.create`
  5. for each accommodation row: resolve rate category/rate -> `travel_expense.accommodation.create`
- Result:
  - fully populated travel expense

### 6.13 `travel_expense.delete`

- Use when:
  - prompt explicitly asks to remove a travel expense
- Inputs:
  - `travel_expense_selector`
- Steps:
  1. `travel_expense.search`
  2. `travel_expense.delete`
- Result:
  - travel expense deleted

### 6.14 `travel_expense.finalize_to_accounting`

- Use when:
  - the task requires the travel expense to progress into accounting state, not just exist as a draft
- Inputs:
  - `travel_expense_selector` or `travel_expense_ids`
  - `voucher_date`
  - `override_approval_flow?`
- Steps:
  1. `travel_expense.search` if IDs are not already known
  2. `travel_expense.deliver`
  3. `travel_expense.approve`
  4. `travel_expense.create_vouchers`
- Result:
  - delivered/approved travel expense with voucher creation

### 6.15 `project.create_for_customer`

- Use when:
  - prompt asks to create a project, especially one linked to a customer
- Inputs:
  - `name`
  - `number?`
  - `customer?`
  - `project_manager?`
  - `department?`
  - `start_date?`
  - `end_date?`
  - `is_fixed_price?`
  - `fixedprice?`
  - `invoice_comment?`
  - `invoice_receiver_email?`
- Steps:
  1. resolve or create customer if needed
  2. resolve project manager and department
  3. `project.create`
- Result:
  - project created

### 6.16 `department.create_with_manager`

- Use when:
  - prompt asks to create a department and optionally assign a manager
- Inputs:
  - `name`
  - `department_number?`
  - `department_manager?`
- Steps:
  1. resolve manager if needed
  2. `department.create`
  3. optional `department.get` and `department.update` if a follow-up adjustment is needed
- Result:
  - department created

### 6.17 `department.enable_accounting_module`

- Use when:
  - the prompt explicitly asks to enable a company/module capability related to departments, projects, or product accounting
- Inputs:
  - `desired_module_name`
  - `cost_start_date?`
  - optional `department_payload?`
- Steps:
  1. `company.sales_modules.list`
  2. if needed `company.sales_modules.activate`
  3. optional `department.create`
- Result:
  - module activated, optionally followed by department creation
- Notes:
  - the public surface exposes sales-module purchase names, not a direct `moduleDepartmentAccounting=true` style endpoint. Keep the mapping from business intent to sales-module name in a separate maintained table.

### 6.18 `voucher.manual_adjustment`

- Use when:
  - a bookkeeping task requires direct voucher/posting creation
  - there is no safer domain-specific flow such as invoice payment, credit note, or travel voucher generation
- Inputs:
  - `date`
  - `description`
  - `voucher_type`
  - `postings[]`
  - `send_to_ledger?`
- Steps:
  1. resolve voucher type, accounts, VAT, currency, and dimensions
  2. `voucher.create`
  3. optional `voucher.get` or `ledger.posting.search`
- Result:
  - manual voucher created

### 6.19 `voucher.reverse_or_correct`

- Use when:
  - prompt asks to reverse or correct an accounting entry
- Inputs:
  - `voucher_selector`
  - `reverse_date?`
  - `correction_mode`
  - `correction_postings[]?`
- Steps:
  1. `voucher.search`
  2. if reversal is appropriate: `voucher.reverse`
  3. if manual correction is needed: `voucher.create`
  4. optional `ledger.posting.search` verification
- Result:
  - voucher reversed or corrected

### 6.20 `ledger.verify_effect`

- Use when:
  - the solver has to verify accounting consequences rather than mutate more data
- Inputs:
  - `voucher_selector?`
  - `posting_filters`
- Steps:
  1. optional `voucher.search`
  2. `ledger.posting.search`
- Result:
  - read-only accounting verification

### 6.21 `supplier_invoice.register_payment`

- Use when:
  - prompt asks to register payment on an existing supplier invoice
- Inputs:
  - `supplier_invoice_selector`
  - `payment_type`
  - `amount?`
  - `payment_date?`
  - `kid_or_receiver_reference?`
  - `bban?`
  - `use_default_payment_type?`
  - `partial_payment?`
- Steps:
  1. `supplier_invoice.search`
  2. `supplier_invoice.add_payment`
  3. optional `supplier_invoice.get`
- Result:
  - supplier invoice payment registered

## 7. Full OpenAPI Coverage Model

This section defines how the wrapper covers the entire OpenAPI surface, not just the hand-authored aliases in Sections 5 and 6.

### 7.1 Raw command identity

Every HTTP operation in `docs/openapi.json` is a callable low-level command.

The canonical low-level command identifier is the exact OpenAPI `operationId`.

Examples:

- `Employee_search`
- `CompanySalesmodules_post`
- `TravelExpenseCreateVouchers_createVouchers`
- `SupplierInvoiceAddPayment_addPayment`

This means:

- the hand-authored commands in Section 5 are preferred friendly aliases
- the entire remaining API is still in scope through exact `operationId`

### 7.2 Raw command inputs

For every raw low-level command:

- every path parameter is a required top-level command input
- every query parameter is a top-level command input
- if the operation has a request body, the wrapper should expose it as `body`
- if the request body is multipart, the wrapper should expose the multipart fields exactly as defined by OpenAPI
- parameter names, required flags, enums, and body schemas come directly from `docs/openapi.json`

Practical rule:

- Section 5 gives human-friendly aliases for common operations
- `docs/openapi.json` remains the source of truth for all raw per-operation parameter details

### 7.3 Technical flow-family coverage

Every raw command must belong to at least one technical flow family, even if there is no hand-authored business flow for that domain yet.

The technical flow family is derived from:

1. the path namespace
2. the method semantics
3. any action marker in the path, such as `:approve`, `:reverse`, `:payment`, `:invoice`

Recommended family classes:

- `resolve`
  search/list/filter operations
- `read`
  get-by-id and single-resource reads
- `create`
  normal POST creates
- `update`
  normal PUT updates
- `delete`
  DELETE operations
- `bulk`
  `/list` style bulk create/update/delete operations
- `action`
  state-changing action endpoints
- `approval`
  approve/reject/deliver/undeliver style operations
- `payment`
  payment registration and payment-type flows
- `invoice`
  invoice-generation and credit-note flows
- `reverse_or_correct`
  reverse, close, correction, posting-fix operations
- `attachment`
  attachment upload/delete/list operations
- `document`
  pdf/export/download operations
- `configuration`
  settings, modules, categories, entitlements, preferences, numbering, reference data
- `reporting`
  summaries, dashboards, reserve/budget/status, search-only analytical endpoints
- `import_export`
  import, export, inbox, archive, external integration operations

### 7.4 Flow-family naming rule

Technical flow-family naming should be deterministic.

Recommended format:

- `<domain>.<subdomain>.resolve`
- `<domain>.<subdomain>.read`
- `<domain>.<subdomain>.create`
- `<domain>.<subdomain>.update`
- `<domain>.<subdomain>.delete`
- `<domain>.<subdomain>.bulk`
- `<domain>.<subdomain>.<action>`

Examples:

- `/employee/employment` -> `employee.employment.resolve`, `employee.employment.create`
- `/employee/preferences/:changeLanguage` -> `employee.preferences.change_language`
- `/order/{id}/:invoice` -> `order.invoice`
- `/travelExpense/:approve` -> `travel_expense.approve`
- `/ledger/voucher/{id}/:reverse` -> `ledger.voucher.reverse`
- `/bank/reconciliation/paymentType` -> `bank.reconciliation_payment_type.resolve`
- `/purchaseOrder` -> `purchase_order.lifecycle`
- `/salary/...` -> `salary.<subdomain>.*`
- `/timesheet/...` -> `timesheet.<subdomain>.*`
- `/yearEnd/...` -> `year_end.<subdomain>.*`

### 7.5 Relationship between friendly aliases and raw commands

The wrapper therefore has two command layers:

- `friendly aliases`
  - Section 5
  - preferred when they exist
- `raw operation commands`
  - exact `operationId`
  - guaranteed full OpenAPI coverage

And two flow layers:

- `business flows`
  - Section 6
  - preferred for human business tasks
- `technical flow families`
  - auto-derived from namespace and method semantics
  - required for full OpenAPI coverage

## 8. Entire OpenAPI Scope Inventory

No top-level domain in `docs/openapi.json` is out of scope.

The full top-level inventory currently includes:

- core identity and company domains:
  - `token`
  - `company`
  - `accountingOffice`
  - `userLicense`
  - `internal`
  - `platformAgnostic`
  - `supportDashboard`
  - `accountantDashboard`
- master-data and CRM domains:
  - `customer`
  - `supplier`
  - `supplierCustomer`
  - `contact`
  - `crm`
  - `department`
  - `division`
  - `activity`
  - `event`
  - `country`
  - `municipality`
  - `pickupPoint`
  - `deliveryAddress`
- employee, time, salary, and travel domains:
  - `employee`
  - `timesheet`
  - `salary`
  - `travelExpense`
  - `transportType`
  - `pension`
- sales, project, inventory, and purchase domains:
  - `product`
  - `inventory`
  - `order`
  - `purchaseOrder`
  - `project`
  - `subscription`
  - `reminder`
- invoice and supplier-invoice domains:
  - `invoice`
  - `invoiceRemark`
  - `incomingInvoice`
  - `supplierInvoice`
- accounting and control domains:
  - `ledger`
  - `bank`
  - `balance`
  - `balanceSheet`
  - `resultbudget`
  - `yearEnd`
  - `vatReturns`
  - `vatTermSizeSettings`
  - `voucherStatus`
  - `voucherInbox`
  - `voucherMessage`
  - `voucherApprovalListElement`
  - `saft`
- documents and assets:
  - `document`
  - `documentArchive`
  - `asset`
  - `attestation`

The LLM should therefore not assume that a domain is unavailable just because it is not one of the public competition examples.

## 9. Intent Routing For The LLM

This section explains how the LLM should choose between business flows, friendly aliases, and raw `operationId` commands.

### 9.1 First choice: business flows

Use a hand-authored business flow from Section 6 when the human request is a recognizable business task.

Examples:

- "Create an employee" -> `employee.create_basic`
- "Create an employee and make them administrator" -> `employee.create_with_access`
- "Update customer invoice email" -> `customer.create_or_update`
- "Create a product" -> `product.create_or_update`
- "Create an invoice for customer X with these lines" -> `invoice.order_first` or `invoice.direct`
- "Register payment on invoice 123" -> `invoice.register_payment`
- "Issue a credit note for invoice 123" -> `invoice.credit_note`
- "Register a travel expense with mileage and hotel" -> `travel_expense.create_with_rows`
- "Delete this travel expense" -> `travel_expense.delete`
- "Create project for customer X" -> `project.create_for_customer`
- "Create department and assign manager" -> `department.create_with_manager`
- "Enable department/project accounting" -> `department.enable_accounting_module`
- "Reverse this voucher" -> `voucher.reverse_or_correct`
- "Register payment on supplier invoice" -> `supplier_invoice.register_payment`

### 9.2 Second choice: friendly command aliases

Use a hand-authored command alias from Section 5 when the request is low-level, read-only, or clearly about one specific known operation.

Examples:

- "Find employee by email" -> `employee.search`
- "Get invoice by id" -> `invoice.get`
- "List VAT types" -> `vat_type.search`
- "Find payment type called Nettbank" -> `invoice_payment_type.search`
- "Check current sales modules" -> `company.sales_modules.list`
- "Verify ledger effect" -> `ledger.posting.search` or business flow `ledger.verify_effect`

### 9.3 Third choice: raw operationId commands

If the request falls outside Sections 5 and 6, the LLM must not conclude that the API is unsupported.

Instead:

1. find the correct raw operation in `docs/openapi.json`
2. call it by exact `operationId`
3. place it inside the corresponding technical flow family

This is the rule that makes the entire OpenAPI surface usable.

Examples of request families that should often fall back to raw operation commands:

- employee employment, leave, next-of-kin, standard time, preferences
- salary and payroll operations
- timesheet operations
- purchase-order operations
- bank reconciliation operations
- inventory and warehouse operations
- year-end and tax-related operations
- result budget and balance operations
- document-archive and inbox/archive flows
- asset and pension operations

### 9.4 Routing rules by intent family

Read/list/show/search intent:

- prefer a read/search alias if it exists
- otherwise use the raw `operationId` search/read command

Create/update/delete intent in an uncommon domain:

- choose the technical flow family for that namespace
- then call the corresponding raw create/update/delete command

Action intent:

- if a friendly action alias exists, use it
- otherwise call the raw action `operationId` and place it in the matching technical flow family such as `approve`, `reject`, `send`, `invoice`, `payment`, `reverse`, `copy`, `convert`, or `close`

Configuration intent:

- categories, preferences, settings, modules, entitlements, rates, reference data, and accounting dimensions should route to `configuration` flow families

Document/download intent:

- pdf and attachment operations should route to `document` or `attachment` flow families

## 10. Final Operating Rules

- The entire `docs/openapi.json` surface is in scope.
- A hand-authored business flow is the preferred entry point when one matches the request.
- A hand-authored friendly command alias is the second choice.
- The exact raw OpenAPI `operationId` command is the guaranteed fallback for every remaining operation.
- Every raw command belongs to at least one technical flow family, even when there is no hand-authored business flow yet.
- If the OpenAPI spec changes, the raw-command and technical-flow coverage must be regenerated from the updated spec.
