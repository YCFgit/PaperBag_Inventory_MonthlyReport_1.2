from src.models.schemas import NormalizedDataset, ScopeConfig
from src.services.scope_filter_service import ScopeFilterService


class DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None


def test_scope_filter_service_filters_region_rows_and_drops_totals() -> None:
    service = ScopeFilterService(
        ScopeConfig(
            allowed_regions=["东北", "粤海"],
            allowed_brand_codes=["NK", "AD"],
            drop_total_rows_with_region_scope=True,
        ),
        {
            "region_keys": ["大区", "地区"],
            "brand_keys": ["brd_no"],
        },
        DummyLogger(),
    )
    datasets = [
        NormalizedDataset(
            role="regional_inventory_ratio",
            card_id="1",
            card_name="大区库销",
            section="inventory_diagnosis",
            rows=[
                {"地区": "总计", "期末库销比": 2.0},
                {"地区": "东北", "期末库销比": 2.7},
                {"地区": "粤海", "期末库销比": 3.1},
                {"地区": "西北", "期末库销比": 2.8},
            ],
            summary={"row_count": 4, "columns": ["地区", "期末库销比"]},
        )
    ]

    filtered = service.apply(datasets)

    assert [row["地区"] for row in filtered[0].rows] == ["东北", "粤海"]
    assert filtered[0].summary["scope_info"]["dropped_rows"] == 2


def test_scope_filter_service_reports_missing_brand_fields() -> None:
    service = ScopeFilterService(
        ScopeConfig(allowed_regions=["东北"], allowed_brand_codes=["NK"]),
        {
            "region_keys": ["大区", "地区"],
            "brand_keys": ["brd_no"],
        },
        DummyLogger(),
    )
    datasets = [
        NormalizedDataset(
            role="demo",
            card_id="1",
            card_name="演示",
            section="demo",
            rows=[{"地区": "东北", "值": 1}],
            summary={"row_count": 1, "columns": ["地区", "值"]},
        )
    ]

    filtered = service.apply(datasets)

    assert filtered[0].summary["scope_info"]["warnings"] == ["缺少可识别的品牌字段，无法在本地严格应用 brd_no 白名单。"]
