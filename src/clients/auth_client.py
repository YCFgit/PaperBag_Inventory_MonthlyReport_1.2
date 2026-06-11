from __future__ import annotations

from typing import Any

import requests


class AuthClient:
    def __init__(self, base_url: str, auth_token_path: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token_path = auth_token_path
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def fetch_token(self, client_id: str, client_secret: str) -> dict[str, Any]:
        params = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        response = self.session.get(
            f"{self.base_url}{self.auth_token_path}",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
