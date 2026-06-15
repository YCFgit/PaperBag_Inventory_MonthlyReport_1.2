from __future__ import annotations

from pathlib import Path

from src.services.dingtalk_binding_service import DingTalkBindingService


class DummyLogger:
    def warning(self, *_args, **_kwargs) -> None:
        return None

    def info(self, *_args, **_kwargs) -> None:
        return None


def test_binding_service_saves_and_loads_binding(tmp_path: Path) -> None:
    service = DingTalkBindingService(
        binding_path=tmp_path / "dingtalk_binding.json",
        logger=DummyLogger(),
    )

    saved = service.save_binding(
        corp_id="dingcorp",
        open_conversation_id="oc_123",
        title="纸袋月报群",
        chat_id="chat123",
        union_id="union123",
        user_id="user123",
        operator_name="张三",
        space_id="space123",
    )
    loaded = service.load_binding()

    assert saved.open_conversation_id == "oc_123"
    assert loaded is not None
    assert loaded.corp_id == "dingcorp"
    assert loaded.open_conversation_id == "oc_123"
    assert loaded.title == "纸袋月报群"
    assert loaded.chat_id == "chat123"
    assert loaded.union_id == "union123"
    assert loaded.user_id == "user123"
    assert loaded.operator_name == "张三"
    assert loaded.space_id == "space123"


def test_binding_service_prefers_configured_open_conversation_id(tmp_path: Path) -> None:
    service = DingTalkBindingService(
        binding_path=tmp_path / "dingtalk_binding.json",
        logger=DummyLogger(),
        configured_corp_id="dingcorp",
        configured_open_conversation_id="oc_env",
    )

    loaded = service.load_binding()

    assert loaded is not None
    assert loaded.corp_id == "dingcorp"
    assert loaded.open_conversation_id == "oc_env"
