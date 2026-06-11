from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.clients.auth_client import AuthClient


class TokenService:
    def __init__(
        self,
        auth_client: AuthClient,
        client_id: str,
        client_secret: str,
        cache_path: Path,
        logger: Any,
    ) -> None:
        self.auth_client = auth_client
        self.client_id = client_id
        self.client_secret = client_secret
        self.cache_path = cache_path
        self.logger = logger

    def get_valid_token(self, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = self._read_cache()
            if cached and datetime.now() < cached["expires_at"]:
                return cached["token"]

        payload = self.auth_client.fetch_token(self.client_id, self.client_secret)
        token, expires_in = self._parse_token_payload(payload)
        expires_at = datetime.now() + timedelta(seconds=max(expires_in - 120, 300))
        self._write_cache(token, expires_at)
        self.logger.info("Fetched fresh auth token from GuanYuan.")
        return token

    def refresh_token(self) -> str:
        return self.get_valid_token(force_refresh=True)

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return {
                "token": payload["token"],
                "expires_at": datetime.fromisoformat(payload["expires_at"]),
            }
        except Exception:
            return None

    def _write_cache(self, token: str, expires_at: datetime) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps({"token": token, "expires_at": expires_at.isoformat()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _parse_token_payload(self, payload: dict[str, Any]) -> tuple[str, int]:
        candidates = [
            (payload.get("access_token"), payload.get("expires_in")),
            (payload.get("client_token"), payload.get("expires_in")),
        ]

        data = payload.get("data")
        if isinstance(data, dict):
            candidates.extend(
                [
                    (data.get("access_token"), data.get("expires_in")),
                    (data.get("client_token"), data.get("expires_in")),
                ]
            )

        for token, expires_in in candidates:
            if token:
                return str(token), int(expires_in or 3600)

        raise KeyError(f"Token not found in auth payload: {json.dumps(self._redact_payload(payload), ensure_ascii=False)}")

    def _redact_payload(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            redacted: dict[str, Any] = {}
            for key, value in payload.items():
                if key.lower() in {"access_token", "client_token", "auth-token", "authorization", "client_secret"}:
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = self._redact_payload(value)
            return redacted
        if isinstance(payload, list):
            return [self._redact_payload(item) for item in payload]
        return payload
