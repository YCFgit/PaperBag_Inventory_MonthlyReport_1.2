from src.models.schemas import NormalizedDataset
from src.services.integration_service import IntegrationService


class DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None


def test_summarize_dataset_health_marks_application_errors() -> None:
    service = IntegrationService(DummyLogger())
    datasets = [
        NormalizedDataset(
            role="demo",
            card_id="1",
            card_name="演示卡片",
            section="demo",
            rows=[],
            summary={
                "row_count": 0,
                "columns": [],
                "application_errors": [{"page_index": 0, "code": 500, "msg": "boom"}],
            },
        )
    ]

    health = service.summarize_dataset_health(datasets)

    assert health["dataset_statuses"][0]["status"] == "error"
    assert "应用层错误" in health["warnings"][0]


def test_summarize_dataset_health_marks_expected_empty_cards() -> None:
    service = IntegrationService(DummyLogger())
    datasets = [
        NormalizedDataset(
            role="demo",
            card_id="1",
            card_name="演示卡片",
            section="demo",
            rows=[],
            summary={
                "row_count": 0,
                "columns": [],
                "application_errors": [],
                "allow_empty_result": True,
                "empty_reason": "本期无异常属于正常现象",
            },
        )
    ]

    health = service.summarize_dataset_health(datasets)

    assert health["dataset_statuses"][0]["status"] == "empty_allowed"
    assert "正常现象" in health["warnings"][0]


def test_summarize_dataset_health_separates_fallback_and_hard_errors() -> None:
    service = IntegrationService(DummyLogger())
    datasets = [
        NormalizedDataset(
            role="fallback_demo",
            card_id="1",
            card_name="兜底卡",
            section="demo",
            rows=[{"值": 1}],
            summary={
                "row_count": 1,
                "columns": ["值"],
                "application_errors": [{"page_index": 0, "code": 500, "msg": "boom"}],
                "fallback_info": {"source_type": "card_collection"},
            },
        ),
        NormalizedDataset(
            role="error_demo",
            card_id="2",
            card_name="失败卡",
            section="demo",
            rows=[],
            summary={
                "row_count": 0,
                "columns": [],
                "application_errors": [{"page_index": 0, "code": 500, "msg": "boom"}],
            },
        ),
    ]

    health = service.summarize_dataset_health(datasets)

    assert health["dataset_statuses"][0]["status"] == "fallback"
    assert health["dataset_statuses"][1]["status"] == "error"
    assert "已自动切换为本地卡片集合兜底" in health["warnings"][0]
    assert "暂无可用兜底" in health["warnings"][1]
