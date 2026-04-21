from __future__ import annotations

import io
import json
import unittest
import urllib.error

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


class RecordingOpener:
    def __init__(self, body: str) -> None:
        self.body = body
        self.requests: list[object] = []

    def __call__(self, request, timeout=0):
        self.requests.append(request)
        return FakeResponse(self.body)


class RecordingSequenceOpener:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[object] = []

    def __call__(self, request, timeout=0):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class MiniMaxClientTests(unittest.TestCase):
    def test_chat_text_retries_five_times_then_succeeds(self) -> None:
        notices: list[str] = []
        sleep_calls: list[float] = []
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
            opener=make_opener(
                [
                    OSError("network"),
                    OSError("again"),
                    OSError("third"),
                    OSError("fourth"),
                    OSError("fifth"),
                    payload,
                ]
            ),
            sleep_fn=sleep_calls.append,
        )

        result = client.chat_text(
            [{"role": "user", "content": "hi"}],
            retry_context="任务规划",
            notice_callback=notices.append,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(len(notices), 5)
        self.assertEqual(sleep_calls, [10.0, 10.0, 10.0, 10.0, 10.0])
        self.assertIn("第 1 次重试", notices[0])
        self.assertIn("第 5 次重试", notices[-1])
        self.assertIn("共 5 次", notices[-1])

    def test_chat_text_raises_after_six_failures(self) -> None:
        sleep_calls: list[float] = []
        client = MiniMaxClient(
            api_key="test",
            model="MiniMax-M2.7",
            api_url="https://example.com",
            opener=make_opener([OSError("1"), OSError("2"), OSError("3"), OSError("4"), OSError("5"), OSError("6")]),
            sleep_fn=sleep_calls.append,
        )

        with self.assertRaises(MiniMaxError):
            client.chat_text([{"role": "user", "content": "hi"}])
        self.assertEqual(sleep_calls, [10.0, 10.0, 10.0, 10.0, 10.0])

    def test_chat_text_normalizes_openai_compatible_base_url_and_uses_max_tokens(self) -> None:
        opener = RecordingOpener(
            json.dumps(
                {
                    "choices": [{"message": {"content": "ok"}}],
                }
            )
        )
        client = MiniMaxClient(
            api_key="test",
            model="glm-5.1",
            api_url="https://api.z.ai/api/coding/paas/v4",
            opener=opener,
        )

        result = client.chat_text([{"role": "user", "content": "hi"}], max_completion_tokens=321)

        self.assertEqual(result, "ok")
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.z.ai/api/coding/paas/v4/chat/completions")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["max_tokens"], 321)
        self.assertNotIn("max_completion_tokens", payload)

    def test_chat_text_keeps_minimax_endpoint_and_uses_max_completion_tokens(self) -> None:
        opener = RecordingOpener(
            json.dumps(
                {
                    "base_resp": {"status_code": 0},
                    "choices": [{"message": {"content": "ok"}}],
                }
            )
        )
        client = MiniMaxClient(
            api_key="test",
            model="MiniMax-M2.7",
            api_url="https://api.minimaxi.com/v1/text/chatcompletion_v2",
            opener=opener,
        )

        result = client.chat_text([{"role": "user", "content": "hi"}], max_completion_tokens=123)

        self.assertEqual(result, "ok")
        request = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.minimaxi.com/v1/text/chatcompletion_v2")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["max_completion_tokens"], 123)
        self.assertNotIn("max_tokens", payload)

    def test_chat_text_reports_provider_label_and_resolved_404_endpoint(self) -> None:
        client = MiniMaxClient(
            api_key="test",
            model="glm-5.1",
            api_url="https://api.z.ai/api/coding/paas/v4",
            opener=make_opener([urllib.error.HTTPError("https://api.z.ai/api/coding/paas/v4/chat/completions", 404, "Not Found", {}, None)]),
            max_attempts=1,
        )

        with self.assertRaises(MiniMaxError) as caught:
            client.chat_text([{"role": "user", "content": "hi"}])

        message = str(caught.exception)
        self.assertIn("glm-5.1 request failed", message)
        self.assertIn("resolved endpoint: https://api.z.ai/api/coding/paas/v4/chat/completions", message)
        self.assertIn("saved value: https://api.z.ai/api/coding/paas/v4", message)
        self.assertNotIn("MiniMax request failed", message)

    def test_chat_text_includes_response_format_for_openai_compatible_endpoint(self) -> None:
        opener = RecordingOpener(
            json.dumps(
                {
                    "choices": [{"message": {"content": "ok"}}],
                }
            )
        )
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "request_plan",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"intent": {"type": "string"}},
                    "required": ["intent"],
                    "additionalProperties": False,
                },
            },
        }
        client = MiniMaxClient(
            api_key="test",
            model="glm-5.1",
            api_url="https://api.z.ai/api/coding/paas/v4",
            opener=opener,
        )

        client.chat_text(
            [{"role": "system", "content": "Return JSON only."}, {"role": "user", "content": "JSON"}],
            response_format=response_format,
        )

        payload = json.loads(opener.requests[0].data.decode("utf-8"))
        self.assertEqual(payload["response_format"], response_format)

    def test_chat_text_falls_back_from_json_schema_to_json_object_on_unsupported_response_format(self) -> None:
        unsupported_schema = urllib.error.HTTPError(
            "https://api.z.ai/api/coding/paas/v4/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error":{"message":"Unknown parameter: response_format"}}'),
        )
        opener = RecordingSequenceOpener(
            [
                unsupported_schema,
                json.dumps({"choices": [{"message": {"content": "{\"intent\":\"explain_paper\"}"}}]}),
            ]
        )
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "request_plan",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"intent": {"type": "string"}},
                    "required": ["intent"],
                    "additionalProperties": False,
                },
            },
        }
        client = MiniMaxClient(
            api_key="test",
            model="glm-5.1",
            api_url="https://api.z.ai/api/coding/paas/v4",
            opener=opener,
        )

        result = client.chat_text(
            [{"role": "system", "content": "Return JSON only."}, {"role": "user", "content": "JSON"}],
            response_format=response_format,
        )

        self.assertEqual(result, '{"intent":"explain_paper"}')
        first_payload = json.loads(opener.requests[0].data.decode("utf-8"))
        second_payload = json.loads(opener.requests[1].data.decode("utf-8"))
        self.assertEqual(first_payload["response_format"]["type"], "json_schema")
        self.assertEqual(second_payload["response_format"]["type"], "json_object")
