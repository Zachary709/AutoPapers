from __future__ import annotations

import re


def json_string_schema() -> dict[str, object]:
    return {"type": "string"}


def json_string_array_schema() -> dict[str, object]:
    return {"type": "array", "items": json_string_schema()}


def json_object_response_format(name: str, properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties.keys()),
                "additionalProperties": False,
            },
        },
    }


def plan_response_format() -> dict[str, object]:
    return json_object_response_format(
        "request_plan",
        {
            "intent": {"type": "string", "enum": ["explain_paper", "discover_papers"]},
            "user_goal": json_string_schema(),
            "search_query": json_string_schema(),
            "paper_refs": json_string_array_schema(),
            "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            "reuse_local": {"type": "boolean"},
            "rationale": json_string_schema(),
        },
    )


def abstract_translation_response_format() -> dict[str, object]:
    return json_object_response_format("abstract_translation", {"abstract_zh": json_string_schema()})


def metadata_response_format() -> dict[str, object]:
    return json_object_response_format(
        "paper_metadata_digest",
        {
            "major_topic": json_string_schema(),
            "minor_topic": json_string_schema(),
            "keywords": json_string_array_schema(),
        },
    )


def overview_response_format() -> dict[str, object]:
    return json_object_response_format(
        "paper_overview_digest",
        {
            "one_sentence_takeaway": json_string_schema(),
            "problem": json_string_schema(),
            "background": json_string_schema(),
            "relevance": json_string_schema(),
        },
    )


def method_response_format() -> dict[str, object]:
    return json_object_response_format("paper_method_digest", {"method": json_string_schema()})


def experiment_response_format() -> dict[str, object]:
    return json_object_response_format(
        "paper_experiment_digest",
        {
            "experiment_setup": json_string_schema(),
            "findings": json_string_array_schema(),
            "limitations": json_string_array_schema(),
            "improvement_ideas": json_string_array_schema(),
        },
    )


def full_digest_response_format() -> dict[str, object]:
    return json_object_response_format(
        "paper_full_digest",
        {
            "abstract_zh": json_string_schema(),
            "one_sentence_takeaway": json_string_schema(),
            "problem": json_string_schema(),
            "background": json_string_schema(),
            "method": json_string_schema(),
            "experiment_setup": json_string_schema(),
            "findings": json_string_array_schema(),
            "limitations": json_string_array_schema(),
            "relevance": json_string_schema(),
            "improvement_ideas": json_string_array_schema(),
        },
    )


def single_field_response_format(field_name: str, value: object) -> dict[str, object]:
    field_schema = json_string_array_schema() if isinstance(value, list) else json_string_schema()
    schema_name = re.sub(r"[^a-z0-9_]+", "_", field_name.strip().lower()).strip("_") or "field"
    return json_object_response_format(f"paper_field_{schema_name}", {field_name: field_schema})


def response_format_field_names(response_format: dict[str, object]) -> list[str]:
    schema = ((response_format.get("json_schema") or {}).get("schema") or {})
    properties = schema.get("properties") or {}
    if isinstance(properties, dict):
        return list(properties.keys())
    return []


def json_user_prompt_checklist(response_format: dict[str, object]) -> str:
    fields = ", ".join(response_format_field_names(response_format))
    return (
        "\n输出检查清单（必须全部满足）：\n"
        "- 只返回一个 JSON 对象。\n"
        f"- 只能包含这些字段：{fields}。\n"
        "- 不要输出解释、标题、Markdown、代码块、前后缀文字。\n"
        "- 若字段没有内容，字符串返回 \"\"，列表返回 []。\n"
    )
