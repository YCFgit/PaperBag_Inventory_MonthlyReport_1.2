from __future__ import annotations

from typing import Any

from src.models.schemas import DeliveryResult, ReportDocument
from src.services.dingtalk_file_sender import DingTalkFileSender


class SendService:
    def __init__(
        self,
        file_sender: DingTalkFileSender | None,
        enabled: bool,
        logger: Any | None = None,
    ) -> None:
        self.file_sender = file_sender
        self.enabled = enabled
        self.logger = logger

    def send_report(self, report: ReportDocument) -> list[DeliveryResult]:
        if not self.enabled:
            return [DeliveryResult(channel="disabled", success=True, message="DingTalk sending is disabled.")]

        if self.file_sender is None:
            return [DeliveryResult("conversation_file", False, "No DingTalk conversation file sender configured.")]
        return [self.file_sender.send_report_pdf(report)]
