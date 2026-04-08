from __future__ import annotations

import json


def extract_json_object(text: str) -> dict:
    cleaned = _strip_code_fence(text.strip())
    if not cleaned:
        raise ValueError("Empty response cannot be parsed as JSON.")

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = json.loads(_find_balanced_json(cleaned))

    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed


def _strip_code_fence(text: str) -> str:
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return text


def _find_balanced_json(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON object found.")

    depth = 0
    in_string = False
    escaping = False

    for index in range(start, len(text)):
        char = text[index]
        if escaping:
            escaping = False
            continue
        if char == "\\":
            escaping = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ValueError("Unterminated JSON object.")

