from __future__ import annotations

from types import SimpleNamespace

from src.main import _run_diagnosis


class DummyLogger:
    def __init__(self) -> None:
        self.infos: list[tuple[object, ...]] = []
        self.warnings: list[tuple[object, ...]] = []

    def info(self, *args: object, **_kwargs: object) -> None:
        self.infos.append(args)

    def warning(self, *args: object, **_kwargs: object) -> None:
        self.warnings.append(args)


class DiagnosisServiceStub:
    def __init__(self) -> None:
        self.build_actual_calls = 0
        self.build_diagnosis_calls = 0
        self.load_input_csv_rows_calls = 0
        self.extract_model_card_rows_calls = 0

    def load_theory_input_rows(self, report_month: str) -> list[dict[str, object]]:
        assert report_month == "2026-05"
        return [{
            "region": "华南一区",
            "period": report_month,
            "xs_theory_qty": 1,
            "s_theory_qty": 2,
            "m_theory_qty": 3,
            "l_theory_qty": 4,
            "xl_theory_qty": 5,
            "total_theory_qty": 15,
        }]

    def load_input_csv_rows(self, report_month: str) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        self.load_input_csv_rows_calls += 1
        assert report_month == "2026-05"
        return (
            [{"region": "华南一区", "period": report_month, "total_theory_qty": 999}],
            [{"region": "华南一区", "period": report_month, "total_actual_qty": 999}],
            [{"region": "华南一区", "period": report_month, "total_stock_qty": 999}],
        )

    def extract_model_card_rows(self, dataset: object) -> list[dict[str, object]]:
        self.extract_model_card_rows_calls += 1
        raw_payload = getattr(dataset, "raw_payload")
        assert raw_payload["source"] == "raw-card"
        return [{"row": "from-a597-raw"}]

    def build_actual_and_stock_rows_from_model_card(
        self,
        rows: list[dict[str, object]],
        report_month: str,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        self.build_actual_calls += 1
        assert rows == [{"row": "from-a597-raw"}]
        assert report_month == "2026-05"
        return (
            [{"region": "华南一区", "period": report_month, "total_actual_qty": 123}],
            [{"region": "华南一区", "period": report_month, "total_stock_qty": 456}],
        )

    def build_diagnosis(
        self,
        theory_rows: list[dict[str, object]],
        actual_rows: list[dict[str, object]],
        stock_rows: list[dict[str, object]],
        report_month: str,
    ) -> dict[str, object]:
        self.build_diagnosis_calls += 1
        if actual_rows == [{"region": "华南一区", "period": report_month, "total_actual_qty": 123}]:
            assert theory_rows[0]["total_theory_qty"] == 15
            assert stock_rows == [{"region": "华南一区", "period": report_month, "total_stock_qty": 456}]
            return {"total_regions": 1, "source": "a597"}

        assert theory_rows == [{"region": "华南一区", "period": report_month, "total_theory_qty": 999}]
        assert actual_rows == [{"region": "华南一区", "period": report_month, "total_actual_qty": 999}]
        assert stock_rows == [{"region": "华南一区", "period": report_month, "total_stock_qty": 999}]
        return {"total_regions": 1, "source": "local_csv"}


def test_run_diagnosis_prefers_a597_actual_and_stock_over_local_csv_inputs() -> None:
    service = DiagnosisServiceStub()
    logger = DummyLogger()
    normalized = [SimpleNamespace(
        role="regional_model_purchase_analysis",
        rows=[{"row": "from-local-aligned-a597"}],
        raw_payload={"source": "raw-card"},
    )]

    result = _run_diagnosis(service, "2026-05", logger, normalized)

    assert result == {"total_regions": 1, "source": "a597"}
    assert service.build_actual_calls == 1
    assert service.build_diagnosis_calls == 1
    assert service.extract_model_card_rows_calls == 1
    assert service.load_input_csv_rows_calls == 0


def test_run_diagnosis_falls_back_to_local_csv_when_a597_card_is_missing() -> None:
    service = DiagnosisServiceStub()
    logger = DummyLogger()

    result = _run_diagnosis(service, "2026-05", logger, [])

    assert result == {"total_regions": 1, "source": "local_csv"}
    assert service.build_actual_calls == 0
    assert service.build_diagnosis_calls == 1
    assert service.load_input_csv_rows_calls == 1
