from __future__ import annotations

from typing import Callable

from autopapers.json_utils import extract_json_object
from autopapers.llm.minimax import MiniMaxError
from autopapers.llm.fallbacks import fallback_plan, normalize_paper_refs, resolve_request_intent
from autopapers.llm.prompt_specs import PLAN_PROMPT
from autopapers.llm.response_formats import json_user_prompt_checklist, plan_response_format
from autopapers.common.text_normalization import normalize_whitespace, truncate_text
from autopapers.models import RequestPlan


def plan_request(
    planner,
    user_request: str,
    library_snapshot: str,
    max_results: int | None = None,
    *,
    notice_callback: Callable[[str], None] | None = None,
    debug_callback: Callable[[str], None] | None = None,
) -> RequestPlan:
    requested_limit = max_results or planner.default_max_results
    response_format = plan_response_format()
    prompt = (
        f"用户请求:\n{user_request.strip()}\n\n"
        f"当前本地论文库概览:\n{truncate_text(library_snapshot, 3000)}\n\n"
        f"默认返回条数: {requested_limit}\n"
        f"{json_user_prompt_checklist(response_format)}"
    )
    raw = ""
    try:
        raw = planner.client.chat_text(
            [{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=800,
            retry_context="任务规划",
            notice_callback=notice_callback,
            response_format=response_format,
        )
        data = extract_json_object(raw)
    except MiniMaxError:
        if notice_callback is not None:
            notice_callback("任务规划连续失败，已切换到本地回退策略。")
        return fallback_plan(user_request, requested_limit)
    except (ValueError, TypeError) as exc:
        planner._emit_raw_response_debug(
            debug_callback,
            retry_context="任务规划",
            parse_error=exc,
            raw_response=raw,
        )
        if notice_callback is not None:
            notice_callback("任务规划响应解析失败，已切换到本地回退策略。")
        return fallback_plan(user_request, requested_limit)

    paper_refs = normalize_paper_refs(data.get("paper_refs", []), user_request=user_request, intent=str(data.get("intent", "")))
    resolved_intent = resolve_request_intent(str(data.get("intent", "")), user_request=user_request, paper_refs=paper_refs)
    search_query = "" if resolved_intent == "explain_paper" else normalize_whitespace(str(data.get("search_query", user_request)))
    return RequestPlan(
        intent=resolved_intent,
        user_goal=normalize_whitespace(str(data.get("user_goal", user_request))),
        search_query=search_query,
        paper_refs=paper_refs,
        max_results=max(1, min(int(data.get("max_results", requested_limit)), 20)),
        reuse_local=bool(data.get("reuse_local", True)),
        rationale=normalize_whitespace(str(data.get("rationale", ""))),
    )
