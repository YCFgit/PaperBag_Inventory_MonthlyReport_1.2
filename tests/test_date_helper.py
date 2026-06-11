from src.utils.date_helper import resolve_month_boundaries


def test_resolve_month_boundaries_exposes_expected_template_variables() -> None:
    values = resolve_month_boundaries("2026-03")

    assert values["report_month_start"] == "2026-03-01"
    assert values["report_month_end"] == "2026-03-31"
    assert values["previous_month_start"] == "2026-02-01"
    assert values["previous_month_end"] == "2026-02-28"
    assert values["previous_year_same_month_start"] == "2025-03-01"
    assert values["previous_year_same_month_end"] == "2025-03-31"
    assert values["fiscal_year_start"] == "2025-03-01"
    assert values["rolling_30d_start"] == "2026-03-02"
    assert values["rolling_30d_end"] == "2026-03-31"


def test_resolve_month_boundaries_exposes_april_2026_comparison_dates() -> None:
    values = resolve_month_boundaries("2026-04")

    assert values["report_month_start"] == "2026-04-01"
    assert values["report_month_end"] == "2026-04-30"
    assert values["previous_year_same_month_start"] == "2025-04-01"
    assert values["previous_year_same_month_end"] == "2025-04-30"
