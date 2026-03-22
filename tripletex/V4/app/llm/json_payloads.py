from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(payload: str) -> str | None:
    fenced = re.search(r"```(?:json)?\s*([\[{].*[\]}])\s*```", payload, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    start_object = payload.find("{")
    start_array = payload.find("[")
    candidates = [index for index in (start_object, start_array) if index >= 0]
    if not candidates:
        return None
    start = min(candidates)
    opener = payload[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(payload)):
        char = payload[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return payload[start : index + 1]
    return None


def load_json_payload(payload: str) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        candidate = extract_json_object(payload)
        if candidate is None:
            raise
        return json.loads(candidate)
