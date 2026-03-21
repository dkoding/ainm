from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.competition_dashboard import build_competition_dashboard
from app.coverage_report import build_coverage_report


def _compile_paths() -> dict[str, Any]:
    import py_compile

    targets: list[str] = []
    for relative_dir in ("app", "tests", "scripts"):
        for path in sorted((ROOT / relative_dir).glob("*.py")):
            py_compile.compile(str(path), doraise=True)
            targets.append(str(path.relative_to(ROOT)))
    return {"passed": True, "targets": targets}


def _run_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    tests_run = _parse_tests_run(combined_output)
    return {
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "tests_run": tests_run,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _parse_tests_run(output: str) -> int | None:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Ran ") and " test" in line:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def main() -> int:
    compile_status = _compile_paths()
    tests_status = _run_tests()
    verification = {"compile": compile_status, "tests": tests_status}
    coverage_report = build_coverage_report()
    dashboard = build_competition_dashboard(
        coverage_report=coverage_report,
        verification=verification,
    )

    (ROOT / "coverage_report.json").write_text(json.dumps(coverage_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "competition_dashboard.json").write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(dashboard, indent=2, sort_keys=True))

    if not dashboard["release_gate"]["ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
