from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.services.dingtalk_jsapi_service import DingTalkJsapiService


class FakeOapiClient:
    def __init__(self) -> None:
        self.access_token_calls = 0
        self.ticket_calls = 0

    def get_access_token(self, app_key: str, app_secret: str) -> dict[str, object]:
        self.access_token_calls += 1
        assert app_key == "app-key"
        assert app_secret == "app-secret"
        return {"access_token": "access-token"}

    def get_jsapi_ticket(self, access_token: str) -> dict[str, object]:
        self.ticket_calls += 1
        assert access_token == "access-token"
        return {"ticket": "ticket-123", "expires_in": 7200}


class DummyLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(message % args if args else message)


def test_normalize_url_strips_fragment() -> None:
    service = DingTalkJsapiService(
        oapi_client=FakeOapiClient(),
        app_key="app-key",
        app_secret="app-secret",
        agent_id="4668444612",
        cache_path=Path("/tmp/test_dingtalk_jsapi_ticket.json"),
        logger=DummyLogger(),
    )

    normalized = service.normalize_url("https://example.com/path?a=1#fragment")

    assert normalized == "https://example.com/path?a=1"


def test_build_config_generates_signature_and_reuses_cached_ticket(tmp_path: Path, monkeypatch) -> None:
    fake_client = FakeOapiClient()
    cache_path = tmp_path / "dingtalk_jsapi_ticket.json"
    logger = DummyLogger()
    service = DingTalkJsapiService(
        oapi_client=fake_client,
        app_key="app-key",
        app_secret="app-secret",
        agent_id="4668444612",
        cache_path=cache_path,
        logger=logger,
    )
    monkeypatch.setattr("src.services.dingtalk_jsapi_service.time.time", lambda: 1718188800)
    monkeypatch.setattr("src.services.dingtalk_jsapi_service.secrets.token_hex", lambda _: "nonce1234")

    payload = service.build_config("https://example.com/app?x=1#hash", "dingcorp")

    expected_sign_text = (
        "jsapi_ticket=ticket-123&noncestr=nonce1234&timestamp=1718188800&url=https://example.com/app?x=1"
    )
    assert payload == {
        "corpId": "dingcorp",
        "agentId": "4668444612",
        "timeStamp": 1718188800,
        "nonceStr": "nonce1234",
        "signature": hashlib.sha1(expected_sign_text.encode("utf-8")).hexdigest(),
        "url": "https://example.com/app?x=1",
    }
    assert fake_client.access_token_calls == 1
    assert fake_client.ticket_calls == 1
    assert json.loads(cache_path.read_text(encoding="utf-8"))["ticket"] == "ticket-123"

    second_payload = service.build_config("https://example.com/app?x=1#other", "dingcorp")

    assert second_payload["signature"] == payload["signature"]
    assert fake_client.access_token_calls == 1
    assert fake_client.ticket_calls == 1


def test_build_config_rejects_missing_corp_id(tmp_path: Path) -> None:
    service = DingTalkJsapiService(
        oapi_client=FakeOapiClient(),
        app_key="app-key",
        app_secret="app-secret",
        agent_id="4668444612",
        cache_path=tmp_path / "ticket.json",
        logger=DummyLogger(),
    )

    try:
        service.build_config("https://example.com/app", "")
    except ValueError as exc:
        assert str(exc) == "corpId is required."
    else:
        raise AssertionError("Expected build_config to require corpId")
