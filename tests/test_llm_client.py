from __future__ import annotations

import requests

from src.clients.llm_client import LLMClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict, timeout: int) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if not self.responses:
            raise AssertionError("No more fake responses available")
        return self.responses.pop(0)


def test_llm_client_retries_on_transient_http_error() -> None:
    client = LLMClient("https://example.com/v1", "token", "model", retry_attempts=1, retry_delay_seconds=0)
    session = FakeSession(
        [
            FakeResponse(502, {"error": "bad gateway"}),
            FakeResponse(200, {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}),
        ]
    )
    client.session = session

    response = client.chat_completion("system", "user")

    assert response["choices"][0]["message"]["content"] == '{"summary":"ok"}'
    assert len(session.calls) == 2
    assert session.calls[0]["json"]["response_format"] == {"type": "json_object"}


def test_llm_client_skips_structured_output_in_compatibility_mode() -> None:
    client = LLMClient("https://example.com/v1", "token", "model")
    session = FakeSession([FakeResponse(200, {"choices": [{"message": {"content": '{"summary":"ok"}'}}]})])
    client.session = session

    client.chat_completion("system", "user", structured_output=False)

    assert "response_format" not in session.calls[0]["json"]


def test_llm_client_uses_openai_chat_completions_for_openai_compatible_base_url() -> None:
    client = LLMClient("https://api.longcat.chat/openai/v1", "token", "LongCat-Flash-Chat")
    session = FakeSession([FakeResponse(200, {"choices": [{"message": {"content": '{"summary":"ok"}'}}]})])
    client.session = session

    client.chat_completion("system", "user")

    call = session.calls[0]
    assert call["url"] == "https://api.longcat.chat/openai/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer token"
    assert call["json"]["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert call["json"]["response_format"] == {"type": "json_object"}


def test_llm_client_uses_anthropic_messages_for_anthropic_base_url() -> None:
    client = LLMClient("https://token-plan-sgp.xiaomimimo.com/anthropic", "token", "mimo-v2.5-pro")
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "id": "msg_1",
                    "content": [{"type": "text", "text": '{"summary":"ok"}'}],
                    "model": "mimo-v2.5-pro",
                    "role": "assistant",
                },
            )
        ]
    )
    client.session = session

    response = client.chat_completion("system", "user", structured_output=True)

    call = session.calls[0]
    assert call["url"] == "https://token-plan-sgp.xiaomimimo.com/anthropic/v1/messages"
    assert call["headers"]["x-api-key"] == "token"
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["json"]["system"] == "system"
    assert call["json"]["messages"] == [{"role": "user", "content": "user"}]
    assert "response_format" not in call["json"]
    assert response["choices"][0]["message"]["content"] == '{"summary":"ok"}'


def test_llm_client_clone_preserves_config_with_independent_session() -> None:
    client = LLMClient(
        "https://example.com/v1",
        "token",
        "model",
        timeout_seconds=123,
        retry_attempts=2,
        retry_delay_seconds=0.5,
    )

    cloned = client.clone()

    assert cloned.base_url == client.base_url
    assert cloned.api_key == client.api_key
    assert cloned.model == client.model
    assert cloned.timeout_seconds == client.timeout_seconds
    assert cloned.retry_attempts == client.retry_attempts
    assert cloned.retry_delay_seconds == client.retry_delay_seconds
    assert cloned.session is not client.session
