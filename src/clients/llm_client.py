from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import requests


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        retry_attempts: int = 1,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.session = requests.Session()

    def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        structured_output: bool = True,
    ) -> dict[str, Any]:
        if self._provider() == "anthropic":
            return self._anthropic_messages(system_prompt, user_prompt)

        return self._openai_chat_completions(system_prompt, user_prompt, structured_output=structured_output)

    def clone(self) -> "LLMClient":
        return LLMClient(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            timeout_seconds=self.timeout_seconds,
            retry_attempts=self.retry_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
        )

    def _openai_chat_completions(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        structured_output: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        if structured_output:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(self.retry_attempts + 1):
            response = self.session.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError:
                if response.status_code not in {429, 500, 502, 503, 504} or attempt >= self.retry_attempts:
                    raise
                time.sleep(self.retry_delay_seconds * (attempt + 1))
                continue
            return response.json()

        raise RuntimeError("LLM request exhausted retry attempts without returning a response.")

    def _anthropic_messages(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.2,
            "max_tokens": 4096,
        }

        for attempt in range(self.retry_attempts + 1):
            response = self.session.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError:
                if response.status_code not in {429, 500, 502, 503, 504} or attempt >= self.retry_attempts:
                    raise
                time.sleep(self.retry_delay_seconds * (attempt + 1))
                continue
            return self._normalize_anthropic_response(response.json())

        raise RuntimeError("LLM request exhausted retry attempts without returning a response.")

    def _normalize_anthropic_response(self, response: dict[str, Any]) -> dict[str, Any]:
        content = response.get("content")
        text_parts: list[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    text_parts.append(str(item["text"]))
                elif isinstance(item, str):
                    text_parts.append(item)
        elif isinstance(content, str):
            text_parts.append(content)

        return {
            "id": response.get("id"),
            "model": response.get("model", self.model),
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "".join(text_parts),
                    },
                    "finish_reason": response.get("stop_reason"),
                }
            ],
            "raw_response": response,
        }

    def _provider(self) -> str:
        parsed = urlparse(self.base_url)
        path_parts = [part for part in parsed.path.lower().split("/") if part]
        if path_parts and path_parts[-1] == "anthropic":
            return "anthropic"
        return "openai"
