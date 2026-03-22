from __future__ import annotations

import unittest

from app.raw.input_coercion import RawInputCoercer
from app.wrapper import load_wrapper_catalog


class RawInputCoercionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.coercer = RawInputCoercer()
        self.wrapper_catalog = load_wrapper_catalog()

    def test_drops_token_owner_placeholder_for_query_params_with_token_owner_default(self) -> None:
        payload = self.coercer.normalize_operation_inputs(
            "TimesheetEntryTotalHours_getTotalHours",
            {
                "employeeId": "token_owner",
            },
        )

        self.assertNotIn("employeeId", payload)

    def test_coerces_csv_style_query_strings(self) -> None:
        payload = self.coercer.normalize_operation_inputs(
            "TimesheetMonthByMonthNumberList_getByMonthNumberList",
            {
                "employeeIds": [1, "2", {"id": "3"}],
                "monthYearList": ["2026-01", "2026-02"],
                "from": "0",
                "count": "25",
            },
        )

        self.assertEqual(payload["employeeIds"], "1,2,3")
        self.assertEqual(payload["monthYearList"], "2026-01,2026-02")
        self.assertEqual(payload["from"], 0)
        self.assertEqual(payload["count"], 25)

    def test_coerces_nested_body_types_from_openapi_schema(self) -> None:
        payload = self.coercer.normalize_operation_inputs(
            "TravelExpense_post",
            {
                "body": {
                    "employee": "7",
                    "travelDetails": {
                        "destination": "Berlin",
                        "departureDate": "2026-03-20",
                        "returnDate": "2026-03-21",
                        "isDayTrip": "true",
                    },
                }
            },
        )

        self.assertEqual(payload["body"]["employee"], {"id": 7})
        self.assertTrue(payload["body"]["travelDetails"]["isDayTrip"])

    def test_coerces_wrapper_command_inputs_via_bound_raw_schema(self) -> None:
        payload = self.coercer.normalize_command_inputs(
            self.wrapper_catalog.get_command("project.create"),
            {
                "name": "ACME Build",
                "customer_ref": "7",
                "is_internal": "false",
                "fixedprice": "99.5",
            },
        )

        self.assertEqual(payload["customer_ref"], {"id": 7})
        self.assertFalse(payload["is_internal"])
        self.assertEqual(payload["fixedprice"], 99.5)


if __name__ == "__main__":
    unittest.main()
