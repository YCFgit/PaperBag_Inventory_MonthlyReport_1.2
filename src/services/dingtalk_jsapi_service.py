from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.clients.dingtalk_oapi_client import DingTalkOapiClient


class DingTalkJsapiService:
    def __init__(
        self,
        oapi_client: DingTalkOapiClient,
        app_key: str,
        app_secret: str,
        agent_id: str,
        cache_path: Path,
        logger: Any,
    ) -> None:
        self.oapi_client = oapi_client
        self.app_key = app_key
        self.app_secret = app_secret
        self.agent_id = str(agent_id)
        self.cache_path = cache_path
        self.logger = logger

    def build_config(self, url: str, corp_id: str) -> dict[str, Any]:
        normalized_url = self.normalize_url(url)
        if not corp_id.strip():
            raise ValueError("corpId is required.")

        ticket = self._get_valid_ticket()
        time_stamp = int(time.time())
        nonce_str = secrets.token_hex(8)
        signature = self._sign(ticket, nonce_str, time_stamp, normalized_url)

        return {
            "corpId": corp_id.strip(),
            "agentId": self.agent_id,
            "timeStamp": time_stamp,
            "nonceStr": nonce_str,
            "signature": signature,
            "url": normalized_url,
        }

    def normalize_url(self, url: str) -> str:
        if not url.strip():
            raise ValueError("url is required.")

        parsed = urlsplit(url.strip())
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL.")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    def _get_valid_ticket(self) -> str:
        cached = self._read_cache()
        now = int(time.time())
        if cached and int(cached.get("expires_at", 0)) > now + 60:
            return str(cached["ticket"])

        access_token_payload = self.oapi_client.get_access_token(self.app_key, self.app_secret)
        ticket_payload = self.oapi_client.get_jsapi_ticket(str(access_token_payload["access_token"]))
        expires_in = int(ticket_payload.get("expires_in", 7200))
        ticket = str(ticket_payload["ticket"])
        self._write_cache(ticket, now + expires_in)
        return ticket

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None

        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("Failed to read DingTalk JSAPI cache, refetching ticket: %s", exc)
            return None

    def _write_cache(self, ticket: str, expires_at: int) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ticket": ticket, "expires_at": expires_at}
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _sign(self, ticket: str, nonce_str: str, time_stamp: int, url: str) -> str:
        sign_text = f"jsapi_ticket={ticket}&noncestr={nonce_str}&timestamp={time_stamp}&url={url}"
        return hashlib.sha1(sign_text.encode("utf-8")).hexdigest()
