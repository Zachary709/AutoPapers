from __future__ import annotations

import json
import time
from typing import Callable
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

from autopapers.http_client import build_url_opener


class MiniMaxError(RuntimeError):
    """Raised when the configured LLM API call fails."""


class MiniMaxClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        api_url: str,
        timeout: int = 120,
        *,
        opener: Callable[..., object] | None = None,
        max_attempts: int = 6,
        retry_backoff_seconds: float = 10.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url.strip()
        self.request_url = self._normalize_api_url(self.api_url)
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
        response_format: dict[str, object] | None = None,
    ) -> str:
        last_error: MiniMaxError | None = None
        retry_total = max(self.max_attempts - 1, 0)
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._chat_text_once(
                    messages,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                    response_format=response_format,
                )
            except MiniMaxError as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                if notice_callback is not None:
                    notice_callback(
                        f"{retry_context} 调用失败，正在进行第 {attempt} 次重试（共 {retry_total} 次）：{exc}"
                    )
                self._sleep(self.retry_backoff_seconds)
        raise last_error or MiniMaxError(f"{self._service_label()} request failed.")

    def _chat_text_once(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_completion_tokens: int,
        response_format: dict[str, object] | None,
    ) -> str:
        if not self.api_key:
            raise MiniMaxError(f"{self._service_label()} API key is not configured.")

        candidate_formats = self._response_format_candidates(response_format)
        raw_body = ""
        last_http_error: Exception | None = None
        for candidate in candidate_formats:
            payload = self._build_payload(
                messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                response_format=candidate,
            )
            request = urllib.request.Request(
                self.request_url,
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
                break
            except urllib.error.HTTPError as exc:
                detail, body_text = self._describe_http_error(exc)
                last_http_error = exc
                if self._should_retry_with_fallback_format(exc.code, candidate, body_text):
                    continue
                if "HTTP Error 404" in detail and self.request_url != self.api_url:
                    detail = (
                        f"{detail} (resolved endpoint: {self.request_url}; saved value: {self.api_url})"
                    )
                raise MiniMaxError(f"{self._service_label()} request failed: {detail}") from exc
            except Exception as exc:
                detail = str(exc)
                if "HTTP Error 404" in detail and self.request_url != self.api_url:
                    detail = (
                        f"{detail} (resolved endpoint: {self.request_url}; saved value: {self.api_url})"
                    )
                raise MiniMaxError(f"{self._service_label()} request failed: {detail}") from exc
        else:
            if last_http_error is not None:
                detail, _ = self._describe_http_error(last_http_error)
                raise MiniMaxError(f"{self._service_label()} request failed: {detail}") from last_http_error
            raise MiniMaxError(f"{self._service_label()} request failed.")

        data = self._decode_response(raw_body)
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", 0) not in (0, None):
            raise MiniMaxError(
                f"{self._service_label()} error {base_resp.get('status_code')}: {base_resp.get('status_msg', '')}"
            )

        choices = data.get("choices", [])
        if not choices:
            raise MiniMaxError(f"{self._service_label()} returned no choices: {data}")

        message = choices[0].get("message", {})
        content = self._extract_message_content(message)
        if not isinstance(content, str):
            raise MiniMaxError(f"{self._service_label()} returned unexpected content payload: {message}")
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
            raise MiniMaxError(f"{self._service_label()} returned invalid JSON: {raw_body}") from exc

        if isinstance(data, dict) and data.get("type") == "error":
            raise MiniMaxError(self._describe_error_response([data]))
        if not isinstance(data, dict):
            raise MiniMaxError(f"{self._service_label()} returned unexpected payload: {data}")
        return data

    def _describe_error_response(self, objects: list[dict]) -> str:
        for item in objects:
            if not isinstance(item, dict):
                continue
            error = item.get("error")
            if isinstance(error, dict):
                error_type = error.get("type", "error")
                message = error.get("message", "")
                http_code = error.get("http_code")
                suffix = f", HTTP {http_code}" if http_code else ""
                return f"{self._service_label()} {error_type}: {message}{suffix}"
            base_resp = item.get("base_resp")
            if isinstance(base_resp, dict) and base_resp.get("status_code") not in (0, None):
                return f"{self._service_label()} error {base_resp.get('status_code')}: {base_resp.get('status_msg', '')}"
        return f"{self._service_label()} returned invalid JSON: {' '.join(str(item) for item in objects)}"

    def _uses_openai_chat_completions(self) -> bool:
        path = urlparse(self.request_url).path.rstrip("/")
        return path.endswith("/chat/completions")

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_completion_tokens: int,
        response_format: dict[str, object] | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if self._uses_openai_chat_completions():
            payload["max_tokens"] = max_completion_tokens
            if response_format:
                payload["response_format"] = response_format
        else:
            payload["max_completion_tokens"] = max_completion_tokens
        return payload

    def _response_format_candidates(self, response_format: dict[str, object] | None) -> list[dict[str, object] | None]:
        if not response_format or not self._uses_openai_chat_completions():
            return [response_format]
        if str(response_format.get("type") or "") != "json_schema":
            return [response_format]
        return [response_format, {"type": "json_object"}, None]

    def _should_retry_with_fallback_format(
        self,
        status_code: int,
        response_format: dict[str, object] | None,
        body_text: str,
    ) -> bool:
        if not response_format or not self._uses_openai_chat_completions():
            return False
        if status_code != 400:
            return False
        body_lower = body_text.lower()
        if not body_lower:
            return True
        return any(
            token in body_lower
            for token in (
                "response_format",
                "json_schema",
                "json_object",
                "strict",
                "unsupported",
                "invalid parameter",
                "unknown parameter",
                "messages must contain the word 'json'",
                "\"messages\" must contain the word \"json\"",
            )
        )

    @staticmethod
    def _describe_http_error(exc: urllib.error.HTTPError | Exception) -> tuple[str, str]:
        if not isinstance(exc, urllib.error.HTTPError):
            return str(exc), ""
        body_text = ""
        try:
            if exc.fp is not None:
                body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        detail = str(exc)
        if body_text.strip():
            detail = f"{detail} | body={body_text.strip()}"
        return detail, body_text

    @staticmethod
    def _extract_message_content(message: dict[str, object]) -> str | object:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if str(item.get("type") or "") not in {"text", "output_text"}:
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            if parts:
                return "\n".join(parts)
        return content

    def _service_label(self) -> str:
        model = str(self.model or "").strip()
        if model:
            return model
        host = urlparse(self.request_url or self.api_url).netloc.strip()
        return host or "LLM API"

    @staticmethod
    def _normalize_api_url(api_url: str) -> str:
        normalized = str(api_url or "").strip()
        if not normalized:
            return normalized
        parsed = urlparse(normalized)
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions") or path.endswith("/text/chatcompletion_v2"):
            return normalized
        if path.endswith("/v1") or path.endswith("/v4"):
            return urlunparse(parsed._replace(path=f"{path}/chat/completions"))
        return normalized
