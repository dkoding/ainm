from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the submission scaffold locally and validate its output.")
    parser.add_argument("submission_dir", type=Path, help="Directory containing run.py at its root.")
    parser.add_argument("--image-dir", type=Path, help="Optional directory of real test images.")
    parser.add_argument("--output-json", type=Path, help="Optional path for the generated predictions.json.")
    parser.add_argument("--fail-on-empty", action="store_true", help="Fail if the submission writes zero predictions.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    submission_dir = args.submission_dir.resolve()
    run_path = submission_dir / "run.py"
    if not run_path.exists():
        raise SystemExit(f"Missing run.py in {submission_dir}")

    with tempfile.TemporaryDirectory(prefix="ngd_smoke_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_dir = args.image_dir.resolve() if args.image_dir else temp_dir / "input"
        output_json = args.output_json.resolve() if args.output_json else temp_dir / "output" / "predictions.json"
        if args.image_dir is None:
            create_placeholder_image(input_dir / "img_00001.jpg")

        command = [
            sys.executable,
            str(run_path),
            "--input",
            str(input_dir),
            "--output",
            str(output_json),
        ]
        subprocess.run(command, check=True, cwd=submission_dir)
        predictions = json.loads(output_json.read_text(encoding="utf-8"))
        validate_predictions(predictions)

        if args.fail_on_empty and not predictions:
            raise SystemExit("Submission output is valid JSON but contains zero predictions.")

        print(f"OK: {output_json}")
        print(f"predictions={len(predictions)}")


def create_placeholder_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb0043000302020302020303030304030304"
            "050805050404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b10161011131415151515"
            "0c0f171816141812141514ffdb00430103040405040509050509140d0b0d14141414141414141414"
            "14141414141414141414141414141414141414141414141414141414141414141414141414ffc000"
            "11080001000103012200021101031101ffc4001f0000010501010101010100000000000000000102"
            "030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131"
            "410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a"
            "3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a83"
            "8485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8"
            "c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f010003010101"
            "0101010101010000000000000102030405060708090a0bffc400b511000201020404030407050404"
            "00010277000102031104052131061241510761711322328108144291a1b1c109233352f0156272d1"
            "0a162434e125f11718191a262728292a35363738393a434445464748494a535455565758595a636465"
            "666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2"
            "b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7"
            "f8f9faffda000c03010002110311003f00fdfc28a2803fffd9"
        )
    )


def validate_predictions(predictions) -> None:
    if not isinstance(predictions, list):
        raise SystemExit("predictions.json must contain a JSON array")

    for index, prediction in enumerate(predictions):
        if not isinstance(prediction, dict):
            raise SystemExit(f"Prediction {index} must be an object")
        for field in ("image_id", "category_id", "bbox", "score"):
            if field not in prediction:
                raise SystemExit(f"Prediction {index} is missing required field '{field}'")
        if not isinstance(prediction["image_id"], int):
            raise SystemExit(f"Prediction {index} has non-integer image_id")
        if not isinstance(prediction["category_id"], int):
            raise SystemExit(f"Prediction {index} has non-integer category_id")
        if not isinstance(prediction["bbox"], list) or len(prediction["bbox"]) != 4:
            raise SystemExit(f"Prediction {index} has invalid bbox")
        if any(not isinstance(value, (int, float)) for value in prediction["bbox"]):
            raise SystemExit(f"Prediction {index} has non-numeric bbox values")
        if not isinstance(prediction["score"], (int, float)):
            raise SystemExit(f"Prediction {index} has non-numeric score")


if __name__ == "__main__":
    main()
