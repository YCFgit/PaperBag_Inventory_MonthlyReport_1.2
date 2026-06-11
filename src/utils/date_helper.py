from __future__ import annotations

import calendar
from datetime import datetime, timedelta


def resolve_month_boundaries(report_month: str) -> dict[str, str]:
    year, month = map(int, report_month.split("-"))
    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1])
    previous_month_last_day = first_day - timedelta(days=1)
    previous_month_first_day = previous_month_last_day.replace(day=1)
    previous_year_same_month_first_day = datetime(year - 1, month, 1)
    previous_year_same_month_last_day = datetime(year - 1, month, calendar.monthrange(year - 1, month)[1])
    fiscal_year_start = datetime(year - 1, 3, 1)
    rolling_30d_start = last_day - timedelta(days=29)
    return {
        "report_month": report_month,
        "report_month_start": first_day.strftime("%Y-%m-%d"),
        "report_month_end": last_day.strftime("%Y-%m-%d"),
        "previous_month_start": previous_month_first_day.strftime("%Y-%m-%d"),
        "previous_month_end": previous_month_last_day.strftime("%Y-%m-%d"),
        "previous_year_same_month_start": previous_year_same_month_first_day.strftime("%Y-%m-%d"),
        "previous_year_same_month_end": previous_year_same_month_last_day.strftime("%Y-%m-%d"),
        "fiscal_year_start": fiscal_year_start.strftime("%Y-%m-%d"),
        "rolling_30d_start": rolling_30d_start.strftime("%Y-%m-%d"),
        "rolling_30d_end": last_day.strftime("%Y-%m-%d"),
    }


def resolve_report_month(explicit_month: str | None = None, now: datetime | None = None) -> str:
    if explicit_month:
        return explicit_month
    current = now or datetime.now()
    first_day_of_current_month = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month_last_day = first_day_of_current_month - timedelta(days=1)
    return previous_month_last_day.strftime("%Y-%m")


def month_label(report_month: str) -> str:
    year, month = report_month.split("-")
    return f"{year}年{int(month)}月"
