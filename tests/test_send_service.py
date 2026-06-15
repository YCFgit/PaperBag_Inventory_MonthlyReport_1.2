from pathlib import Path

from src.models.schemas import DeliveryResult
from src.models.schemas import ReportDocument
from src.services.send_service import SendService


class DummyFileSender:
    def __init__(self) -> None:
        self.calls = 0
        self.success = True

    def send_report_pdf(self, report: ReportDocument):
        self.calls += 1
        if not self.success:
            return DeliveryResult("conversation_file", False, "conversation file failed")
        return DeliveryResult("conversation_file", True, "ok", {"file": report.output_path.with_suffix(".pdf").name})


def build_report() -> ReportDocument:
    return ReportDocument(
        report_month="2026-05",
        title="测试月报",
        markdown="# 测试月报\n",
        output_path=Path("data/reports/demo.md"),
        executive_summary="summary",
    )


def test_send_service_reports_missing_conversation_sender_when_not_configured() -> None:
    service = SendService(
        file_sender=None,
        enabled=True,
    )

    results = service.send_report(build_report())

    assert len(results) == 1
    assert results[0].channel == "conversation_file"
    assert results[0].success is False
    assert results[0].message == "No DingTalk conversation file sender configured."


def test_send_service_returns_conversation_delivery_failure() -> None:
    file_sender = DummyFileSender()
    file_sender.success = False
    service = SendService(
        file_sender=file_sender,
        enabled=True,
    )

    results = service.send_report(build_report())

    assert [result.channel for result in results] == ["conversation_file"]
    assert results[0].success is False
    assert results[0].message == "conversation file failed"
    assert file_sender.calls == 1


def test_send_service_uses_conversation_file_only_mode_when_available() -> None:
    file_sender = DummyFileSender()
    service = SendService(
        file_sender=file_sender,
        enabled=True,
    )

    results = service.send_report(build_report())

    assert len(results) == 1
    assert results[0].channel == "conversation_file"
    assert results[0].success is True
    assert file_sender.calls == 1
