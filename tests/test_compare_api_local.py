import importlib.util
from pathlib import Path
from types import SimpleNamespace

from src.models.schemas import NormalizedDataset


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_api_local.py"
MODULE_SPEC = importlib.util.spec_from_file_location("compare_api_local", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
compare_api_local = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(compare_api_local)
_compare_card = compare_api_local._compare_card


def _build_dataset(card_id: str, role: str, rows: list[dict[str, object]]) -> NormalizedDataset:
    return NormalizedDataset(
        role=role,
        card_id=card_id,
        card_name=card_id,
        section="demo",
        rows=rows,
        summary={"row_count": len(rows), "columns": sorted({key for row in rows for key in row.keys()}), "application_errors": []},
        raw_payload={},
    )


def test_compare_card_marks_near_match_for_small_numeric_deltas() -> None:
    card = SimpleNamespace(card_id="xe5da9d423db44bbe96028ad", name="demo", role="regional_inventory_ratio")
    api_dataset = _build_dataset(
        card.card_id,
        card.role,
        [
            {"原销售大区": "华北二区", "期末业务库存量": 500357, "期末近30天累计纸袋销售量": 301182, "进销比": 0.386477},
            {"原销售大区": "华南一区", "期末业务库存量": 415757, "期末近30天累计纸袋销售量": 146590, "进销比": 1.028037},
        ],
    )
    local_dataset = _build_dataset(
        card.card_id,
        card.role,
        [
            {"原销售大区": "华北二区", "期末业务库存量": 500358, "期末近30天累计纸袋销售量": 301181, "进销比": 0.386479},
            {"原销售大区": "华南一区", "期末业务库存量": 415757, "期末近30天累计纸袋销售量": 146590, "进销比": 1.028037},
        ],
    )

    result = _compare_card(card, api_dataset, local_dataset, SimpleNamespace(archived_path=Path("/tmp/demo.json")))

    assert result["status"] == "near_match"
    assert result["near_match_notes"]


def test_compare_card_marks_near_match_when_only_derived_local_columns_remain() -> None:
    card = SimpleNamespace(card_id="j21833508e589464c922d381", name="demo", role="consumption_ratio_monthly")
    api_dataset = _build_dataset(
        card.card_id,
        card.role,
        [
            {"日期 (月)": "2026-05", "纸袋配比": 0.602884, "纸袋配比-不含团购": 0.731757, "同期": 0.782795, "同比": -0.0652},
            {"日期 (月)": "2025-05", "纸袋配比": 0.663288, "纸袋配比-不含团购": 0.782795, "同期": None, "同比": None},
        ],
    )
    local_dataset = _build_dataset(
        card.card_id,
        card.role,
        [
            {
                "日期 (月)": "2026-05",
                "纸袋配比": 0.602884,
                "纸袋配比-不含团购": 0.731773,
                "同期": 0.782795,
                "同比": -0.065178,
                "纸袋配比-同期": 0.663288,
                "纸袋配比-同比": -0.091067,
            },
            {
                "日期 (月)": "2025-05",
                "纸袋配比": 0.663288,
                "纸袋配比-不含团购": 0.782795,
                "同期": None,
                "同比": None,
                "纸袋配比-同期": None,
                "纸袋配比-同比": None,
            },
        ],
    )

    result = _compare_card(card, api_dataset, local_dataset, SimpleNamespace(archived_path=Path("/tmp/demo.json")))

    assert result["status"] == "near_match"
    assert "衍生列" in " ".join(result["near_match_notes"])


def test_compare_card_keeps_partial_match_for_material_difference() -> None:
    card = SimpleNamespace(card_id="demo", name="demo", role="demo")
    api_dataset = _build_dataset(card.card_id, card.role, [{"日期": "2026-05", "值": 10.0}])
    local_dataset = _build_dataset(card.card_id, card.role, [{"日期": "2026-05", "值": 12.0}])

    result = _compare_card(card, api_dataset, local_dataset, SimpleNamespace(archived_path=Path("/tmp/demo.json")))

    assert result["status"] == "mismatch"
    assert result["near_match_notes"] == []
