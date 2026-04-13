from __future__ import annotations

import json
import re


def extract_json_object(text: str) -> dict:
    cleaned = _strip_code_fence(text.strip())
    if not cleaned:
        raise ValueError("Empty response cannot be parsed as JSON.")
    candidates = [cleaned]
    try:
        balanced = _find_balanced_json(cleaned)
    except ValueError:
        balanced = ""
    if balanced and balanced != cleaned:
        candidates.append(balanced)
    last_error: Exception | None = None
    for candidate in candidates:
        for variant in (candidate, _repair_common_llm_json(candidate)):
            try:
                parsed = json.loads(variant)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if not isinstance(parsed, dict):
                raise ValueError("Expected a JSON object.")
            return parsed
    raise ValueError(f"Could not parse JSON object: {last_error}") from last_error


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


def _repair_common_llm_json(text: str) -> str:
    repaired = re.sub(r",(\s*[}\]])", r"\1", text)
    chars: list[str] = []
    in_string = False
    escaping = False

    for char in repaired:
        if in_string:
            if escaping:
                if char not in '"\\/bfnrtu':
                    chars.append("\\")
                chars.append(char)
                escaping = False
                continue
            if char == "\\":
                chars.append(char)
                escaping = True
                continue
            if char == '"':
                chars.append(char)
                in_string = False
                continue
            if char == "\n":
                chars.append("\\n")
                continue
            if char == "\r":
                chars.append("\\r")
                continue
            if char == "\t":
                chars.append("\\t")
                continue
            chars.append(char)
            continue
        chars.append(char)
        if char == '"':
            in_string = True

    if escaping:
        chars.append("\\")
    return "".join(chars)
