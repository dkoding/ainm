from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.coverage_report import build_coverage_report


def main() -> None:
    print(json.dumps(build_coverage_report(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
