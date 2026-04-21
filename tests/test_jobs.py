from __future__ import annotations

import time
import unittest

from autopapers.web.jobs import TaskManager
from autopapers.web.test_workers import job_test_worker


def wait_for(predicate, *, timeout: float = 5.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def wait_for_job_status(manager: TaskManager, job_id: str, status: str, *, timeout: float = 5.0):
    return wait_for(lambda: _job_with_status(manager, job_id, status), timeout=timeout)


def _job_with_status(manager: TaskManager, job_id: str, status: str):
    current = manager.get(job_id)
    if current and current["status"] == status:
        return current
    return None


class TaskManagerTests(unittest.TestCase):
    def test_task_manager_emits_structured_progress_and_notices(self) -> None:
        events: list[tuple[str, str]] = []
        manager = TaskManager(
            job_test_worker,
            event_callback=lambda _job_id, kind, message: events.append((kind, message)),
        )
        try:
            job = manager.submit("structured", refresh_existing=True, max_results=3)
            current = wait_for_job_status(manager, job["id"], "completed")
            if current is None:
                self.fail("job did not complete in time")
        finally:
            manager.close()

        event_kinds = [kind for kind, _message in events]
        self.assertIn("queued", event_kinds)
        self.assertIn("running", event_kinds)
        self.assertIn("progress", event_kinds)
        self.assertIn("notice", event_kinds)
        self.assertIn("completed", event_kinds)
        self.assertEqual(current["progress"]["stage"], "completed")
        self.assertEqual(current["progress"]["percent"], 100)
        self.assertEqual(current["notices"][0]["kind"], "milestone")
        self.assertEqual(current["notices"][0]["stage"], "planning")
        self.assertEqual(current["notices"][1]["kind"], "retry")
        self.assertEqual(current["notices"][1]["stage"], "searching")

    def test_task_manager_keeps_progress_monotonic_and_updates_queue_positions(self) -> None:
        manager = TaskManager(job_test_worker, max_workers=1)
        try:
            first = manager.submit("progress-regression")
            running = wait_for_job_status(manager, first["id"], "running")
            if running is None:
                self.fail("first job did not start in time")
            second = manager.submit("sleep")

            queued = wait_for_job_status(manager, second["id"], "queued")
            if queued is None:
                self.fail("second job did not stay queued in time")
            self.assertTrue(queued["progress"]["indeterminate"])
            self.assertEqual(queued["progress"]["queue_position"], 1)

            regressed = wait_for(
                lambda: _job_with_detail(manager, first["id"], "尝试回退到更低百分比"),
                timeout=3.0,
            )
            if regressed is None:
                self.fail("first job did not report the regressed progress detail in time")
            self.assertEqual(regressed["progress"]["percent"], 30)

            current = wait_for_job_status(manager, first["id"], "completed")
            if current is None:
                self.fail("first job did not complete in time")
        finally:
            manager.close()

    def test_task_manager_emits_debug_events_without_adding_timeline_notices(self) -> None:
        events: list[tuple[str, str]] = []
        manager = TaskManager(
            job_test_worker,
            event_callback=lambda _job_id, kind, message: events.append((kind, message)),
        )
        try:
            job = manager.submit("debug")
            current = wait_for_job_status(manager, job["id"], "completed")
            if current is None:
                self.fail("job did not complete in time")
        finally:
            manager.close()

        self.assertIn(("debug", "原始模型返回（解析失败） | parse_error=Expected JSON | response=not json"), events)
        self.assertEqual(current["notices"], [])

    def test_task_manager_waits_for_confirmation_and_resumes(self) -> None:
        manager = TaskManager(job_test_worker)
        try:
            job = manager.submit("confirm")
            current = wait_for_job_status(manager, job["id"], "awaiting_confirmation")
            if current is None:
                self.fail("job did not enter confirmation state in time")
            self.assertIsNotNone(current["confirmation"])
            self.assertEqual(current["confirmation"]["source"], "arXiv")

            updated = manager.respond_confirmation(job["id"], current["confirmation"]["id"], approved=True)
            self.assertIsNotNone(updated)

            current = wait_for_job_status(manager, job["id"], "completed")
            if current is None:
                self.fail("job did not resume after confirmation")
            self.assertEqual(current["result"]["approved"], True)
        finally:
            manager.close()

    def test_task_manager_cancels_queued_job_before_it_starts(self) -> None:
        manager = TaskManager(job_test_worker, max_workers=1)
        try:
            first = manager.submit("sleep")
            running = wait_for_job_status(manager, first["id"], "running")
            if running is None:
                self.fail("first job did not start in time")

            second = manager.submit("structured")
            cancelled = manager.cancel(second["id"])
            self.assertIsNotNone(cancelled)
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertTrue(cancelled["cancel_requested"])

            current = manager.get(second["id"])
            self.assertIsNotNone(current)
            self.assertEqual(current["status"], "cancelled")
            self.assertEqual(current["error"], "用户手动停止任务。")
        finally:
            manager.close()

    def test_task_manager_cancels_running_job_via_process_termination(self) -> None:
        manager = TaskManager(job_test_worker, max_workers=1)
        try:
            job = manager.submit("sleep")
            running = wait_for_job_status(manager, job["id"], "running")
            if running is None:
                self.fail("job did not start in time")

            cancelled = manager.cancel(job["id"])
            self.assertIsNotNone(cancelled)
            self.assertTrue(cancelled["cancel_requested"])
            self.assertEqual(cancelled["progress"]["detail"], "已收到停止请求，正在终止任务进程。")

            current = wait_for_job_status(manager, job["id"], "cancelled")
            if current is None:
                self.fail("job did not cancel in time")
            self.assertTrue(current["cancel_requested"])
            self.assertEqual(current["error"], "用户手动停止任务。")
            self.assertEqual(current["progress"]["stage"], "cancelled")
        finally:
            manager.close()

    def test_task_manager_cancels_confirmation_wait_by_killing_worker(self) -> None:
        manager = TaskManager(job_test_worker, max_workers=1)
        try:
            job = manager.submit("confirm-then-cancel")
            current = wait_for_job_status(manager, job["id"], "awaiting_confirmation")
            if current is None:
                self.fail("job did not enter confirmation state in time")

            cancelled = manager.cancel(job["id"])
            self.assertIsNotNone(cancelled)
            self.assertTrue(cancelled["cancel_requested"])

            current = wait_for_job_status(manager, job["id"], "cancelled")
            if current is None:
                self.fail("job did not cancel from confirmation state in time")
            self.assertIsNone(current["confirmation"])
            self.assertEqual(current["error"], "用户手动停止任务。")
        finally:
            manager.close()

    def test_task_manager_marks_abnormal_worker_exit_as_failed(self) -> None:
        manager = TaskManager(job_test_worker)
        try:
            job = manager.submit("crash")
            current = wait_for_job_status(manager, job["id"], "failed")
            if current is None:
                self.fail("job did not fail in time")
        finally:
            manager.close()

        self.assertIn("任务进程异常退出", current["error"])
        self.assertIn("exit_code=7", current["error"])

    def test_task_manager_close_terminates_live_worker_process(self) -> None:
        manager = TaskManager(job_test_worker)
        job = manager.submit("sleep")
        running = wait_for_job_status(manager, job["id"], "running")
        if running is None:
            manager.close()
            self.fail("job did not start in time")

        worker_state = wait_for(lambda: manager._workers.get(job["id"]), timeout=2.0)
        if worker_state is None:
            manager.close()
            self.fail("worker state was not registered in time")

        process = worker_state.process
        manager.close()
        process.join(timeout=2.0)
        self.assertFalse(process.is_alive())


def _job_with_detail(manager: TaskManager, job_id: str, detail: str):
    current = manager.get(job_id)
    if current and current["progress"]["detail"] == detail:
        return current
    return None
