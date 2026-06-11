from __future__ import annotations

from typing import Any

from src.clients.dingtalk_client import DingTalkClient
from src.models.schemas import DeliveryResult, ReportDocument


class SendService:
    def __init__(
        self,
        dingtalk_client: DingTalkClient,
        webhook: str,
        openclaw_endpoint: str,
        openclaw_token: str,
        enabled: bool,
        logger: Any,
    ) -> None:
        self.dingtalk_client = dingtalk_client
        self.webhook = webhook
        self.openclaw_endpoint = openclaw_endpoint
        self.openclaw_token = openclaw_token
        self.enabled = enabled
        self.logger = logger

    def send_report(self, report: ReportDocument) -> list[DeliveryResult]:
        if not self.enabled:
            return [DeliveryResult(channel="disabled", success=True, message="DingTalk sending is disabled.")]

        results: list[DeliveryResult] = []

        if self.openclaw_endpoint and self.openclaw_token:
            try:
                payload = self.dingtalk_client.send_openclaw_markdown(
                    self.openclaw_endpoint,
                    self.openclaw_token,
                    report.title,
                    report.markdown,
                )
                results.append(DeliveryResult("openclaw", True, "OpenClaw delivery succeeded.", payload))
                return results
            except Exception as exc:
                self.logger.warning("OpenClaw delivery failed, fallback to webhook: %s", exc)
                results.append(DeliveryResult("openclaw", False, str(exc)))

        if self.webhook:
            try:
                payload = self.dingtalk_client.send_webhook_markdown(self.webhook, report.title, report.markdown)
                results.append(DeliveryResult("webhook", True, "Webhook delivery succeeded.", payload))
            except Exception as exc:
                results.append(DeliveryResult("webhook", False, str(exc)))
        else:
            results.append(DeliveryResult("webhook", False, "No webhook configured."))
        return results
