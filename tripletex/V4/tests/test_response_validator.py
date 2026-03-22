from __future__ import annotations

import unittest

from app.llm.response_validator import ResponseValidator
from app.raw.errors import RawExecutionError


class ResponseValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = ResponseValidator()

    def test_rejects_raw_operation_inside_selected_commands(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "hours", "promptCanonical": "hours"},
                    "understanding": {"objective": "hours"},
                    "executionPlan": {
                        "selectedCommands": [
                            {
                                "stepId": "step_1",
                                "commandName": "TimesheetEntryTotalHours_getTotalHours",
                                "commandType": "friendly_alias",
                            }
                        ]
                    },
                    "validation": {"isExecutable": True},
                }
            )
        self.assertIn("must go in fallbackRawCommands", str(ctx.exception))

    def test_rejects_human_string_for_ref_input(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "create voucher", "promptCanonical": "create voucher"},
                    "understanding": {"objective": "create voucher"},
                    "flatBridge": {
                        "commandArguments": {
                            "voucher.create": {
                                "date": "2026-03-21",
                                "description": "Manual booking",
                                "voucher_type_ref": "Inngående faktura",
                                "postings": [],
                            }
                        }
                    },
                    "executionPlan": {
                        "selectedCommands": [
                            {
                                "stepId": "step_1",
                                "commandName": "voucher.create",
                                "commandType": "friendly_alias",
                            }
                        ]
                    },
                    "validation": {"isExecutable": True},
                }
            )
        self.assertIn("body.voucherType", str(ctx.exception))

    def test_attachment_accounting_without_attachments_is_demoted_to_blocked_plan(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "bookkeep", "promptCanonical": "bookkeep"},
                "understanding": {"objective": "bookkeep"},
                "flatBridge": {
                    "commandArguments": {
                        "ledger.voucher.import_document": {
                            "attachment_id": "attachment_1",
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
                    ]
                },
                "validation": {"isExecutable": True},
            }
        )
        self.assertFalse(bridge.validation.isExecutable)
        self.assertIn("attachment-dependent", bridge.validation.blockingIssues[0])

    def test_normalizes_structured_blocking_issue_objects_to_strings(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "bookkeep", "promptCanonical": "bookkeep"},
                "understanding": {"objective": "bookkeep"},
                "validation": {
                    "isExecutable": False,
                    "blockingIssues": [
                        {
                            "level": "error",
                            "code": "missing_required_input",
                            "message": "The prompt asks to bookkeep an attachment, but no attachment was provided.",
                            "blockingInputs": ["attachment_id"],
                        }
                    ],
                },
            }
        )
        self.assertEqual(
            bridge.validation.blockingIssues,
            ["The prompt asks to bookkeep an attachment, but no attachment was provided."],
        )

    def test_accepts_json_inside_markdown_fence(self) -> None:
        bridge = self.validator.validate(
            """```json
            {"contractVersion":"tripletex.llm_bridge.v1","language":{"promptOriginal":"hours","promptCanonical":"hours"},"understanding":{"objective":"hours"},"validation":{"isExecutable":false}}
            ```"""
        )
        self.assertEqual(bridge.contractVersion, "tripletex.llm_bridge.v1")

    def test_canonicalizes_known_tripletex_contract_alias(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.api_contract.v1",
                "language": {"promptOriginal": "hours", "promptCanonical": "hours"},
                "understanding": {"objective": "hours"},
                "validation": {"isExecutable": False},
            }
        )
        self.assertEqual(bridge.contractVersion, "tripletex.llm_bridge.v1")

    def test_injects_request_attachments_from_defaults_when_model_omits_sources_attachments(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "bookkeep", "promptCanonical": "bookkeep"},
                "understanding": {"objective": "bookkeep"},
                "flatBridge": {
                    "flowArguments": {
                        "supplier_invoice.import_from_attachment": {
                            "attachment_id": "attachment_1",
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "supplier_invoice.import_from_attachment",
                            "flowType": "business_flow",
                        }
                    ]
                },
                "validation": {"isExecutable": True},
                "__tripletex_defaults": {
                    "attachments": [
                        {
                            "attachmentId": "attachment_1",
                            "filename": "invoice.txt",
                            "mimeType": "text/plain",
                            "extractedText": "Invoice 1001",
                        }
                    ]
                },
            }
        )
        self.assertEqual(bridge.sources.attachments[0]["attachmentId"], "attachment_1")
        self.assertTrue(bridge.validation.isExecutable)

    def test_autofills_missing_step_id_and_normalizes_employee_name_selector(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "find Jane Doe", "promptCanonical": "find Jane Doe"},
                "understanding": {"objective": "find Jane Doe"},
                "flatBridge": {
                    "commandArguments": {
                        "employee.search": {
                            "name": "Jane Doe",
                        }
                    }
                },
                "executionPlan": {
                    "selectedCommands": [
                        {
                            "commandName": "employee.search",
                            "commandType": "friendly_alias",
                        }
                    ]
                },
                "validation": {"isExecutable": True},
                "completion": {"completionSignals": ["Employee resolved"]},
            }
        )
        self.assertEqual(bridge.executionPlan.selectedCommands[0].stepId, "cmd_1")
        self.assertEqual(
            bridge.flatBridge.commandArguments["employee.search"],
            {"first_name": "Jane", "last_name": "Doe"},
        )

    def test_rejects_incomplete_travel_details_payload(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "travel", "promptCanonical": "travel"},
                    "understanding": {"objective": "travel"},
                    "flatBridge": {
                        "flowArguments": {
                            "travel_expense.create_with_rows": {
                                "employee": {"email": "jane@example.org"},
                                "travel_details": {"destination": "Berlin"},
                            }
                        }
                    },
                    "executionPlan": {
                        "selectedFlows": [
                            {
                                "flowName": "travel_expense.create_with_rows",
                                "flowType": "business_flow",
                            }
                        ]
                    },
                    "validation": {"isExecutable": True},
                    "completion": {"completionSignals": ["Travel expense created"]},
                }
            )
        self.assertIn("travel_details omitted required fields", str(ctx.exception))

    def test_allows_resolvable_nested_payment_type_ref_for_invoice_flow(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "pay invoice", "promptCanonical": "pay invoice"},
                "understanding": {"objective": "register invoice payment"},
                "flatBridge": {
                    "flowArguments": {
                        "invoice.register_payment": {
                            "invoice_selector": {"invoice_number": "1001"},
                            "payment_spec": {
                                "payment_date": "2026-03-21",
                                "payment_type_ref": {"description": "Bank payment"},
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
                "validation": {"isExecutable": True},
                "completion": {"completionSignals": ["Invoice paid"]},
            }
        )

        self.assertEqual(
            bridge.flatBridge.flowArguments["invoice.register_payment"]["payment_spec"]["payment_type_ref"],
            {"description": "Bank payment"},
        )

    def test_drops_invalid_nested_ref_id_when_selector_fields_exist(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "pay invoice", "promptCanonical": "pay invoice"},
                "understanding": {"objective": "register invoice payment"},
                "flatBridge": {
                    "flowArguments": {
                        "invoice.register_payment": {
                            "invoice_selector": {"invoice_number": "1001"},
                            "payment_spec": {
                                "payment_date": "2026-03-21",
                                "payment_type_ref": {"id": "bank", "description": "Bank payment"},
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
                "validation": {"isExecutable": True},
                "completion": {"completionSignals": ["Invoice paid"]},
            }
        )

        self.assertEqual(
            bridge.flatBridge.flowArguments["invoice.register_payment"]["payment_spec"]["payment_type_ref"],
            {"description": "Bank payment"},
        )

    def test_drops_invalid_selector_id_when_other_selector_fields_exist(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "pay invoice", "promptCanonical": "pay invoice"},
                "understanding": {"objective": "register invoice payment"},
                "flatBridge": {
                    "flowArguments": {
                        "invoice.register_payment": {
                            "invoice_selector": {"id": "not-an-int", "invoice_number": "1001"},
                            "payment_spec": {
                                "payment_date": "2026-03-21",
                                "payment_type_ref": {"description": "Bank payment"},
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
                "validation": {"isExecutable": True},
                "completion": {"completionSignals": ["Invoice paid"]},
            }
        )

        self.assertEqual(
            bridge.flatBridge.flowArguments["invoice.register_payment"]["invoice_selector"],
            {"invoice_number": "1001"},
        )

    def test_allows_resolvable_nested_vat_type_ref_for_travel_flow(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "travel expense", "promptCanonical": "travel expense"},
                "understanding": {"objective": "register travel expense"},
                "flatBridge": {
                    "flowArguments": {
                        "travel_expense.create_with_rows": {
                            "employee": {"email": "jane@example.org"},
                            "travel_details": {
                                "departure_date": "2026-03-20",
                                "return_date": "2026-03-21",
                                "destination": "Berlin",
                            },
                            "cost_rows": [
                                {
                                    "cost_category_ref": {"description": "Taxi"},
                                    "payment_type_ref": {"description": "Private card"},
                                    "date": "2026-03-21",
                                    "amount_currency_inc_vat": 420.0,
                                    "vat_type_ref": {"number": "3"},
                                }
                            ],
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "travel_expense.create_with_rows",
                            "flowType": "business_flow",
                        }
                    ]
                },
                "validation": {"isExecutable": True},
                "completion": {"completionSignals": ["Travel expense created"]},
            }
        )

        self.assertEqual(
            bridge.flatBridge.flowArguments["travel_expense.create_with_rows"]["cost_rows"][0]["vat_type_ref"],
            {"number": "3"},
        )

    def test_rejects_undeclared_fields_inside_explicit_raw_body(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "salary", "promptCanonical": "salary"},
                    "understanding": {"objective": "create salary transaction"},
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
                        ]
                    },
                    "validation": {"isExecutable": True},
                    "completion": {"completionSignals": ["Salary transaction created"]},
                }
            )
        self.assertIn("Explicit body for SalaryTransaction_post contains undeclared properties", str(ctx.exception))

    def test_rejects_wrapper_payload_fields_not_writable_in_bound_openapi_schema(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "create order", "promptCanonical": "create order"},
                    "understanding": {"objective": "create order"},
                    "flatBridge": {
                        "commandArguments": {
                            "order.create": {
                                "customer_ref": 17,
                                "order_date": "2026-03-21",
                                "order_lines": [
                                    {
                                        "description": "Consulting",
                                        "count": 1,
                                        "currency_ref": {"id": 2},
                                    }
                                ],
                            }
                        }
                    },
                    "executionPlan": {
                        "selectedCommands": [
                            {
                                "stepId": "step_1",
                                "commandName": "order.create",
                                "commandType": "friendly_alias",
                            }
                        ]
                    },
                    "validation": {"isExecutable": True},
                    "completion": {"completionSignals": ["Order created"]},
                }
            )
        self.assertIn("Translated body for Order_post contains undeclared properties at body.orderLines[1]", str(ctx.exception))

    def test_omits_token_owner_placeholder_for_raw_fields_with_token_owner_default(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "hours", "promptCanonical": "hours"},
                "understanding": {"objective": "hours"},
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
                    ]
                },
                "validation": {"isExecutable": True},
                "completion": {"completionSignals": ["Hours returned"]},
            }
        )

        self.assertNotIn("employeeId", bridge.flatBridge.commandArguments["TimesheetEntryTotalHours_getTotalHours"])

    def test_rejects_direct_mutation_command_when_business_flow_exists(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "create project", "promptCanonical": "create project"},
                    "understanding": {"objective": "create project"},
                    "flatBridge": {
                        "commandArguments": {
                            "project.create": {
                                "name": "ACME Build",
                                "customer_ref": "7",
                                "is_internal": "false",
                                "fixedprice": "99.5",
                            }
                        }
                    },
                    "executionPlan": {
                        "selectedCommands": [
                            {
                                "stepId": "step_1",
                                "commandName": "project.create",
                                "commandType": "friendly_alias",
                            }
                        ]
                    },
                    "validation": {"isExecutable": True},
                    "completion": {"completionSignals": ["Project created"]},
                }
            )
        self.assertIn("direct mutation command project.create", str(ctx.exception))
        self.assertIn("project.create_for_customer", str(ctx.exception))

    def test_rejects_step_output_placeholder_in_nested_ref(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "create voucher", "promptCanonical": "create voucher"},
                    "understanding": {"objective": "create voucher"},
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
                                        "project_ref": "step_1.project.id",
                                    }
                                ],
                            }
                        }
                    },
                    "executionPlan": {
                        "selectedCommands": [
                            {
                                "stepId": "step_1",
                                "commandName": "voucher.create",
                                "commandType": "friendly_alias",
                            }
                        ]
                    },
                    "validation": {"isExecutable": True},
                    "completion": {"completionSignals": ["Voucher created"]},
                }
            )
        self.assertIn("step-output placeholders", str(ctx.exception))

    def test_normalizes_sources_prompt_object_to_plain_string(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "sources": {
                    "prompt": {
                        "text": "Create a reminder invoice and register partial payment",
                        "normalizedDate": "2026-03-22",
                        "timezone": "Europe/Oslo",
                    }
                },
                "understanding": {"objective": {"text": "Create a reminder invoice and register partial payment"}},
                "validation": {"isExecutable": False},
            }
        )
        self.assertEqual(bridge.sources.prompt, "Create a reminder invoice and register partial payment")
        self.assertEqual(bridge.understanding.objective, "Create a reminder invoice and register partial payment")

    def test_allows_supported_step_output_binding_for_later_flow(self) -> None:
        bridge = self.validator.validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {"promptOriginal": "create customer and project", "promptCanonical": "create customer and project"},
                "understanding": {"objective": "create customer and project"},
                "flatBridge": {
                    "flowArguments": {
                        "customer.create_or_update": {
                            "name": "ACME AS",
                            "patch_mode": "auto",
                        },
                        "project.create_for_customer": {
                            "name": "ACME Build",
                            "customer": {"$fromStep": "step_1", "path": "value.id"},
                        },
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "step_1",
                            "flowName": "customer.create_or_update",
                            "flowType": "business_flow",
                        },
                        {
                            "stepId": "step_2",
                            "flowName": "project.create_for_customer",
                            "flowType": "business_flow",
                        },
                    ],
                    "stepOrder": ["step_1", "step_2"],
                },
                "validation": {"isExecutable": True},
                "completion": {"completionSignals": ["Customer and project created"]},
            }
        )
        self.assertEqual(
            bridge.flatBridge.flowArguments["project.create_for_customer"]["customer"],
            {"$fromStep": "step_1", "path": "value.id"},
        )

    def test_rejects_future_step_output_binding(self) -> None:
        with self.assertRaises(RawExecutionError) as ctx:
            self.validator.validate(
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {"promptOriginal": "create customer and project", "promptCanonical": "create customer and project"},
                    "understanding": {"objective": "create customer and project"},
                    "flatBridge": {
                        "flowArguments": {
                        "project.create_for_customer": {
                            "name": "ACME Build",
                            "customer": {"$fromStep": "step_2", "path": "value.id"},
                        },
                        "customer.create_or_update": {
                            "name": "ACME AS",
                            "patch_mode": "auto",
                        },
                    }
                },
                    "executionPlan": {
                        "selectedFlows": [
                            {
                                "stepId": "step_1",
                                "flowName": "project.create_for_customer",
                                "flowType": "business_flow",
                            },
                            {
                                "stepId": "step_2",
                                "flowName": "customer.create_or_update",
                                "flowType": "business_flow",
                            },
                        ],
                        "stepOrder": ["step_1", "step_2"],
                    },
                    "validation": {"isExecutable": True},
                    "completion": {"completionSignals": ["Customer and project created"]},
                }
            )
        self.assertIn("must point only to earlier executed steps", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
