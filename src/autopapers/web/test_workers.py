from __future__ import annotations

import os
import time


def job_test_worker(request: str, refresh_existing: bool, max_results: int | None, reporter) -> dict:
    if request == "structured":
        reporter.notice("开始任务规划", kind="milestone", stage="planning")
        reporter.progress(
            {
                "stage": "searching",
                "label": "检索 arXiv",
                "detail": "第 1 轮命中 2 篇，累计 2 篇",
                "percent": 24,
            }
        )
        reporter.notice("第 1 轮检索失败，准备继续尝试", kind="retry", stage="searching")
        return {"request": request, "refresh_existing": refresh_existing, "max_results": max_results}

    if request == "debug":
        reporter.debug("原始模型返回（解析失败） | parse_error=Expected JSON | response=not json")
        return {"ok": True}

    if request == "progress-regression":
        reporter.progress(
            {
                "stage": "processing",
                "label": "处理论文",
                "detail": "处理论文 1/2",
                "percent": 30,
                "paper_index": 1,
                "paper_total": 2,
            }
        )
        time.sleep(0.1)
        reporter.progress(
            {
                "stage": "processing",
                "label": "处理论文",
                "detail": "尝试回退到更低百分比",
                "percent": 20,
                "paper_index": 1,
                "paper_total": 2,
            }
        )
        time.sleep(0.5)
        return {"ok": True}

    if request == "confirm":
        approved = reporter.confirm(
            {
                "prompt": "继续吗？",
                "detail": "候选论文标题与输入差异较大。",
                "source": "arXiv",
                "requested_title": "Wanted Paper",
                "candidate_title": "Different Paper",
                "similarity_score": 0.21,
            }
        )
        return {"approved": approved}

    if request == "confirm-then-cancel":
        reporter.confirm(
            {
                "prompt": "继续吗？",
                "detail": "等待用户确认。",
                "source": "arXiv",
                "requested_title": "Wanted Paper",
                "candidate_title": "Different Paper",
                "similarity_score": 0.21,
            }
        )
        return {"approved": True}

    if request == "sleep":
        time.sleep(30)
        return {"ok": True}

    if request == "blocking-progress":
        reporter.progress(
            {
                "stage": "processing",
                "label": "处理论文",
                "detail": "正在分析 PDF",
                "percent": 40,
            }
        )
        time.sleep(30)
        return {"ok": True}

    if request == "crash":
        os._exit(7)

    return {"request": request, "refresh_existing": refresh_existing, "max_results": max_results}
