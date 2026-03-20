from __future__ import annotations

import argparse
from pathlib import Path

from ngd_utils import annotations_by_image_id, category_id_list, load_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Approximate the official local hybrid score.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument("predictions", type=Path, help="Path to predictions.json")
    parser.add_argument("--split", type=Path, help="Optional split JSON created by make_splits.py")
    parser.add_argument(
        "--split-name",
        choices=("train", "val"),
        default="val",
        help="Which split to evaluate when --split is provided.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    parser.add_argument("--iou-threshold", type=float, default=0.5, help="IoU threshold for TP matching.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coco = load_json(args.annotations.resolve())
    predictions = load_json(args.predictions.resolve())
    selected_image_ids = load_selected_image_ids(coco, args.split.resolve() if args.split else None, args.split_name)
    filtered_predictions = [prediction for prediction in predictions if int(prediction["image_id"]) in selected_image_ids]
    gt_by_image = build_ground_truth(coco, selected_image_ids)

    detection_ap = evaluate_detection(filtered_predictions, gt_by_image, args.iou_threshold)
    classification_summary = evaluate_classification(
        predictions=filtered_predictions,
        gt_by_image=gt_by_image,
        category_ids=category_id_list(coco),
        iou_threshold=args.iou_threshold,
    )
    combined_score = (0.7 * detection_ap) + (0.3 * classification_summary["mAP"])

    result = {
        "image_count": len(selected_image_ids),
        "prediction_count": len(filtered_predictions),
        "detection_ap50": round(detection_ap, 6),
        "classification_map50": round(classification_summary["mAP"], 6),
        "combined_score": round(combined_score, 6),
        "evaluated_classes": classification_summary["evaluated_classes"],
        "per_class_ap50": classification_summary["per_class_ap"],
    }
    print_result(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_dumps(result), encoding="utf-8")


def load_selected_image_ids(coco: dict, split_path: Path | None, split_name: str) -> set[int]:
    if split_path is None:
        return {int(image["id"]) for image in coco.get("images", [])}
    split = load_json(split_path)
    key = f"{split_name}_image_ids"
    return {int(image_id) for image_id in split.get(key, [])}


def build_ground_truth(coco: dict, selected_image_ids: set[int]) -> dict[int, list[dict]]:
    grouped = {}
    by_image = annotations_by_image_id(coco)
    for image_id in selected_image_ids:
        grouped[image_id] = []
        for annotation in by_image.get(image_id, []):
            bbox = annotation.get("bbox", [0, 0, 0, 0])
            if len(bbox) != 4 or bbox[2] <= 0 or bbox[3] <= 0:
                continue
            grouped[image_id].append(
                {
                    "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                    "category_id": int(annotation["category_id"]),
                }
            )
    return grouped


def evaluate_detection(predictions: list[dict], gt_by_image: dict[int, list[dict]], iou_threshold: float) -> float:
    ranked_predictions = sorted(predictions, key=lambda prediction: float(prediction["score"]), reverse=True)
    total_gt = sum(len(entries) for entries in gt_by_image.values())
    matches = match_ranked_predictions(ranked_predictions, gt_by_image, iou_threshold=iou_threshold, category_id=None)
    return average_precision(matches, total_gt)


def evaluate_classification(
    predictions: list[dict],
    gt_by_image: dict[int, list[dict]],
    category_ids: list[int],
    iou_threshold: float,
) -> dict:
    gt_category_ids = {
        entry["category_id"]
        for image_entries in gt_by_image.values()
        for entry in image_entries
    }
    evaluated_category_ids = [category_id for category_id in category_ids if category_id in gt_category_ids]
    per_class_ap: dict[str, float] = {}

    for category_id in evaluated_category_ids:
        category_predictions = [
            prediction for prediction in predictions if int(prediction["category_id"]) == int(category_id)
        ]
        total_gt = sum(
            1 for image_entries in gt_by_image.values() for entry in image_entries if entry["category_id"] == category_id
        )
        matches = match_ranked_predictions(
            ranked_predictions=sorted(category_predictions, key=lambda prediction: float(prediction["score"]), reverse=True),
            gt_by_image=gt_by_image,
            iou_threshold=iou_threshold,
            category_id=category_id,
        )
        per_class_ap[str(category_id)] = round(average_precision(matches, total_gt), 6)

    map_score = sum(per_class_ap.values()) / max(1, len(per_class_ap))
    return {
        "mAP": map_score,
        "evaluated_classes": len(per_class_ap),
        "per_class_ap": per_class_ap,
    }


def match_ranked_predictions(
    ranked_predictions: list[dict],
    gt_by_image: dict[int, list[dict]],
    iou_threshold: float,
    category_id: int | None,
) -> list[bool]:
    used_gt: dict[int, set[int]] = {image_id: set() for image_id in gt_by_image}
    matches: list[bool] = []

    for prediction in ranked_predictions:
        image_id = int(prediction["image_id"])
        candidates = gt_by_image.get(image_id, [])
        pred_bbox = normalize_bbox(prediction.get("bbox"))
        if pred_bbox is None:
            matches.append(False)
            continue

        best_index = None
        best_iou = 0.0
        for index, candidate in enumerate(candidates):
            if index in used_gt[image_id]:
                continue
            if category_id is not None and candidate["category_id"] != category_id:
                continue
            overlap = iou_xywh(pred_bbox, candidate["bbox"])
            if overlap > best_iou:
                best_iou = overlap
                best_index = index

        if best_index is not None and best_iou >= iou_threshold:
            used_gt[image_id].add(best_index)
            matches.append(True)
        else:
            matches.append(False)

    return matches


def average_precision(matches: list[bool], total_gt: int) -> float:
    if total_gt <= 0:
        return 0.0

    true_positives = 0
    false_positives = 0
    precisions: list[float] = []
    recalls: list[float] = []

    for is_true_positive in matches:
        if is_true_positive:
            true_positives += 1
        else:
            false_positives += 1
        precisions.append(true_positives / max(1, true_positives + false_positives))
        recalls.append(true_positives / total_gt)

    mrec = [0.0, *recalls, 1.0]
    mpre = [0.0, *precisions, 0.0]
    for index in range(len(mpre) - 1, 0, -1):
        mpre[index - 1] = max(mpre[index - 1], mpre[index])

    area = 0.0
    for index in range(1, len(mrec)):
        area += (mrec[index] - mrec[index - 1]) * mpre[index]
    return area


def normalize_bbox(bbox) -> list[float] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    x, y, width, height = bbox
    if width <= 0 or height <= 0:
        return None
    return [float(x), float(y), float(width), float(height)]


def iou_xywh(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, aw, ah = box_a
    bx1, by1, bw, bh = box_b
    ax2 = ax1 + aw
    ay2 = ay1 + ah
    bx2 = bx1 + bw
    by2 = by1 + bh

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h
    if intersection <= 0.0:
        return 0.0

    area_a = aw * ah
    area_b = bw * bh
    union = area_a + area_b - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def print_result(result: dict) -> None:
    print(f"images={result['image_count']}")
    print(f"predictions={result['prediction_count']}")
    print(f"detection_ap50={result['detection_ap50']:.6f}")
    print(f"classification_map50={result['classification_map50']:.6f}")
    print(f"combined_score={result['combined_score']:.6f}")
    print(f"evaluated_classes={result['evaluated_classes']}")


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
