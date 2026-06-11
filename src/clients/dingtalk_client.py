from __future__ import annotations

from typing import Any

import requests


class DingTalkClient:
    def __init__(self, timeout_seconds: int = 30) -> None:
        self.session = requests.Session()
        self.timeout_seconds = timeout_seconds

    def send_webhook_markdown(self, webhook: str, title: str, markdown: str) -> dict[str, Any]:
        response = self.session.post(
            webhook,
            json={
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": markdown,
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def send_openclaw_markdown(self, endpoint: str, token: str, title: str, markdown: str) -> dict[str, Any]:
        response = self.session.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "channel": "dingtalk",
                "message_type": "markdown",
                "title": title,
                "content": markdown,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
