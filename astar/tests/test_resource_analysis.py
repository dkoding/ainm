from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from resource_analysis import collect_resource_analysis_inputs, dedupe_settlement_observations, build_resource_analysis_report
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class ResourceAnalysisTests(unittest.TestCase):
    def test_resource_analysis_joins_simulations_to_ground_truth_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            round_id = "round-1"
            history_root = root / "history"
            history_root.mkdir(parents=True)
            (history_root / "index.json").write_text(
                json.dumps(
                    {
                        "rounds": [
                            {
                                "round_id": round_id,
                                "round_number": 1,
                                "analysis_cached_seeds": [0],
                            }
                        ]
                    }
                )
            )
            (history_root / "rounds" / round_id / "public").mkdir(parents=True)
            (history_root / "rounds" / round_id / "team" / "analysis").mkdir(parents=True)
            (root / round_id / "public").mkdir(parents=True)
            (root / round_id / "team" / "simulations" / "seed_0").mkdir(parents=True)

            round_detail = {
                "round_number": 1,
                "map_width": 4,
                "map_height": 4,
                "seeds_count": 1,
                "initial_states": [
                    {
                        "grid": [
                            [11, 11, 11, 11],
                            [11, 11, 11, 11],
                            [11, 11, 11, 11],
                            [11, 11, 11, 11],
                        ],
                        "settlements": [{"x": 1, "y": 1, "has_port": False}],
                    }
                ],
            }
            (history_root / "rounds" / round_id / "public" / "round_detail.json").write_text(json.dumps(round_detail))
            (root / round_id / "public" / "round_detail.json").write_text(json.dumps(round_detail))

            ground_truth = [
                [[1, 0, 0, 0, 0, 0]] * 4,
                [
                    [1, 0, 0, 0, 0, 0],
                    [0, 1, 0, 0, 0, 0],
                    [0, 0, 1, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                ],
                [
                    [1, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 1, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                ],
                [[1, 0, 0, 0, 0, 0]] * 4,
            ]
            analysis = {
                "width": 4,
                "height": 4,
                "initial_grid": round_detail["initial_states"][0]["grid"],
                "prediction": ground_truth,
                "ground_truth": ground_truth,
                "score": 100.0,
            }
            (history_root / "rounds" / round_id / "team" / "analysis" / "seed_0.json").write_text(json.dumps(analysis))

            query_00 = {
                "request": {"round_id": round_id, "seed_index": 0, "viewport_x": 0, "viewport_y": 0, "viewport_w": 2, "viewport_h": 2},
                "response": {
                    "width": 4,
                    "height": 4,
                    "viewport": {"x": 0, "y": 0, "w": 2, "h": 2, "h": 2},
                    "grid": [[11, 11], [11, 11]],
                    "settlements": [
                        {"x": 1, "y": 1, "population": 2.0, "food": 0.8, "wealth": 0.3, "defense": 0.2, "has_port": False, "alive": True, "owner_id": 1}
                    ],
                },
            }
            query_01 = {
                "request": {"round_id": round_id, "seed_index": 0, "viewport_x": 1, "viewport_y": 1, "viewport_w": 2, "viewport_h": 2},
                "response": {
                    "width": 4,
                    "height": 4,
                    "viewport": {"x": 1, "y": 1, "w": 2, "h": 2},
                    "grid": [[11, 11], [11, 11]],
                    "settlements": [
                        {"x": 1, "y": 1, "population": 2.0, "food": 0.8, "wealth": 0.3, "defense": 0.2, "has_port": False, "alive": True, "owner_id": 1},
                        {"x": 2, "y": 1, "population": 3.0, "food": 0.4, "wealth": 0.9, "defense": 0.5, "has_port": True, "alive": True, "owner_id": 2},
                    ],
                },
            }
            (root / round_id / "team" / "simulations" / "seed_0" / "query_00.json").write_text(json.dumps(query_00))
            (root / round_id / "team" / "simulations" / "seed_0" / "query_01.json").write_text(json.dumps(query_01))

            raw_records, window_records, coverage = collect_resource_analysis_inputs(root=root)
            self.assertEqual(coverage["rounds_with_simulations"], 1)
            self.assertEqual(len(raw_records), 3)
            self.assertEqual(len(window_records), 2)
            self.assertEqual(raw_records[0]["final_class_name"], "settlement")
            self.assertEqual(raw_records[-1]["final_class_name"], "port")

            unique_records, duplicate_summary = dedupe_settlement_observations(raw_records)
            self.assertEqual(len(unique_records), 2)
            self.assertEqual(duplicate_summary["repeated_unique_settlements"], 1)

            report = build_resource_analysis_report(
                raw_settlement_records=raw_records,
                unique_settlement_records=unique_records,
                window_records=window_records,
                coverage_summary=coverage,
                duplicate_summary=duplicate_summary,
            )
            self.assertIn("resource_ranges", report)
            self.assertIn("top_findings", report)
            self.assertEqual(report["duplicate_summary"]["repeated_unique_settlements"], 1)


if __name__ == "__main__":
    unittest.main()
