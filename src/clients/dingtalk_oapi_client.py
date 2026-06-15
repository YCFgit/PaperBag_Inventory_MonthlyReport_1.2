from __future__ import annotations

from pathlib import Path
from typing import Any

import requests


class DingTalkOapiClient:
    def __init__(self, base_url: str = "https://oapi.dingtalk.com", timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def get_access_token(self, app_key: str, app_secret: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/gettoken",
            params={"appkey": app_key, "appsecret": app_secret},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_if_business_failed(payload)
        return payload

    def get_jsapi_ticket(self, access_token: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/get_jsapi_ticket",
            params={"access_token": access_token},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_if_business_failed(payload)
        return payload

    def get_user_info_by_auth_code(self, access_token: str, code: str) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/topapi/v2/user/getuserinfo",
            params={"access_token": access_token},
            json={"code": code},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_if_business_failed(payload)
        result = payload.get("result")
        return result if isinstance(result, dict) else payload

    def upload_media_file(self, access_token: str, file_path: Path, media_type: str = "file") -> dict[str, Any]:
        with file_path.open("rb") as file_obj:
            response = self.session.post(
                f"{self.base_url}/media/upload",
                params={"access_token": access_token, "type": media_type},
                files={"media": (file_path.name, file_obj)},
                timeout=self.timeout_seconds,
            )
        response.raise_for_status()
        payload = response.json()
        self._raise_if_business_failed(payload)
        return payload

    def upload_file_single(self, access_token: str, agent_id: str, file_path: Path) -> dict[str, Any]:
        with file_path.open("rb") as file_obj:
            response = self.session.post(
                f"{self.base_url}/file/upload/single",
                params={
                    "access_token": access_token,
                    "agent_id": str(agent_id),
                    "file_size": file_path.stat().st_size,
                },
                files={"media": (file_path.name, file_obj)},
                timeout=self.timeout_seconds,
            )
        response.raise_for_status()
        payload = response.json()
        self._raise_if_business_failed(payload)
        return payload

    def _raise_if_business_failed(self, payload: dict[str, Any]) -> None:
        errcode = payload.get("errcode")
        if errcode in (None, 0, "0"):
            return
        errmsg = payload.get("errmsg", "unknown error")
        raise RuntimeError(f"DingTalk OAPI business error: errcode={errcode}, errmsg={errmsg}")
