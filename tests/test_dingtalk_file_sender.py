from __future__ import annotations

from pathlib import Path

from src.models.schemas import ReportDocument
from src.services.dingtalk_binding_service import DingTalkBindingService
from src.services.dingtalk_file_sender import DingTalkFileSender


class DummyLogger:
    def warning(self, *_args, **_kwargs) -> None:
        return None

    def info(self, *_args, **_kwargs) -> None:
        return None


class FakeOapiClient:
    def __init__(self) -> None:
        self.token_calls = 0

    def get_access_token(self, app_key: str, app_secret: str) -> dict[str, object]:
        self.token_calls += 1
        assert app_key == "app-key"
        assert app_secret == "app-secret"
        return {"access_token": "token123", "expires_in": 7200}


class FakeWorkspaceClient:
    def __init__(self) -> None:
        self.space_calls: list[dict[str, str]] = []
        self.folder_calls: list[dict[str, str]] = []
        self.upload_info_calls: list[dict[str, str | int]] = []
        self.upload_binary_calls: list[dict[str, str]] = []
        self.commit_calls: list[dict[str, str]] = []
        self.send_calls: list[dict[str, str]] = []

    def create_space(
        self,
        access_token: str,
        union_id: str,
        title: str,
    ) -> dict[str, str]:
        self.space_calls.append(
            {"access_token": access_token, "union_id": union_id, "title": title}
        )
        return {"space": {"id": "space123"}}

    def create_folder(
        self,
        access_token: str,
        union_id: str,
        space_id: str,
        folder_name: str,
    ) -> dict[str, str]:
        self.folder_calls.append(
            {
                "access_token": access_token,
                "union_id": union_id,
                "space_id": space_id,
                "folder_name": folder_name,
            }
        )
        return {"dentry": {"id": "folder123", "uuid": "uuid123"}}

    def query_upload_info(
        self,
        access_token: str,
        union_id: str,
        parent_dentry_uuid: str,
        file_name: str,
        file_size: int,
    ) -> dict[str, object]:
        self.upload_info_calls.append(
            {
                "access_token": access_token,
                "union_id": union_id,
                "parent_dentry_uuid": parent_dentry_uuid,
                "file_name": file_name,
                "file_size": file_size,
            }
        )
        return {
            "uploadKey": "upload123",
            "headerSignatureInfo": {
                "headers": {
                    "Content-Type": "",
                    "x-oss-object-acl": "private",
                },
                "resourceUrls": ["https://oss.example/upload"],
            },
        }

    def upload_file_to_resource(
        self,
        resource_url: str,
        headers: dict[str, object],
        file_path: str,
    ) -> None:
        self.upload_binary_calls.append(
            {
                "resource_url": resource_url,
                "file_path": file_path,
                "content_type": str(headers.get("Content-Type", "")),
            }
        )

    def commit_file(
        self,
        access_token: str,
        union_id: str,
        parent_dentry_uuid: str,
        upload_key: str,
        file_name: str,
    ) -> dict[str, object]:
        self.commit_calls.append(
            {
                "access_token": access_token,
                "union_id": union_id,
                "parent_dentry_uuid": parent_dentry_uuid,
                "upload_key": upload_key,
                "file_name": file_name,
            }
        )
        return {"dentry": {"id": "file123"}}

    def send_conversation_file(
        self,
        access_token: str,
        union_id: str,
        open_conversation_id: str,
        space_id: str,
        dentry_id: str,
    ) -> dict[str, str]:
        self.send_calls.append(
            {
                "access_token": access_token,
                "union_id": union_id,
                "open_conversation_id": open_conversation_id,
                "space_id": space_id,
                "dentry_id": dentry_id,
            }
        )
        return {"processQueryKey": "ok"}


def build_report(tmp_path: Path) -> ReportDocument:
    markdown_path = tmp_path / "demo.md"
    markdown_path.write_text("# demo\n", encoding="utf-8")
    markdown_path.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
    return ReportDocument(
        report_month="2026-05",
        title="测试月报",
        markdown="# demo\n",
        output_path=markdown_path,
        executive_summary="summary",
    )


def test_file_sender_uploads_pdf_and_sends_group_message(tmp_path: Path) -> None:
    binding_service = DingTalkBindingService(
        binding_path=tmp_path / "dingtalk_binding.json",
        logger=DummyLogger(),
    )
    binding_service.save_binding("dingcorp", "oc_123", "纸袋月报群", "chat123", union_id="union123")
    sender = DingTalkFileSender(
        oapi_client=FakeOapiClient(),
        workspace_client=FakeWorkspaceClient(),
        app_key="app-key",
        app_secret="app-secret",
        agent_id="4668444612",
        binding_service=binding_service,
        token_cache_path=tmp_path / "token.json",
        logger=DummyLogger(),
    )

    result = sender.send_report_pdf(build_report(tmp_path))

    assert result.success is True
    assert result.channel == "conversation_file"
    assert result.response_payload["binding"]["openConversationId"] == "oc_123"
    assert result.response_payload["space"]["spaceId"] == "space123"
    assert result.response_payload["folder"]["folderUuid"] == "uuid123"
    assert result.response_payload["file"]["dentry"]["id"] == "file123"


def test_file_sender_returns_failure_when_binding_missing(tmp_path: Path) -> None:
    sender = DingTalkFileSender(
        oapi_client=FakeOapiClient(),
        workspace_client=FakeWorkspaceClient(),
        app_key="app-key",
        app_secret="app-secret",
        agent_id="4668444612",
        binding_service=DingTalkBindingService(tmp_path / "dingtalk_binding.json", DummyLogger()),
        token_cache_path=tmp_path / "token.json",
        logger=DummyLogger(),
    )

    result = sender.send_report_pdf(build_report(tmp_path))

    assert result.success is False
    assert result.message == "No DingTalk conversation binding found."
