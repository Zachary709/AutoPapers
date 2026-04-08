from __future__ import annotations

import json
import unittest

from autopapers.llm.minimax import MiniMaxClient, MiniMaxError


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def make_opener(outcomes: list[object]):
    remaining = list(outcomes)

    def opener(request, timeout=0):
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    return opener


class MiniMaxClientTests(unittest.TestCase):
    def test_chat_text_retries_twice_then_succeeds(self) -> None:
        notices: list[str] = []
        payload = json.dumps(
            {
                "base_resp": {"status_code": 0},
                "choices": [{"message": {"content": "ok"}}],
            }
        )
        client = MiniMaxClient(
            api_key="test",
            model="MiniMax-M2.7",
            api_url="https://example.com",
            opener=make_opener([OSError("network"), OSError("again"), payload]),
            sleep_fn=lambda seconds: None,
        )

        result = client.chat_text(
            [{"role": "user", "content": "hi"}],
            retry_context="任务规划",
            notice_callback=notices.append,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(len(notices), 2)
        self.assertIn("第 1 次重试", notices[0])
        self.assertIn("第 2 次重试", notices[1])

    def test_chat_text_raises_after_three_failures(self) -> None:
        client = MiniMaxClient(
            api_key="test",
            model="MiniMax-M2.7",
            api_url="https://example.com",
            opener=make_opener([OSError("1"), OSError("2"), OSError("3")]),
            sleep_fn=lambda seconds: None,
        )

        with self.assertRaises(MiniMaxError):
            client.chat_text([{"role": "user", "content": "hi"}])
