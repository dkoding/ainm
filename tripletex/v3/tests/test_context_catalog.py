from __future__ import annotations

import unittest

from app.contracts import IntentDocument
from app.llm.context_catalog import ContextCatalog


class ContextCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = ContextCatalog(retrieval_backend_name="local")

    def _intent(self, **overrides: object) -> IntentDocument:
        payload: dict[str, object] = {
            "contractVersion": "tripletex.intent.v1",
            "intentSummary": "test intent",
            "taskFamilies": [],
            "targetResources": [],
            "operations": [],
            "routeHints": {
                "flowNames": [],
                "commandNames": [],
                "operationIds": [],
                "technicalFlowFamilies": [],
                "domains": [],
                "subdomains": [],
                "selectorFamilies": [],
                "payloadFamilies": [],
            },
        }
        payload.update(overrides)
        return IntentDocument.model_validate(payload)

    def _context(
        self,
        prompt: str,
        *,
        intent: IntentDocument,
        evidence: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return self.catalog.build_slice(prompt, evidence=evidence or [], intent=intent)

    def _operation_ids(self, prompt: str, *, intent: IntentDocument, evidence: list[dict[str, object]] | None = None, limit: int = 12) -> list[str]:
        context = self._context(prompt, intent=intent, evidence=evidence)
        return [item["operationId"] for item in context["rawOperations"][:limit]]

    def test_timesheet_hours_intent_ranks_total_hours_first(self) -> None:
        intent = self._intent(
            intentSummary="return total worked hours for February",
            taskFamilies=["timesheet.entry.total_hours"],
            targetResources=["timesheet"],
            operations=["get_total_hours"],
            routeHints={
                "flowNames": [],
                "commandNames": [],
                "operationIds": ["TimesheetEntryTotalHours_getTotalHours"],
                "technicalFlowFamilies": ["timesheet.entry.total_hours"],
                "domains": ["timesheet"],
                "subdomains": ["entry"],
                "selectorFamilies": [],
                "payloadFamilies": [],
            },
            needsResolution=True,
            needsMutation=False,
        )

        operation_ids = self._operation_ids("How many hours did I work in February?", intent=intent)

        self.assertGreater(len(operation_ids), 0)
        self.assertEqual(operation_ids[0], "TimesheetEntryTotalHours_getTotalHours")

    def test_supplier_invoice_payment_intent_prefers_payment_routes(self) -> None:
        intent = self._intent(
            intentSummary="register supplier invoice payment",
            taskFamilies=["supplier_invoice.payment"],
            targetResources=["supplier_invoice"],
            operations=["register_payment"],
            routeHints={
                "flowNames": ["supplier_invoice.register_payment"],
                "commandNames": ["supplier_invoice.add_payment"],
                "operationIds": ["SupplierInvoiceAddPayment_addPayment"],
                "technicalFlowFamilies": ["supplier_invoice.add_payment", "supplier_invoice.payment"],
                "domains": ["supplier_invoice"],
                "subdomains": ["root"],
                "selectorFamilies": ["supplier_invoice_selector"],
                "payloadFamilies": ["payment_spec"],
            },
            needsMutation=True,
            needsResolution=True,
        )

        context = self._context("Pay the supplier invoice SI-100", intent=intent)
        operation_ids = [item["operationId"] for item in context["rawOperations"]]

        self.assertGreater(len(operation_ids), 0)
        self.assertEqual(operation_ids[0], "SupplierInvoiceAddPayment_addPayment")
        self.assertIn("SupplierInvoice_search", operation_ids)

    def test_attachment_import_intent_surfaces_import_document(self) -> None:
        intent = self._intent(
            intentSummary="import supplier invoice from attachment",
            taskFamilies=["supplier_invoice.import_from_attachment"],
            targetResources=["supplier_invoice", "ledger"],
            operations=["import_document"],
            routeHints={
                "flowNames": [],
                "commandNames": [],
                "operationIds": [],
                "technicalFlowFamilies": ["ledger.voucher.create"],
                "domains": ["supplier_invoice", "ledger"],
                "subdomains": ["voucher"],
                "selectorFamilies": [],
                "payloadFamilies": [],
            },
            attachmentRelevant=True,
            needsMutation=True,
            needsResolution=True,
        )
        evidence = [
            {
                "attachmentId": "attachment_1",
                "filename": "invoice.pdf",
                "mimeType": "application/pdf",
                "documentType": "supplier_invoice",
                "factSummary": "Supplier invoice from ACME AS",
                "extractedFactHints": ["supplier=ACME AS"],
                "structuredFacts": {
                    "routeHints": ["supplier_invoice.import_from_attachment"],
                },
            }
        ]

        operation_ids = self._operation_ids("Bookkeep the attached supplier invoice", intent=intent, evidence=evidence)

        self.assertIn("LedgerVoucherImportDocument_importDocument", operation_ids[:5])

    def test_reverse_voucher_intent_ranks_reverse_first(self) -> None:
        intent = self._intent(
            intentSummary="reverse voucher",
            taskFamilies=["ledger.voucher.reverse"],
            targetResources=["ledger"],
            operations=["reverse_voucher"],
            routeHints={
                "flowNames": ["voucher.reverse_or_correct"],
                "commandNames": ["voucher.reverse"],
                "operationIds": ["LedgerVoucherReverse_reverse"],
                "technicalFlowFamilies": ["ledger.voucher.reverse", "ledger.voucher.reverse_or_correct"],
                "domains": ["ledger"],
                "subdomains": ["voucher"],
                "selectorFamilies": ["voucher_selector"],
                "payloadFamilies": [],
            },
            needsMutation=True,
            needsResolution=True,
        )

        operation_ids = self._operation_ids("Reverse voucher 123 from March 3 2026", intent=intent)

        self.assertGreater(len(operation_ids), 0)
        self.assertEqual(operation_ids[0], "LedgerVoucherReverse_reverse")

    def test_project_creation_intent_surfaces_project_create_operation(self) -> None:
        intent = self._intent(
            intentSummary="create project for customer",
            taskFamilies=["project.create"],
            targetResources=["project", "customer"],
            operations=["create_project"],
            routeHints={
                "flowNames": ["project.create_for_customer"],
                "commandNames": [],
                "operationIds": ["Project_post"],
                "technicalFlowFamilies": ["project.create"],
                "domains": ["project"],
                "subdomains": ["root"],
                "selectorFamilies": ["customer_selector", "employee_selector"],
                "payloadFamilies": [],
            },
            needsMutation=True,
            needsResolution=True,
        )

        operation_ids = self._operation_ids("Create a project for customer ACME AS with Jane Doe as project manager", intent=intent)

        self.assertIn("Project_post", operation_ids[:5])

    def test_context_slice_is_candidate_bounded(self) -> None:
        intent = self._intent(
            routeHints={
                "flowNames": [],
                "commandNames": [],
                "operationIds": ["TimesheetEntryTotalHours_getTotalHours"],
                "technicalFlowFamilies": ["timesheet.entry.total_hours"],
                "domains": ["timesheet"],
                "subdomains": ["entry"],
                "selectorFamilies": [],
                "payloadFamilies": [],
            },
            needsResolution=True,
        )
        context = self._context("How many hours did I work in February?", intent=intent)

        self.assertNotIn("legalCommandNames", context["apiContract"])
        self.assertNotIn("legalOperationIds", context["rawApiContract"])
        self.assertLessEqual(len(context["apiContract"]["candidateFlowNames"]), 12)
        self.assertLessEqual(len(context["apiContract"]["candidateCommandNames"]), 40)
        self.assertLessEqual(len(context["rawApiContract"]["candidateOperationIds"]), 120)

    def test_project_intent_keeps_relevant_flow_and_raw_contracts(self) -> None:
        intent = self._intent(
            routeHints={
                "flowNames": ["project.create_for_customer"],
                "commandNames": [],
                "operationIds": ["Project_post"],
                "technicalFlowFamilies": ["project.create"],
                "domains": ["project"],
                "subdomains": ["root"],
                "selectorFamilies": ["customer_selector", "employee_selector"],
                "payloadFamilies": [],
            },
            needsMutation=True,
            needsResolution=True,
        )
        context = self._context("Create a project for customer ACME AS with Jane Doe as project manager", intent=intent)

        self.assertIn("project.create_for_customer", context["apiContract"]["candidateFlowNames"])
        self.assertNotIn("project.create", context["apiContract"]["candidateCommandNames"])
        self.assertIn("Project_post", context["rawApiContract"]["candidateOperationIds"])

    def test_shadowed_direct_mutation_command_is_removed_when_business_flow_exists(self) -> None:
        intent = self._intent(
            routeHints={
                "flowNames": ["product.create_or_update"],
                "commandNames": [],
                "operationIds": [],
                "technicalFlowFamilies": ["product.resolve"],
                "domains": ["product"],
                "subdomains": ["root"],
                "selectorFamilies": ["ledger_account_selector", "vat_type_selector"],
                "payloadFamilies": [],
            },
            needsMutation=True,
            needsResolution=True,
        )
        context = self._context("Create product ACME Webdesign with account 3000 and VAT 0", intent=intent)

        self.assertIn("product.create_or_update", context["apiContract"]["candidateFlowNames"])
        self.assertNotIn("product.create", context["apiContract"]["candidateCommandNames"])

    def test_invoice_payment_intent_keeps_payment_flow_and_raw_operation(self) -> None:
        intent = self._intent(
            routeHints={
                "flowNames": ["invoice.register_payment"],
                "commandNames": [],
                "operationIds": ["InvoicePayment_payment"],
                "technicalFlowFamilies": ["invoice.payment"],
                "domains": ["invoice"],
                "subdomains": ["root"],
                "selectorFamilies": ["invoice_selector"],
                "payloadFamilies": ["payment_spec"],
            },
            needsMutation=True,
            needsResolution=True,
        )
        context = self._context("Register payment for invoice 1001", intent=intent)

        self.assertIn("invoice.register_payment", context["apiContract"]["candidateFlowNames"])
        self.assertNotIn("invoice.register_payment", context["apiContract"]["candidateCommandNames"])
        self.assertIn("InvoicePayment_payment", context["rawApiContract"]["candidateOperationIds"])


if __name__ == "__main__":
    unittest.main()
