from __future__ import annotations

from app.benchmark.models import SlotDefinition, TaskFamilyManifest


def _slot(
    name: str,
    description: str,
    *,
    required: bool = True,
    data_type: str = "string",
    attachment_derived: bool = False,
) -> SlotDefinition:
    return SlotDefinition(
        name=name,
        description=description,
        required=required,
        data_type=data_type,
        attachment_derived=attachment_derived,
    )


TASK_FAMILY_MANIFESTS: tuple[TaskFamilyManifest, ...] = (
    TaskFamilyManifest(
        family_id="employee.create_basic",
        category="employees",
        summary="Create a basic employee record.",
        executor_name="employee.create_basic",
        preferred_flow_name="employee.create_basic",
        required_slots=(
            _slot("first_name", "Employee first name"),
            _slot("last_name", "Employee last name"),
        ),
        optional_slots=(
            _slot("email", "Employee email", required=False),
            _slot("phone_number_mobile", "Employee mobile phone", required=False),
            _slot("department", "Employee department", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="employee.create_with_access",
        category="employees",
        summary="Create an employee and grant system access.",
        executor_name="employee.create_with_access",
        preferred_flow_name="employee.create_with_access",
        required_slots=(
            _slot("first_name", "Employee first name"),
            _slot("last_name", "Employee last name"),
            _slot("user_type", "Requested access level"),
        ),
        optional_slots=(
            _slot("email", "Employee email", required=False),
            _slot("entitlement_template", "Entitlement template", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="employee.update_contact",
        category="employees",
        summary="Update employee contact information.",
        executor_name="employee.update_contact",
        preferred_flow_name="employee.update_contact",
        required_slots=(
            _slot("employee_selector", "Employee selector"),
        ),
        optional_slots=(
            _slot("patch", "Contact patch payload", required=False, data_type="object"),
        ),
    ),
    TaskFamilyManifest(
        family_id="employee.search",
        category="employees",
        summary="Find existing employee records.",
        executor_name="employee.search",
        preferred_command_names=("employee.search",),
        required_slots=(
            _slot("employee_selector", "Employee selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="customer.create_or_update",
        category="customers_products",
        summary="Create or update a customer.",
        executor_name="customer.create_or_update",
        preferred_flow_name="customer.create_or_update",
        required_slots=(
            _slot("name", "Customer name"),
        ),
        optional_slots=(
            _slot("organization_number", "Organization number", required=False),
            _slot("email", "Customer email", required=False),
            _slot("invoice_email", "Customer invoice email", required=False),
            _slot("phone_number", "Customer phone number", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="customer.search",
        category="customers_products",
        summary="Find existing customer records.",
        executor_name="customer.search",
        preferred_command_names=("customer.search",),
        required_slots=(
            _slot("customer_selector", "Customer selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="product.create_or_update",
        category="customers_products",
        summary="Create or update a product.",
        executor_name="product.create_or_update",
        preferred_flow_name="product.create_or_update",
        required_slots=(
            _slot("name", "Product name"),
        ),
        optional_slots=(
            _slot("number", "Product number", required=False),
            _slot("price_excluding_vat_currency", "Product unit price excluding VAT", required=False, data_type="number"),
            _slot("vat_type", "VAT type", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="product.search",
        category="customers_products",
        summary="Find existing product records.",
        executor_name="product.search",
        preferred_command_names=("product.search",),
        required_slots=(
            _slot("product_selector", "Product selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="invoice.direct",
        category="invoicing",
        summary="Create an invoice directly from invoice content.",
        executor_name="invoice.direct",
        preferred_flow_name="invoice.direct",
        required_slots=(
            _slot("customer", "Customer selector or create payload"),
            _slot("invoice_date", "Invoice date"),
            _slot("invoiceable_lines", "Invoiceable line items", data_type="array"),
        ),
        optional_slots=(
            _slot("invoice_due_date", "Invoice due date", required=False),
            _slot("payment_spec", "Payment specification", required=False, data_type="object"),
            _slot("invoice_comment", "Invoice comment", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="invoice.order_first",
        category="invoicing",
        summary="Create an order and invoice it.",
        executor_name="invoice.order_first",
        preferred_flow_name="invoice.order_first",
        required_slots=(
            _slot("customer", "Customer selector or create payload"),
            _slot("order_date", "Order date"),
            _slot("invoice_date", "Invoice date"),
            _slot("line_items", "Order line items", data_type="array"),
        ),
        optional_slots=(
            _slot("project", "Project selector", required=False),
            _slot("department", "Department selector", required=False),
            _slot("invoice_comment", "Invoice comment", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="invoice.register_payment",
        category="invoicing",
        summary="Register payment on a customer invoice.",
        executor_name="invoice.register_payment",
        preferred_flow_name="invoice.register_payment",
        required_slots=(
            _slot("invoice_selector", "Invoice selector"),
            _slot("payment_spec", "Payment specification", data_type="object"),
        ),
        optional_slots=(
            _slot("search_date_window", "Search date window", required=False, data_type="object"),
        ),
    ),
    TaskFamilyManifest(
        family_id="invoice.credit_note",
        category="invoicing",
        summary="Create a credit note for an invoice.",
        executor_name="invoice.credit_note",
        preferred_flow_name="invoice.credit_note",
        required_slots=(
            _slot("invoice_selector", "Invoice selector"),
        ),
        optional_slots=(
            _slot("search_date_window", "Search date window", required=False, data_type="object"),
            _slot("credit_note_date", "Credit note date", required=False),
            _slot("comment", "Credit note comment", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="invoice.search",
        category="invoicing",
        summary="Find existing customer invoices.",
        executor_name="invoice.search",
        preferred_command_names=("invoice.search",),
        required_slots=(
            _slot("invoice_selector", "Invoice selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="supplier.create_or_update",
        category="invoicing",
        summary="Create or update a supplier.",
        executor_name="supplier.create_or_update",
        preferred_flow_name="supplier.create_or_update",
        required_slots=(
            _slot("name", "Supplier name"),
        ),
        optional_slots=(
            _slot("organization_number", "Organization number", required=False),
            _slot("email", "Supplier email", required=False),
            _slot("invoice_email", "Supplier invoice email", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="supplier.search",
        category="invoicing",
        summary="Find existing supplier records.",
        executor_name="supplier.search",
        preferred_command_names=("supplier.search",),
        required_slots=(
            _slot("supplier_selector", "Supplier selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="supplier_invoice.import_from_attachment",
        category="invoicing",
        summary="Import and bookkeep a supplier invoice from an uploaded attachment.",
        executor_name="supplier_invoice.import_from_attachment",
        preferred_flow_name="supplier_invoice.import_from_attachment",
        requires_attachment=True,
        attachment_document_types=("supplier_invoice", "receipt", "unknown"),
        required_slots=(
            _slot("attachment_id", "Attachment identifier", attachment_derived=True),
        ),
        optional_slots=(
            _slot("supplier", "Supplier selector or create payload", required=False),
            _slot("description", "Import description", required=False),
            _slot("invoice_header", "Incoming invoice header patch", required=False, data_type="object"),
            _slot("order_lines", "Incoming invoice order lines", required=False, data_type="array"),
            _slot("postings", "Voucher posting corrections", required=False, data_type="array"),
        ),
    ),
    TaskFamilyManifest(
        family_id="supplier_invoice.register_payment",
        category="invoicing",
        summary="Register payment on a supplier invoice.",
        executor_name="supplier_invoice.register_payment",
        preferred_flow_name="supplier_invoice.register_payment",
        required_slots=(
            _slot("supplier_invoice_selector", "Supplier invoice selector"),
            _slot("payment_type", "Payment type"),
        ),
        optional_slots=(
            _slot("amount", "Payment amount", required=False, data_type="number"),
            _slot("payment_date", "Payment date", required=False),
            _slot("search_date_window", "Search date window", required=False, data_type="object"),
        ),
    ),
    TaskFamilyManifest(
        family_id="supplier_invoice.search",
        category="invoicing",
        summary="Find existing supplier invoices.",
        executor_name="supplier_invoice.search",
        preferred_command_names=("supplier_invoice.search",),
        required_slots=(
            _slot("supplier_invoice_selector", "Supplier invoice selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="travel_expense.create_basic",
        category="travel_expenses",
        summary="Create a basic travel expense report.",
        executor_name="travel_expense.create_basic",
        preferred_flow_name="travel_expense.create_basic",
        required_slots=(
            _slot("employee", "Employee selector"),
            _slot("travel_details", "Travel details payload", data_type="object"),
        ),
        optional_slots=(
            _slot("title", "Travel expense title", required=False),
            _slot("project", "Project selector", required=False),
            _slot("department", "Department selector", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="travel_expense.create_with_rows",
        category="travel_expenses",
        summary="Create a travel expense report with row data.",
        executor_name="travel_expense.create_with_rows",
        preferred_flow_name="travel_expense.create_with_rows",
        required_slots=(
            _slot("employee", "Employee selector"),
            _slot("travel_details", "Travel details payload", data_type="object"),
        ),
        optional_slots=(
            _slot("title", "Travel expense title", required=False),
            _slot("project", "Project selector", required=False),
            _slot("department", "Department selector", required=False),
            _slot("cost_rows", "Expense cost rows", required=False, data_type="array"),
            _slot("mileage_rows", "Mileage rows", required=False, data_type="array"),
            _slot("per_diem_rows", "Per diem rows", required=False, data_type="array"),
            _slot("accommodation_rows", "Accommodation rows", required=False, data_type="array"),
        ),
    ),
    TaskFamilyManifest(
        family_id="travel_expense.delete",
        category="travel_expenses",
        summary="Delete a travel expense report.",
        executor_name="travel_expense.delete",
        preferred_flow_name="travel_expense.delete",
        required_slots=(
            _slot("travel_expense_selector", "Travel expense selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="travel_expense.finalize_to_accounting",
        category="travel_expenses",
        summary="Finalize a travel expense into accounting.",
        executor_name="travel_expense.finalize_to_accounting",
        preferred_flow_name="travel_expense.finalize_to_accounting",
        required_slots=(
            _slot("travel_expense_selector", "Travel expense selector"),
        ),
        optional_slots=(
            _slot("voucher_date", "Voucher date", required=False),
            _slot("override_approval_flow", "Override approval flow", required=False, data_type="boolean"),
        ),
    ),
    TaskFamilyManifest(
        family_id="project.create_for_customer",
        category="projects",
        summary="Create a project for a customer.",
        executor_name="project.create_for_customer",
        preferred_flow_name="project.create_for_customer",
        required_slots=(
            _slot("name", "Project name"),
            _slot("customer", "Customer selector or create payload"),
        ),
        optional_slots=(
            _slot("project_manager", "Project manager selector", required=False),
            _slot("department", "Department selector", required=False),
            _slot("start_date", "Project start date", required=False),
            _slot("end_date", "Project end date", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="project.search",
        category="projects",
        summary="Find existing projects.",
        executor_name="project.search",
        preferred_command_names=("project.search",),
        required_slots=(
            _slot("project_selector", "Project selector"),
        ),
    ),
    TaskFamilyManifest(
        family_id="department.create_with_manager",
        category="departments",
        summary="Create a department and assign a manager.",
        executor_name="department.create_with_manager",
        preferred_flow_name="department.create_with_manager",
        required_slots=(
            _slot("name", "Department name"),
            _slot("department_manager", "Department manager selector"),
        ),
        optional_slots=(
            _slot("department_number", "Department number", required=False),
        ),
    ),
    TaskFamilyManifest(
        family_id="department.enable_accounting_module",
        category="departments",
        summary="Enable an accounting-related company module and optionally create a department.",
        executor_name="department.enable_accounting_module",
        preferred_flow_name="department.enable_accounting_module",
        required_slots=(
            _slot("desired_module_name", "Requested company sales module name"),
        ),
        optional_slots=(
            _slot("cost_start_date", "Module cost start date", required=False),
            _slot("department_payload", "Optional department payload", required=False, data_type="object"),
        ),
    ),
    TaskFamilyManifest(
        family_id="voucher.manual_adjustment",
        category="corrections",
        summary="Create a manual bookkeeping voucher.",
        executor_name="voucher.manual_adjustment",
        preferred_flow_name="voucher.manual_adjustment",
        required_slots=(
            _slot("date", "Voucher date"),
            _slot("postings", "Voucher posting lines", data_type="array"),
        ),
        optional_slots=(
            _slot("voucher_type", "Voucher type selector", required=False),
            _slot("description", "Voucher description", required=False),
            _slot("send_to_ledger", "Send voucher to ledger", required=False, data_type="boolean"),
        ),
    ),
    TaskFamilyManifest(
        family_id="voucher.reverse_or_correct",
        category="corrections",
        summary="Reverse or correct an existing voucher.",
        executor_name="voucher.reverse_or_correct",
        preferred_flow_name="voucher.reverse_or_correct",
        required_slots=(
            _slot("voucher_selector", "Voucher selector"),
            _slot("correction_mode", "Correction mode"),
        ),
        optional_slots=(
            _slot("reverse_date", "Reverse date", required=False),
            _slot("voucher_type", "Voucher type selector", required=False),
            _slot("description", "Correction description", required=False),
            _slot("correction_postings", "Correction posting lines", required=False, data_type="array"),
        ),
    ),
    TaskFamilyManifest(
        family_id="ledger.verify_effect",
        category="corrections",
        summary="Verify ledger postings or accounting effect.",
        executor_name="ledger.verify_effect",
        preferred_flow_name="ledger.verify_effect",
        required_slots=(
            _slot("posting_filters", "Posting filter payload", data_type="object"),
        ),
        optional_slots=(
            _slot("voucher_selector", "Voucher selector", required=False),
            _slot("search_date_window", "Search date window", required=False, data_type="object"),
        ),
    ),
    TaskFamilyManifest(
        family_id="timesheet.total_hours",
        category="timesheets",
        summary="Calculate total timesheet hours for a period.",
        executor_name="timesheet.total_hours",
        preferred_raw_operation_id="TimesheetEntryTotalHours_getTotalHours",
        required_slots=(
            _slot("startDate", "Start date"),
            _slot("endDate", "End date"),
        ),
    ),
)
