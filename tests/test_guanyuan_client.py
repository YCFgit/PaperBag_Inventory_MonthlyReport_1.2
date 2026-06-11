from src.clients.guanyuan_client import normalize_filters


def test_normalize_filters_converts_legacy_filter_shape() -> None:
    assert normalize_filters(
        [
            {"fieldName": "日期 (月)", "operator": "EQ", "values": ["2026-04"]},
        ]
    ) == [
        {"name": "日期 (月)", "filterType": "EQ", "filterValue": ["2026-04"]},
    ]


def test_normalize_filters_expands_between_filter() -> None:
    assert normalize_filters(
        [
            {"fieldName": "查询期间", "operator": "BETWEEN", "values": ["2026/04/01", "2026/04/30"]},
        ]
    ) == [
        {"name": "查询期间", "filterType": "GE", "filterValue": ["2026/04/01"]},
        {"name": "查询期间", "filterType": "LE", "filterValue": ["2026/04/30"]},
    ]


def test_normalize_filters_expands_bt_filter_in_native_shape() -> None:
    assert normalize_filters(
        [
            {"name": "日期", "filterType": "BT", "filterValue": ["2026-05-01", "2026-05-31"], "fdId": "date_fd"},
        ]
    ) == [
        {"name": "日期", "filterType": "GE", "filterValue": ["2026-05-01"], "fdId": "date_fd"},
        {"name": "日期", "filterType": "LE", "filterValue": ["2026-05-31"], "fdId": "date_fd"},
    ]
