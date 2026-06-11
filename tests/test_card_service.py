from pathlib import Path

from requests import RequestException

from src.models.schemas import CardConfig, TaskContext
from src.services.card_service import CardService


class DummyClient:
    def __init__(self) -> None:
        self.calls = []

    def fetch_card_all_pages(
        self,
        card,
        token,
        user_id,
        resolved_request_body,
        resolved_dynamic_params,
        resolved_filters,
    ):
        self.calls.append(
            {
                "card_id": card.card_id,
                "resolved_request_body": resolved_request_body,
                "resolved_dynamic_params": resolved_dynamic_params,
                "resolved_filters": resolved_filters,
            }
        )
        return [{"code": 200, "rows": [{"地区": "东北"}]}]


class DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None


def test_card_service_skips_remote_fetch_for_local_only_cards(tmp_path: Path) -> None:
    client = DummyClient()
    service = CardService(client, "tester", DummyLogger())
    context = TaskContext(
        run_id="card1234",
        report_month="2026-03",
        generated_at=__import__("datetime").datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    cards = [
        CardConfig(card_id="local", name="本地卡", role="local_role", section="inventory_diagnosis", local_only=True),
        CardConfig(card_id="remote", name="远程卡", role="remote_role", section="inventory_diagnosis"),
    ]

    results = service.fetch_cards(
        cards=cards,
        token_getter=lambda force_refresh=False: "token",
        context=context,
        raw_data_dir=tmp_path / "raw",
    )

    assert [call["card_id"] for call in client.calls] == ["remote"]
    assert results[0].raw_payload["pages"] == []
    assert results[0].raw_payload["local_only"] is True
    assert results[1].raw_payload["pages"][0]["rows"][0]["地区"] == "东北"


def test_card_service_can_skip_remote_filters_by_default(tmp_path: Path) -> None:
    client = DummyClient()
    service = CardService(client, "tester", DummyLogger())
    context = TaskContext(
        run_id="card1234",
        report_month="2026-03",
        generated_at=__import__("datetime").datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    cards = [
        CardConfig(
            card_id="remote",
            name="远程卡",
            role="remote_role",
            section="inventory_diagnosis",
            filters=[{"fieldName": "查询期间", "operator": "EQ", "values": ["2026-03"]}],
        )
    ]

    service.fetch_cards(
        cards=cards,
        token_getter=lambda force_refresh=False: "token",
        context=context,
        raw_data_dir=tmp_path / "raw",
    )

    assert client.calls[0]["resolved_filters"] == []


def test_card_service_can_forward_remote_filters_when_enabled(tmp_path: Path) -> None:
    client = DummyClient()
    service = CardService(client, "tester", DummyLogger())
    context = TaskContext(
        run_id="card1234",
        report_month="2026-03",
        generated_at=__import__("datetime").datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    cards = [
        CardConfig(
            card_id="remote",
            name="远程卡",
            role="remote_role",
            section="inventory_diagnosis",
            filters=[{"fieldName": "查询期间", "operator": "EQ", "values": ["2026-03"]}],
        )
    ]

    service.fetch_cards(
        cards=cards,
        token_getter=lambda force_refresh=False: "token",
        context=context,
        raw_data_dir=tmp_path / "raw",
        apply_remote_filters=True,
    )

    assert client.calls[0]["resolved_filters"][0]["name"] == "查询期间"


def test_card_service_renders_dynamic_params_and_rich_filters(tmp_path: Path) -> None:
    client = DummyClient()
    service = CardService(client, "tester", DummyLogger())
    context = TaskContext(
        run_id="card1234",
        report_month="2026-05",
        generated_at=__import__("datetime").datetime(2026, 6, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    cards = [
        CardConfig(
            card_id="remote",
            name="远程卡",
            role="remote_role",
            section="inventory_diagnosis",
            request_body={"view": "GRAPH"},
            dynamic_params=[
                {"name": "本期开始日期", "defaultValue": "{{report_month_start}}"},
                {"name": "本期结束日期", "defaultValue": "{{report_month_end}}"},
                {"name": "历史开始日期", "defaultValue": "{{fiscal_year_start}}"},
            ],
            filters=[
                {
                    "name": "日期",
                    "filterType": "BT",
                    "filterValue": ["{{report_month_start}}", "{{report_month_end}}"],
                    "fdId": "date_field",
                }
            ],
        )
    ]

    service.fetch_cards(
        cards=cards,
        token_getter=lambda force_refresh=False: "token",
        context=context,
        raw_data_dir=tmp_path / "raw",
        apply_remote_filters=True,
    )

    assert client.calls[0]["resolved_request_body"]["view"] == "GRAPH"
    assert client.calls[0]["resolved_dynamic_params"][0]["defaultValue"] == "2026-05-01"
    assert client.calls[0]["resolved_dynamic_params"][1]["defaultValue"] == "2026-05-31"
    assert client.calls[0]["resolved_dynamic_params"][2]["defaultValue"] == "2025-03-01"
    assert client.calls[0]["resolved_filters"][0]["fdId"] == "date_field"
    assert client.calls[0]["resolved_filters"][0]["filterType"] == "GE"
    assert client.calls[0]["resolved_filters"][0]["filterValue"] == ["2026-05-01"]
    assert client.calls[0]["resolved_filters"][1]["filterType"] == "LE"
    assert client.calls[0]["resolved_filters"][1]["filterValue"] == ["2026-05-31"]


def test_card_service_redacts_secrets_from_request_error_logs() -> None:
    service = CardService(DummyClient(), "tester", DummyLogger())

    class FakeResponse:
        status_code = 500
        text = "request failed?client_secret=abc123&auth-token=xyz789"

    exc = RequestException("boom")
    exc.response = FakeResponse()

    page = service._build_request_error_page(exc, "request_exception")

    assert "abc123" not in page["msg"]
    assert "xyz789" not in page["msg"]
    assert "[REDACTED]" in page["msg"]
