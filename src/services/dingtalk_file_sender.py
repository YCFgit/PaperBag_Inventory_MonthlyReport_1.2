from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.clients.dingtalk_oapi_client import DingTalkOapiClient
from src.clients.dingtalk_workspace_client import DingTalkWorkspaceClient
from src.models.schemas import DeliveryResult, ReportDocument
from src.services.dingtalk_binding_service import DingTalkBindingService


class DingTalkFileSender:
    def __init__(
        self,
        oapi_client: DingTalkOapiClient,
        workspace_client: DingTalkWorkspaceClient,
        app_key: str,
        app_secret: str,
        agent_id: str,
        binding_service: DingTalkBindingService,
        token_cache_path: Path,
        logger: Any,
    ) -> None:
        self.oapi_client = oapi_client
        self.workspace_client = workspace_client
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self.agent_id = str(agent_id).strip()
        self.binding_service = binding_service
        self.token_cache_path = token_cache_path
        self.logger = logger

    def is_configured(self) -> bool:
        return bool(self.app_key and self.app_secret and self.agent_id and self.binding_service.load_binding())

    def send_report_pdf(self, report: ReportDocument) -> DeliveryResult:
        if not self.app_key or not self.app_secret or not self.agent_id:
            return DeliveryResult("conversation_file", False, "DingTalk conversation file sending is not fully configured.")

        binding = self.binding_service.load_binding()
        if binding is None:
            return DeliveryResult("conversation_file", False, "No DingTalk conversation binding found.")
        if not binding.union_id:
            return DeliveryResult("conversation_file", False, "DingTalk binding is missing unionId. Re-bind the conversation in DingTalk H5 page.")

        pdf_path = report.output_path.with_suffix(".pdf")
        if not pdf_path.exists():
            return DeliveryResult("conversation_file", False, f"PDF file not found: {pdf_path}")

        try:
            access_token = self._get_valid_access_token()
            space_id = binding.space_id or self._ensure_space_id(access_token, binding.union_id)
            folder_id, folder_uuid, binding = self._ensure_folder_location(access_token, binding, space_id)
            upload_info = self.workspace_client.query_upload_info(
                access_token=access_token,
                union_id=binding.union_id,
                parent_dentry_uuid=folder_uuid,
                file_name=pdf_path.name,
                file_size=pdf_path.stat().st_size,
            )
            header_signature_info = upload_info.get("headerSignatureInfo", {}) if isinstance(upload_info, dict) else {}
            resource_urls = header_signature_info.get("resourceUrls", []) if isinstance(header_signature_info, dict) else []
            resource_url = str(resource_urls[0] if resource_urls else "")
            upload_key = str(upload_info.get("uploadKey") or "")
            upload_headers = header_signature_info.get("headers", {}) if isinstance(header_signature_info, dict) else {}
            if not resource_url or not upload_key or not upload_headers:
                raise RuntimeError("DingTalk upload info response missing resourceUrl/uploadKey/headers.")
            self.workspace_client.upload_file_to_resource(
                resource_url=resource_url,
                headers=upload_headers,
                file_path=str(pdf_path),
            )
            file_payload = self.workspace_client.commit_file(
                access_token=access_token,
                union_id=binding.union_id,
                parent_dentry_uuid=folder_uuid,
                upload_key=upload_key,
                file_name=pdf_path.name,
            )
            dentry = file_payload.get("dentry", {}) if isinstance(file_payload.get("dentry"), dict) else {}
            dentry_id = str(dentry.get("id") or file_payload.get("fileId") or file_payload.get("dentryId") or "")
            if not dentry_id:
                raise RuntimeError("DingTalk add file response missing dentryId/fileId.")
            send_payload = self.workspace_client.send_conversation_file(
                access_token=access_token,
                union_id=binding.union_id,
                open_conversation_id=binding.open_conversation_id,
                space_id=space_id,
                dentry_id=dentry_id,
            )
            payload = {
                "binding": self.binding_service.to_payload(binding),
                "space": {"spaceId": space_id},
                "folder": {"folderId": folder_id, "folderUuid": folder_uuid},
                "uploadInfo": upload_info,
                "file": file_payload,
                "send": send_payload,
            }
            return DeliveryResult("conversation_file", True, "Conversation PDF delivery succeeded.", payload)
        except Exception as exc:
            self.logger.warning("Conversation PDF delivery failed: %s", exc)
            return DeliveryResult("conversation_file", False, str(exc))

    def _ensure_space_id(self, access_token: str, union_id: str) -> str:
        title = "纸袋月报自动投递空间"
        payload = self.workspace_client.create_space(access_token=access_token, union_id=union_id, title=title)
        space = payload.get("space", {}) if isinstance(payload.get("space"), dict) else {}
        space_id = str(space.get("id") or payload.get("id") or payload.get("spaceId") or "")
        if not space_id:
            raise RuntimeError("DingTalk create space response missing id/spaceId.")
        return space_id

    def _ensure_folder_location(self, access_token: str, binding, space_id: str) -> tuple[str, str, Any]:
        if binding.folder_id and binding.folder_uuid:
            return binding.folder_id, binding.folder_uuid, binding
        payload = self.workspace_client.create_folder(
            access_token=access_token,
            union_id=binding.union_id,
            space_id=space_id,
            folder_name="纸袋月报自动投递",
        )
        dentry = payload.get("dentry", {}) if isinstance(payload.get("dentry"), dict) else {}
        folder_id = str(dentry.get("id") or "")
        folder_uuid = str(dentry.get("uuid") or "")
        if not folder_id or not folder_uuid:
            raise RuntimeError("DingTalk create folder response missing id/uuid.")
        updated = self.binding_service.update_storage_location(space_id, folder_id, folder_uuid) or binding
        return folder_id, folder_uuid, updated

    def _get_valid_access_token(self) -> str:
        cached = self._read_token_cache()
        now = int(time.time())
        if cached and int(cached.get("expires_at", 0)) > now + 60:
            return str(cached["access_token"])

        token_payload = self.oapi_client.get_access_token(self.app_key, self.app_secret)
        access_token = str(token_payload["access_token"])
        expires_in = int(token_payload.get("expires_in", 7200))
        self._write_token_cache(access_token, now + expires_in)
        return access_token

    def _read_token_cache(self) -> dict[str, Any] | None:
        if not self.token_cache_path.exists():
            return None
        try:
            return json.loads(self.token_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("Failed to read DingTalk access token cache: %s", exc)
            return None

    def _write_token_cache(self, access_token: str, expires_at: int) -> None:
        self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"access_token": access_token, "expires_at": expires_at}
        self.token_cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
