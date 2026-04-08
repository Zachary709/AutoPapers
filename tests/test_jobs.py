from __future__ import annotations

import time
import unittest

from autopapers.web.jobs import TaskManager


class TaskManagerTests(unittest.TestCase):
    def test_task_manager_emits_events_for_runtime_progress(self) -> None:
        events: list[tuple[str, str]] = []

        def runner(request: str, refresh_existing: bool, max_results: int | None, notify):
            notify("开始任务规划")
            return {"request": request, "refresh_existing": refresh_existing, "max_results": max_results}

        manager = TaskManager(
            runner,
            event_callback=lambda _job_id, kind, message: events.append((kind, message)),
        )
        try:
            job = manager.submit("帮我找论文", refresh_existing=True, max_results=3)
            for _ in range(100):
                current = manager.get(job["id"])
                if current and current["status"] == "completed":
                    break
                time.sleep(0.01)
            else:
                self.fail("job did not complete in time")
        finally:
            manager.close()

        event_kinds = [kind for kind, _message in events]
        self.assertIn("queued", event_kinds)
        self.assertIn("running", event_kinds)
        self.assertIn("notice", event_kinds)
        self.assertIn("completed", event_kinds)
        self.assertTrue(any("开始任务规划" in message for _kind, message in events))
