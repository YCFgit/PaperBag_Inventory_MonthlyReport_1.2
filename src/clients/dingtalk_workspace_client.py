from __future__ import annotations

import json
from typing import Any

import requests


class DingTalkWorkspaceClient:
    def __init__(
        self,
        api_base_url: str = "https://api.dingtalk.com",
        oapi_base_url: str = "https://oapi.dingtalk.com",
        timeout_seconds: int = 30,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.oapi_base_url = oapi_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def create_space(self, access_token: str, union_id: str, title: str) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base_url}/v1.0/storage/spaces",
            params={"unionId": union_id},
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "option": {
                    "name": title,
                    "ownerType": "USER",
                }
            },
            timeout=self.timeout_seconds,
        )
        self._raise_for_response(response, "create storage space")
        return response.json()

    def create_folder(self, access_token: str, union_id: str, space_id: str, folder_name: str) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base_url}/v1.0/storage/spaces/{space_id}/dentries/0/folders",
            params={"unionId": union_id},
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "name": folder_name,
                "option": {"conflictStrategy": "AUTO_RENAME"},
            },
            timeout=self.timeout_seconds,
        )
        self._raise_for_response(response, "create folder in storage space")
        return response.json()

    def query_upload_info(
        self,
        access_token: str,
        union_id: str,
        parent_dentry_uuid: str,
        file_name: str,
        file_size: int,
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base_url}/v2.0/storage/spaces/files/{parent_dentry_uuid}/uploadInfos/query",
            params={"unionId": union_id},
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "protocol": "HEADER_SIGNATURE",
                "option": {
                    "storageDriver": "DINGTALK",
                    "preCheckParam": {
                        "name": file_name,
                        "size": file_size,
                    },
                },
            },
            timeout=self.timeout_seconds,
        )
        self._raise_for_response(response, "query file upload info")
        return response.json()

    def upload_file_to_resource(
        self,
        resource_url: str,
        headers: dict[str, Any],
        file_path: str,
    ) -> None:
        normalized_headers = {str(key): str(value) for key, value in headers.items()}
        with open(file_path, "rb") as file_obj:
            response = self.session.put(
                resource_url,
                headers=normalized_headers,
                data=file_obj,
                timeout=self.timeout_seconds,
            )
        self._raise_for_response(response, "upload file binary")

    def commit_file(
        self,
        access_token: str,
        union_id: str,
        parent_dentry_uuid: str,
        upload_key: str,
        file_name: str,
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base_url}/v2.0/storage/spaces/files/{parent_dentry_uuid}/commit",
            params={"unionId": union_id},
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "uploadKey": upload_key,
                "name": file_name,
                "option": {"conflictStrategy": "AUTO_RENAME"},
            },
            timeout=self.timeout_seconds,
        )
        self._raise_for_response(response, "commit uploaded file")
        return response.json()

    def send_conversation_file(
        self,
        access_token: str,
        union_id: str,
        open_conversation_id: str,
        space_id: str,
        dentry_id: str,
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base_url}/v1.0/convFile/conversations/files/send",
            params={"unionId": union_id},
            headers={
                "x-acs-dingtalk-access-token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "openConversationId": open_conversation_id,
                "spaceId": space_id,
                "dentryId": dentry_id,
            },
            timeout=self.timeout_seconds,
        )
        self._raise_for_response(response, "send conversation file")
        return response.json()

    def _raise_for_response(self, response: requests.Response, action: str) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = self._response_text(response)
            raise RuntimeError(
                f"DingTalk {action} API request failed: status={response.status_code}, body={detail}"
            ) from exc

    def _response_text(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            return json.dumps(payload, ensure_ascii=False)
        except ValueError:
            return response.text
