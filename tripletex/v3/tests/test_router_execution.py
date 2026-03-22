from __future__ import annotations

import unittest
from typing import Any

from app.contracts import ExecutionContext, LLMBridgeDocument
from app.raw import RawExecutor, load_raw_catalog
from app.raw.errors import RawExecutionError
from app.router import BridgeRouter


class RecordingTransport:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        *,
        context: ExecutionContext,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        multipart_data: dict[str, Any] | None = None,
        multipart_files: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params or {},
                "json_body": json_body,
                "multipart_data": multipart_data,
                "multipart_files": multipart_files,
            }
        )
        response = self.responses[(method, path)]
        if callable(response):
            return response(params or {}, json_body or {})
        return response


class RouterExecutionTests(unittest.TestCase):
    def _context(self) -> ExecutionContext:
        return ExecutionContext(
            base_url="https://example.test/v2",
            session_token="token",
            request_id="req-1",
            current_date="2026-03-21",
            timezone="Europe/Oslo",
        )

    def test_router_executes_raw_timesheet_fallback(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/timesheet/entry/>totalHours"): {"value": 123.5},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {
                    "detectedPrimaryLanguage": "nb",
                    "canonicalLanguage": "en",
                    "promptOriginal": "Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar",
                    "promptCanonical": "I cannot find my timesheet. Can you check how many hours I worked in February?",
                },
                "flatBridge": {
                    "fieldBag": {
                        "startDate": "2026-02-01",
                        "endDate": "2026-03-01",
                    },
                    "commandArguments": {
                        "TimesheetEntryTotalHours_getTotalHours": {
                            "startDate": "2026-02-01",
                            "endDate": "2026-03-01",
                        }
                    },
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "name": "timesheet.entry.read",
                            "kind": "technical_flow_family",
                        }
                    ],
                    "selectedCommands": [
                        {
                            "stepId": "step_1",
                            "command": "TimesheetEntryTotalHours_getTotalHours",
                            "commandType": "raw_operation",
                            "operationId": "TimesheetEntryTotalHours_getTotalHours",
                        }
                    ],
                    "stepOrder": ["step_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Hours returned"]},
            }
        )
        result = router.execute(bridge, self._context())
        self.assertEqual(result.traces[0].outputs, {"value": 123.5})
        self.assertEqual(transport.calls[0]["params"], {"startDate": "2026-02-01", "endDate": "2026-03-01"})

    def test_router_omits_token_owner_defaulted_raw_employee_id(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/timesheet/entry/>totalHours"): {"value": 123.5},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "commandArguments": {
                        "TimesheetEntryTotalHours_getTotalHours": {
                            "startDate": "2026-02-01",
                            "endDate": "2026-03-01",
                            "employeeId": "token_owner",
                        }
                    }
                },
                "executionPlan": {
                    "fallbackRawCommands": [
                        {
                            "stepId": "step_1",
                            "commandType": "raw_operation",
                            "operationId": "TimesheetEntryTotalHours_getTotalHours",
                        }
                    ],
                    "stepOrder": ["step_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Hours returned"]},
            }
        )

        router.execute(bridge, self._context())
        self.assertEqual(
            transport.calls[0]["params"],
            {"startDate": "2026-02-01", "endDate": "2026-03-01"},
        )

    def test_router_executes_customer_create_flow(self) -> None:
        def customer_search(params: dict[str, Any], _body: dict[str, Any]) -> Any:
            self.assertEqual(params["email"], "jason@example.org")
            self.assertEqual(params["customerName"], "Jason Bourne")
            return {"values": []}

        def customer_create(_params: dict[str, Any], body: dict[str, Any]) -> Any:
            self.assertEqual(body["name"], "Jason Bourne")
            self.assertEqual(body["email"], "jason@example.org")
            return {"value": {"id": 7, "name": body["name"], "email": body["email"]}}

        transport = RecordingTransport(
            {
                ("GET", "/customer"): customer_search,
                ("POST", "/customer"): customer_create,
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "customer.create_or_update": {
                            "name": "Jason Bourne",
                            "email": "jason@example.org",
                            "patch_mode": "auto",
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "customer.create_or_update",
                            "flowType": "business_flow",
                        }
                    ],
                    "stepOrder": ["flow_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Customer exists"]},
            }
        )
        result = router.execute(bridge, self._context())
        self.assertEqual(result.traces[0].outputs["value"]["id"], 7)
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])

    def test_router_filters_unrelated_field_bag_inputs_from_raw_command(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/timesheet/entry/>totalHours"): {"value": 160.0},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "fieldBag": {
                        "startDate": "2026-02-01",
                        "endDate": "2026-02-29",
                        "task": "ignore me",
                    },
                    "commandArguments": {
                        "TimesheetEntryTotalHours_getTotalHours": {
                            "startDate": "2026-02-01",
                            "endDate": "2026-02-29",
                        }
                    },
                },
                "executionPlan": {
                    "fallbackRawCommands": [
                        {
                            "stepId": "step_1",
                            "commandType": "raw_operation",
                            "operationId": "TimesheetEntryTotalHours_getTotalHours",
                        }
                    ],
                    "stepOrder": ["step_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Hours returned"]},
            }
        )
        router.execute(bridge, self._context())
        self.assertEqual(transport.calls[0]["params"], {"startDate": "2026-02-01", "endDate": "2026-02-29"})

    def test_router_filters_unrelated_field_bag_inputs_from_friendly_command(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/token/session/>whoAmI"): {"value": {"id": 1}},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "fieldBag": {
                        "date_range_start": "2026-02-01",
                    },
                    "commandArguments": {
                        "session.who_am_i": {
                            "fields": "id"
                        }
                    },
                },
                "executionPlan": {
                    "selectedCommands": [
                        {
                            "stepId": "step_1",
                            "commandName": "session.who_am_i",
                            "commandType": "friendly_alias",
                        }
                    ],
                    "stepOrder": ["step_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Identity returned"]},
            }
        )
        router.execute(bridge, self._context())
        self.assertEqual(transport.calls[0]["params"], {"fields": "id"})

    def test_router_rejects_explicit_raw_body_with_undeclared_fields_at_runtime(self) -> None:
        transport = RecordingTransport({})
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "commandArguments": {
                        "SalaryTransaction_post": {
                            "body": {
                                "amount": 50000,
                                "date": "2026-03-31",
                                "employeeId": 7,
                                "salaryTypeId": 3,
                            }
                        }
                    }
                },
                "executionPlan": {
                    "fallbackRawCommands": [
                        {
                            "stepId": "step_1",
                            "commandType": "raw_operation",
                            "operationId": "SalaryTransaction_post",
                        }
                    ],
                    "stepOrder": ["step_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Salary transaction created"]},
            }
        )

        with self.assertRaises(RawExecutionError) as ctx:
            router.execute(bridge, self._context())
        self.assertIn("Translated body for SalaryTransaction_post contains undeclared properties", str(ctx.exception))
        self.assertEqual(transport.calls, [])

    def test_flow_search_synthesizes_required_date_window(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/supplierInvoice"): {"values": [{"id": 99, "invoiceNumber": "SI-100"}]},
                ("POST", "/supplierInvoice/99/:addPayment"): {"value": {"id": 99, "status": "paid"}},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "supplier_invoice.register_payment": {
                            "supplier_invoice_selector": {"invoice_number": "SI-100"},
                            "payment_type": "MANUAL",
                            "amount": 1000,
                            "payment_date": "2026-03-21",
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "supplier_invoice.register_payment",
                            "flowType": "business_flow",
                        }
                    ]
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Payment registered"]},
            }
        )
        router.execute(bridge, self._context())
        search_params = transport.calls[0]["params"]
        self.assertEqual(search_params["invoiceNumber"], "SI-100")
        self.assertIn("invoiceDateFrom", search_params)
        self.assertIn("invoiceDateTo", search_params)

    def test_invoice_order_first_uses_openapi_order_line_price_fields(self) -> None:
        def customer_search(_params: dict[str, Any], _body: dict[str, Any]) -> Any:
            return {"values": [{"id": 17, "name": "ACME AS"}]}

        def order_create(_params: dict[str, Any], body: dict[str, Any]) -> Any:
            line = body["orderLines"][0]
            self.assertEqual(line["unitPriceExcludingVatCurrency"], 1000)
            self.assertNotIn("unitPriceExVat", line)
            return {"value": {"id": 55}}

        transport = RecordingTransport(
            {
                ("GET", "/customer"): customer_search,
                ("POST", "/order"): order_create,
                ("PUT", "/order/55/:invoice"): {"value": {"id": 88}},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "invoice.order_first": {
                            "customer": {"name": "ACME AS"},
                            "order_date": "2026-03-21",
                            "invoice_date": "2026-03-21",
                            "line_items": [
                                {
                                    "description": "Consulting",
                                    "count": 1,
                                    "unit_price_ex_vat": 1000,
                                }
                            ],
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "invoice.order_first",
                            "flowType": "business_flow",
                        }
                    ]
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Invoice created"]},
            }
        )

        router.execute(bridge, self._context())

    def test_wrapper_passthrough_body_rejects_nested_undeclared_order_line_fields(self) -> None:
        transport = RecordingTransport({})
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "commandArguments": {
                        "order.create": {
                            "body": {
                                "customer": {"id": 17},
                                "orderDate": "2026-03-21",
                                "orderLines": [
                                    {
                                        "description": "Consulting",
                                        "count": 1,
                                        "unitPriceExVat": 1000,
                                    }
                                ],
                            }
                        }
                    }
                },
                "executionPlan": {
                    "selectedCommands": [
                        {
                            "stepId": "cmd_1",
                            "commandName": "order.create",
                            "commandType": "friendly_alias",
                        }
                    ]
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Order created"]},
            }
        )

        with self.assertRaises(RawExecutionError) as ctx:
            router.execute(bridge, self._context())
        self.assertIn("Translated body for Order_post contains undeclared properties at body.orderLines[1]", str(ctx.exception))
        self.assertEqual(transport.calls, [])

    def test_flow_runtime_ignores_invalid_selector_ids_when_other_selector_fields_exist(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/invoice"): {"values": [{"id": 17, "invoiceNumber": "1001"}]},
                ("GET", "/invoice/paymentType"): {"values": [{"id": 5, "description": "Bank payment"}]},
                ("PUT", "/invoice/17/:payment"): {"value": {"id": 17, "status": "paid"}},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "invoice.register_payment": {
                            "invoice_selector": {"id": "not-an-int", "invoice_number": "1001"},
                            "payment_spec": {
                                "payment_date": "2026-03-21",
                                "payment_type_ref": {"id": "bad-id", "description": "Bank payment"},
                                "paid_amount": 1250.0,
                            },
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "invoice.register_payment",
                            "flowType": "business_flow",
                        }
                    ]
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Payment registered"]},
            }
        )

        router.execute(bridge, self._context())
        self.assertEqual(transport.calls[0]["path"], "/invoice")
        self.assertEqual(transport.calls[0]["params"]["invoiceNumber"], "1001")
        self.assertEqual(transport.calls[1]["path"], "/invoice/paymentType")
        self.assertEqual(transport.calls[1]["params"]["description"], "Bank payment")
        self.assertEqual(transport.calls[2]["path"], "/invoice/17/:payment")
        self.assertEqual(transport.calls[2]["params"]["paymentTypeId"], 5)
        self.assertEqual(transport.calls[2]["params"]["paidAmount"], 1250.0)

    def test_attachment_import_command_resolves_attachment_id_to_multipart_file(self) -> None:
        transport = RecordingTransport(
            {
                ("POST", "/ledger/voucher/importDocument"): {"value": {"id": 321}},
            }
        )
        context = ExecutionContext(
            base_url="https://example.test/v2",
            session_token="token",
            request_id="req-1",
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            attachments_by_id={
                "attachment_1": {
                    "filename": "invoice.pdf",
                    "content_base64": "aGVsbG8=",
                    "mime_type": "application/pdf",
                }
            },
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "sources": {
                    "attachments": [
                        {
                            "attachmentId": "attachment_1",
                            "filename": "invoice.pdf",
                            "mimeType": "application/pdf",
                        }
                    ]
                },
                "flatBridge": {
                    "commandArguments": {
                        "ledger.voucher.import_document": {
                            "attachment_id": "attachment_1",
                            "description": "Bookkeep attachment",
                        }
                    }
                },
                "executionPlan": {
                    "selectedCommands": [
                        {
                            "stepId": "step_1",
                            "commandName": "ledger.voucher.import_document",
                            "commandType": "friendly_alias",
                        }
                    ],
                    "stepOrder": ["step_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Voucher imported"]},
            }
        )
        router.execute(bridge, context)
        call = transport.calls[0]
        self.assertEqual(call["multipart_data"], {"description": "Bookkeep attachment"})
        self.assertIn("file", call["multipart_files"])

    def test_default_order_runs_flow_before_child_commands(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/customer"): {"values": []},
                ("POST", "/customer"): {"value": {"id": 7, "name": "Jason Bourne"}},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "customer.create_or_update": {
                            "name": "Jason Bourne",
                            "email": "jason@example.org",
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "customer.create_or_update",
                            "flowType": "business_flow",
                        }
                    ],
                    "selectedCommands": [
                        {
                            "stepId": "step_1",
                            "commandName": "customer.create",
                            "commandType": "friendly_alias",
                            "parentFlowStepId": "flow_1",
                        }
                    ],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Customer exists"]},
            }
        )
        router.execute(bridge, self._context())
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])

    def test_project_flow_normalizes_employee_name_selector(self) -> None:
        def customer_search(_params: dict[str, Any], _body: dict[str, Any]) -> Any:
            return {"values": [{"id": 17, "name": "ACME AS"}]}

        def employee_search(params: dict[str, Any], _body: dict[str, Any]) -> Any:
            self.assertEqual(params["firstName"], "Jane")
            self.assertEqual(params["lastName"], "Doe")
            return {"values": [{"id": 9, "firstName": "Jane", "lastName": "Doe"}]}

        def project_create(_params: dict[str, Any], body: dict[str, Any]) -> Any:
            self.assertEqual(body["customer"], {"id": 17})
            self.assertEqual(body["projectManager"], {"id": 9})
            return {"value": {"id": 55, "name": body["name"]}}

        transport = RecordingTransport(
            {
                ("GET", "/customer"): customer_search,
                ("GET", "/employee"): employee_search,
                ("POST", "/project"): project_create,
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "project.create_for_customer": {
                            "name": "Migration Project",
                            "customer": {"name": "ACME AS"},
                            "project_manager": {"name": "Jane Doe"},
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "project.create_for_customer",
                            "flowType": "business_flow",
                        }
                    ]
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Project created"]},
            }
        )
        router.execute(bridge, self._context())
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "GET", "POST"])

    def test_supplier_flow_projects_selector_onto_legal_search_inputs(self) -> None:
        def supplier_search(params: dict[str, Any], _body: dict[str, Any]) -> Any:
            self.assertEqual(params, {"organizationNumber": "913777255"})
            return {"values": []}

        def supplier_create(_params: dict[str, Any], body: dict[str, Any]) -> Any:
            self.assertEqual(body["name"], "Ironbridge Ltd")
            self.assertEqual(body["organizationNumber"], "913777255")
            return {"value": {"id": 41, "name": body["name"]}}

        transport = RecordingTransport(
            {
                ("GET", "/supplier"): supplier_search,
                ("POST", "/supplier"): supplier_create,
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "supplier.create_or_update": {
                            "name": "Ironbridge Ltd",
                            "organization_number": "913777255",
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "supplier.create_or_update",
                            "flowType": "business_flow",
                        }
                    ]
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Supplier created"]},
            }
        )
        router.execute(bridge, self._context())
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])

    def test_voucher_command_translates_nested_posting_payloads(self) -> None:
        transport = RecordingTransport(
            {
                ("POST", "/ledger/voucher"): {"value": {"id": 66}},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "commandArguments": {
                        "voucher.create": {
                            "date": "2026-03-21",
                            "description": "Manual correction",
                            "voucher_type_ref": 3,
                            "postings": [
                                {
                                    "account_ref": 1200,
                                    "amount": 1500,
                                    "date": "2026-03-21",
                                }
                            ],
                        }
                    }
                },
                "executionPlan": {
                    "selectedCommands": [
                        {
                            "stepId": "cmd_1",
                            "commandName": "voucher.create",
                            "commandType": "friendly_alias",
                        }
                    ]
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Voucher created"]},
            }
        )
        router.execute(bridge, self._context())
        body = transport.calls[0]["json_body"]
        self.assertEqual(body["voucherType"], {"id": 3})
        self.assertEqual(body["postings"][0]["account"], {"id": 1200})
        self.assertNotIn("account_ref", body["postings"][0])


if __name__ == "__main__":
    unittest.main()
