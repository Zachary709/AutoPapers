from __future__ import annotations

import json
import time
from typing import Callable
import urllib.request

from autopapers.http_client import build_url_opener


class MiniMaxError(RuntimeError):
    """Raised when the MiniMax API call fails."""


class MiniMaxClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        api_url: str,
        timeout: int = 120,
        *,
        opener: Callable[..., object] | None = None,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 2.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.timeout = timeout
        self._opener = opener or build_url_opener().open
        self.max_attempts = max(1, int(max_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self._sleep = sleep_fn or time.sleep

    def chat_text(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_completion_tokens: int = 1800,
        retry_context: str = "MiniMax",
        notice_callback: Callable[[str], None] | None = None,
    ) -> str:
        last_error: MiniMaxError | None = None
        retry_total = max(self.max_attempts - 1, 0)
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._chat_text_once(
                    messages,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
            except MiniMaxError as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                if notice_callback is not None:
                    notice_callback(
                        f"{retry_context} 调用失败，正在进行第 {attempt} 次重试（共 {retry_total} 次）：{exc}"
                    )
                self._sleep(self.retry_backoff_seconds * attempt)
        raise last_error or MiniMaxError("MiniMax request failed.")

    def _chat_text_once(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_completion_tokens: int,
    ) -> str:
        if not self.api_key:
            raise MiniMaxError("MINIMAX_API_KEY is not configured.")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
        }
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8")
        except Exception as exc:
            raise MiniMaxError(f"MiniMax request failed: {exc}") from exc

        data = self._decode_response(raw_body)
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", 0) not in (0, None):
            raise MiniMaxError(
                f"MiniMax error {base_resp.get('status_code')}: {base_resp.get('status_msg', '')}"
            )

        choices = data.get("choices", [])
        if not choices:
            raise MiniMaxError(f"MiniMax returned no choices: {data}")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not isinstance(content, str):
            raise MiniMaxError(f"MiniMax returned unexpected content payload: {message}")
        return content.strip()

    def _decode_response(self, raw_body: str) -> dict:
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            parsed_lines = []
            for line in raw_body.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed_lines.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
            if parsed_lines:
                raise MiniMaxError(self._describe_error_response(parsed_lines)) from exc
            raise MiniMaxError(f"MiniMax returned invalid JSON: {raw_body}") from exc

        if isinstance(data, dict) and data.get("type") == "error":
            raise MiniMaxError(self._describe_error_response([data]))
        if not isinstance(data, dict):
            raise MiniMaxError(f"MiniMax returned unexpected payload: {data}")
        return data

    @staticmethod
    def _describe_error_response(objects: list[dict]) -> str:
        for item in objects:
            if not isinstance(item, dict):
                continue
            error = item.get("error")
            if isinstance(error, dict):
                error_type = error.get("type", "error")
                message = error.get("message", "")
                http_code = error.get("http_code")
                suffix = f", HTTP {http_code}" if http_code else ""
                return f"MiniMax {error_type}: {message}{suffix}"
            base_resp = item.get("base_resp")
            if isinstance(base_resp, dict) and base_resp.get("status_code") not in (0, None):
                return f"MiniMax error {base_resp.get('status_code')}: {base_resp.get('status_msg', '')}"
        return f"MiniMax returned invalid JSON: {' '.join(str(item) for item in objects)}"
