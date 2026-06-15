from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models.schemas import DingTalkConversationBinding


class DingTalkBindingService:
    def __init__(
        self,
        binding_path: Path,
        logger: Any,
        configured_corp_id: str = "",
        configured_open_conversation_id: str = "",
    ) -> None:
        self.binding_path = binding_path
        self.logger = logger
        self.configured_corp_id = configured_corp_id.strip()
        self.configured_open_conversation_id = configured_open_conversation_id.strip()

    def load_binding(self) -> DingTalkConversationBinding | None:
        if self.configured_open_conversation_id:
            return DingTalkConversationBinding(
                corp_id=self.configured_corp_id,
                open_conversation_id=self.configured_open_conversation_id,
            )

        if not self.binding_path.exists():
            return None

        try:
            payload = json.loads(self.binding_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("Failed to read DingTalk binding file: %s", exc)
            return None

        open_conversation_id = str(payload.get("openConversationId", "")).strip()
        if not open_conversation_id:
            return None

        return DingTalkConversationBinding(
            corp_id=str(payload.get("corpId", "")).strip(),
            open_conversation_id=open_conversation_id,
            title=str(payload.get("title", "")).strip(),
            chat_id=str(payload.get("chatId", "")).strip(),
            union_id=str(payload.get("unionId", "")).strip(),
            user_id=str(payload.get("userId", "")).strip(),
            operator_name=str(payload.get("operatorName", "")).strip(),
            space_id=str(payload.get("spaceId", "")).strip(),
            folder_id=str(payload.get("folderId", "")).strip(),
            folder_uuid=str(payload.get("folderUuid", "")).strip(),
            bound_at=str(payload.get("boundAt", "")).strip(),
        )

    def save_binding(
        self,
        corp_id: str,
        open_conversation_id: str,
        title: str = "",
        chat_id: str = "",
        union_id: str = "",
        user_id: str = "",
        operator_name: str = "",
        space_id: str = "",
        folder_id: str = "",
        folder_uuid: str = "",
    ) -> DingTalkConversationBinding:
        binding = DingTalkConversationBinding(
            corp_id=corp_id.strip(),
            open_conversation_id=open_conversation_id.strip(),
            title=title.strip(),
            chat_id=chat_id.strip(),
            union_id=union_id.strip(),
            user_id=user_id.strip(),
            operator_name=operator_name.strip(),
            space_id=space_id.strip(),
            folder_id=folder_id.strip(),
            folder_uuid=folder_uuid.strip(),
            bound_at=datetime.now().isoformat(timespec="seconds"),
        )
        payload = {
            "corpId": binding.corp_id,
            "openConversationId": binding.open_conversation_id,
            "title": binding.title,
            "chatId": binding.chat_id,
            "unionId": binding.union_id,
            "userId": binding.user_id,
            "operatorName": binding.operator_name,
            "spaceId": binding.space_id,
            "folderId": binding.folder_id,
            "folderUuid": binding.folder_uuid,
            "boundAt": binding.bound_at,
        }
        self.binding_path.parent.mkdir(parents=True, exist_ok=True)
        self.binding_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("Saved DingTalk conversation binding to %s", self.binding_path)
        return binding

    def update_space_id(self, space_id: str) -> DingTalkConversationBinding | None:
        binding = self.load_binding()
        if binding is None:
            return None
        return self.save_binding(
            corp_id=binding.corp_id,
            open_conversation_id=binding.open_conversation_id,
            title=binding.title,
            chat_id=binding.chat_id,
            union_id=binding.union_id,
            user_id=binding.user_id,
            operator_name=binding.operator_name,
            space_id=space_id,
            folder_id=binding.folder_id,
            folder_uuid=binding.folder_uuid,
        )

    def update_storage_location(self, space_id: str, folder_id: str, folder_uuid: str) -> DingTalkConversationBinding | None:
        binding = self.load_binding()
        if binding is None:
            return None
        return self.save_binding(
            corp_id=binding.corp_id,
            open_conversation_id=binding.open_conversation_id,
            title=binding.title,
            chat_id=binding.chat_id,
            union_id=binding.union_id,
            user_id=binding.user_id,
            operator_name=binding.operator_name,
            space_id=space_id,
            folder_id=folder_id,
            folder_uuid=folder_uuid,
        )

    def to_payload(self, binding: DingTalkConversationBinding | None) -> dict[str, Any]:
        if binding is None:
            return {}
        payload = asdict(binding)
        payload["corpId"] = payload.pop("corp_id")
        payload["openConversationId"] = payload.pop("open_conversation_id")
        payload["chatId"] = payload.pop("chat_id")
        payload["unionId"] = payload.pop("union_id")
        payload["userId"] = payload.pop("user_id")
        payload["operatorName"] = payload.pop("operator_name")
        payload["spaceId"] = payload.pop("space_id")
        payload["folderId"] = payload.pop("folder_id")
        payload["folderUuid"] = payload.pop("folder_uuid")
        payload["boundAt"] = payload.pop("bound_at")
        return payload
