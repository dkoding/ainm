from __future__ import annotations

import unittest

from app.llm.context_catalog import ContextCatalog


class ContextCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = ContextCatalog()

    def _operation_ids(self, prompt: str, *, limit: int = 12) -> list[str]:
        context = self.catalog.build_slice(prompt)
        return [item["operationId"] for item in context["rawOperations"][:limit]]

    def test_timesheet_hours_prompt_ranks_total_hours_first(self) -> None:
        operation_ids = self._operation_ids("How many hours did I work in February?")

        self.assertGreater(len(operation_ids), 0)
        self.assertEqual(operation_ids[0], "TimesheetEntryTotalHours_getTotalHours")

    def test_supplier_invoice_payment_prompt_prefers_supplier_invoice_payment_routes(self) -> None:
        operation_ids = self._operation_ids("Pay the supplier invoice SI-100")

        self.assertGreater(len(operation_ids), 0)
        self.assertEqual(operation_ids[0], "SupplierInvoiceAddPayment_addPayment")
        self.assertIn("SupplierInvoice_search", operation_ids[:10])

    def test_norwegian_attachment_bookkeeping_prompt_surfaces_import_document(self) -> None:
        operation_ids = self._operation_ids("Bokfør den vedlagte leverandørfakturaen")

        self.assertIn("LedgerVoucherImportDocument_importDocument", operation_ids[:5])

    def test_reverse_voucher_prompt_ranks_reverse_first(self) -> None:
        operation_ids = self._operation_ids("Reverse voucher 123 from March 3 2026")

        self.assertGreater(len(operation_ids), 0)
        self.assertEqual(operation_ids[0], "LedgerVoucherReverse_reverse")

    def test_project_creation_prompt_surfaces_project_create_operation(self) -> None:
        operation_ids = self._operation_ids("Create a project for customer ACME AS with Jane Doe as project manager")

        self.assertIn("Project_post", operation_ids[:5])


if __name__ == "__main__":
    unittest.main()
