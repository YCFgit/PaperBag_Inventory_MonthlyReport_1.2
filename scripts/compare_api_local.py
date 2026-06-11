from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.clients.auth_client import AuthClient
from src.clients.guanyuan_client import GuanYuanClient
from src.main import _save_json
from src.models.schemas import NormalizedDataset, TaskContext
from src.services.card_collection_fallback_service import CardCollectionFallbackService
from src.services.card_service import CardService
from src.services.scope_filter_service import ScopeFilterService
from src.services.supplemental_data_service import SupplementalDataService
from src.services.token_service import TokenService
from src.services.transform_service import TransformService
from src.utils.config import load_app_config, load_cards, load_field_aliases
from src.utils.date_helper import resolve_report_month
from src.utils.logger import configure_logger


FORECAST_CARD_ID = "u114a0c72ae524037a53c8d1"
FLOAT_COMPARISON_TOLERANCE = 0.00005
INTEGER_COMPARISON_TOLERANCE = 1.0
DERIVED_LOCAL_ONLY_COLUMNS_BY_CARD = {
    "j21833508e589464c922d381": {"纸袋配比-同期", "纸袋配比-同比"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare API card results with local card collection workbooks")
    parser.add_argument("--month", required=False, help="Report month in YYYY-MM format")
    parser.add_argument("--run-id", required=False, help="Optional run id for archived outputs")
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    app_config = load_app_config(project_root)
    report_month = resolve_report_month(args.month)
    run_id = args.run_id or f"cmp{uuid.uuid4().hex[:8]}"
    logger = configure_logger(app_config.runtime_root, run_id)
    logger.info("Starting API/local comparison for report_month=%s", report_month)

    cards = load_cards(app_config.cards_path)
    field_aliases = load_field_aliases(app_config.field_aliases_path)
    transform_service = TransformService()
    scope_filter_service = ScopeFilterService(app_config.scope_config, field_aliases, logger)
    fallback_service = CardCollectionFallbackService(app_config.card_collection_dir, logger)
    supplemental_service = SupplementalDataService(
        workbook_glob=app_config.forecast_workbook_glob,
        sheet_name=app_config.forecast_workbook_sheet,
        logger=logger,
        workbook_path=app_config.forecast_workbook_path,
        paper_bag_specs_workbook_path=app_config.paper_bag_specs_workbook_path,
        paper_bag_specs_sheet_name=app_config.paper_bag_specs_workbook_sheet,
    )

    api_cards = [replace(card, enabled=True) for card in cards if card.enabled and not card.local_only]
    local_only_cards = [card for card in cards if card.local_only or not card.enabled]

    auth_client = AuthClient(app_config.guanyuan_base_url, app_config.auth_token_path)
    guanyuan_client = GuanYuanClient(app_config.guanyuan_base_url, app_config.data_card_path_template)
    token_service = TokenService(
        auth_client=auth_client,
        client_id=app_config.guanyuan_client_id,
        client_secret=app_config.guanyuan_client_secret,
        cache_path=app_config.processed_data_dir / "token_cache.json",
        logger=logger,
    )
    card_service = CardService(guanyuan_client, app_config.guanyuan_user_id, logger)

    context = TaskContext(
        run_id=run_id,
        report_month=report_month,
        generated_at=datetime.now(),
        project_root=project_root,
    )

    raw_results = card_service.fetch_cards(
        cards=api_cards,
        token_getter=lambda force_refresh=False: token_service.get_valid_token(force_refresh=force_refresh),
        context=context,
        raw_data_dir=app_config.raw_data_dir,
        apply_remote_filters=True,
    )

    api_datasets = scope_filter_service.apply(transform_service.normalize(raw_results))
    api_by_card_id = {dataset.card_id: dataset for dataset in api_datasets}
    raw_by_card_id = {item.card.card_id: item for item in raw_results}

    local_datasets = _load_local_collection_datasets(
        cards=api_cards,
        fallback_service=fallback_service,
        scope_filter_service=scope_filter_service,
        report_month=report_month,
    )
    local_by_card_id = {dataset.card_id: dataset for dataset in local_datasets}

    comparison_items = []
    for card in api_cards:
        api_dataset = api_by_card_id.get(card.card_id)
        local_dataset = local_by_card_id.get(card.card_id)
        raw_result = raw_by_card_id.get(card.card_id)
        comparison_items.append(_compare_card(card, api_dataset, local_dataset, raw_result))

    local_only_statuses = _build_local_only_statuses(
        local_only_cards=local_only_cards,
        fallback_service=fallback_service,
        supplemental_service=supplemental_service,
        scope_filter_service=scope_filter_service,
        report_month=report_month,
    )

    summary = _build_summary(report_month, run_id, comparison_items, local_only_statuses)
    output_dir = app_config.processed_data_dir / "inspection" / report_month
    output_dir.mkdir(parents=True, exist_ok=True)

    output_json = output_dir / f"{run_id}_api_local_compare.json"
    output_md = output_dir / f"{run_id}_api_local_compare.md"
    _save_json(
        output_json,
        {
            "summary": summary,
            "cards": comparison_items,
            "local_only_cards": local_only_statuses,
        },
    )
    output_md.write_text(_render_markdown(summary, comparison_items, local_only_statuses), encoding="utf-8")

    print(json.dumps({"json": str(output_json), "markdown": str(output_md), "run_id": run_id}, ensure_ascii=False))


def _load_local_collection_datasets(
    cards: list[Any],
    fallback_service: CardCollectionFallbackService,
    scope_filter_service: ScopeFilterService,
    report_month: str,
) -> list[NormalizedDataset]:
    datasets: list[NormalizedDataset] = []
    for card in cards:
        workbook_path = fallback_service.collection_dir / f"{card.card_id}.xlsx"
        if not workbook_path.exists():
            continue
        if fallback_service.__class__.__dict__.get("_resolve_sheet") is None:
            continue
        workbook = __import__("openpyxl").load_workbook(workbook_path, read_only=True, data_only=True)
        worksheet = fallback_service._resolve_sheet(workbook, card.card_id)
        if worksheet is None:
            continue
        rows = fallback_service._extract_rows(worksheet)
        rows = fallback_service._normalize_rows(card.card_id, rows, report_month=report_month)
        dataset = NormalizedDataset(
            role=card.role,
            card_id=card.card_id,
            card_name=card.name,
            section=card.section,
            rows=rows,
            summary={
                "row_count": len(rows),
                "columns": sorted({key for row in rows for key in row.keys()}),
            },
            raw_payload={
                "source_type": "card_collection",
                "workbook_path": str(workbook_path),
                "sheet_name": worksheet.title,
            },
        )
        aligned_rows = fallback_service._month_aligned_rows(dataset, rows, report_month)
        if aligned_rows is not None:
            dataset = replace(
                dataset,
                rows=aligned_rows,
                summary={
                    "row_count": len(aligned_rows),
                    "columns": sorted({key for row in aligned_rows for key in row.keys()}),
                    "fallback_info": {
                        "source_type": "card_collection_month_alignment",
                        "report_month": report_month,
                    },
                },
            )
        datasets.append(dataset)
    return scope_filter_service.apply(datasets)


def _build_local_only_statuses(
    local_only_cards: list[Any],
    fallback_service: CardCollectionFallbackService,
    supplemental_service: SupplementalDataService,
    scope_filter_service: ScopeFilterService,
    report_month: str,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    forecast_datasets = {
        dataset.card_id: dataset
        for dataset in scope_filter_service.apply(supplemental_service.load_datasets(report_month=report_month))
    }
    for card in local_only_cards:
        if card.card_id == FORECAST_CARD_ID:
            dataset = forecast_datasets.get(card.card_id)
            statuses.append(
                {
                    "card_id": card.card_id,
                    "card_name": card.name,
                    "role": card.role,
                    "mode": "local_excel_only",
                    "status": "ready" if dataset and dataset.rows else "missing_or_empty",
                    "row_count": len(dataset.rows) if dataset else 0,
                    "workbook_path": dataset.raw_payload.get("workbook_path") if dataset else "",
                }
            )
            continue

        workbook_path = fallback_service.collection_dir / f"{card.card_id}.xlsx"
        row_count = 0
        status = "missing_workbook"
        if workbook_path.exists():
            workbook = __import__("openpyxl").load_workbook(workbook_path, read_only=True, data_only=True)
            worksheet = fallback_service._resolve_sheet(workbook, card.card_id)
            if worksheet is not None:
                rows = fallback_service._extract_rows(worksheet)
                scoped = scope_filter_service.apply(
                    [
                        NormalizedDataset(
                            role=card.role,
                            card_id=card.card_id,
                            card_name=card.name,
                            section=card.section,
                            rows=rows,
                            summary={},
                            raw_payload={"workbook_path": str(workbook_path), "sheet_name": worksheet.title},
                        )
                    ]
                )
                row_count = len(scoped[0].rows)
                status = "ready" if row_count else "empty"
        statuses.append(
            {
                "card_id": card.card_id,
                "card_name": card.name,
                "role": card.role,
                "mode": "local_excel_only",
                "status": status,
                "row_count": row_count,
                "workbook_path": str(workbook_path),
            }
        )
    return statuses


def _compare_card(
    card: Any,
    api_dataset: NormalizedDataset | None,
    local_dataset: NormalizedDataset | None,
    raw_result: Any | None,
) -> dict[str, Any]:
    api_rows = list(api_dataset.rows if api_dataset else [])
    local_rows = list(local_dataset.rows if local_dataset else [])
    api_columns = sorted({key for row in api_rows for key in row.keys()})
    local_columns = sorted({key for row in local_rows for key in row.keys()})
    common_columns = sorted(set(api_columns) & set(local_columns))
    api_only_columns = sorted(set(api_columns) - set(local_columns))
    local_only_columns = sorted(set(local_columns) - set(api_columns))

    api_counter = Counter(_build_signature(row, common_columns) for row in api_rows) if common_columns else Counter()
    local_counter = Counter(_build_signature(row, common_columns) for row in local_rows) if common_columns else Counter()
    exact_match_rows = sum(min(api_counter[key], local_counter[key]) for key in api_counter.keys() | local_counter.keys())
    application_errors = list(api_dataset.summary.get("application_errors", []) if api_dataset else [])
    near_match, near_match_notes = _assess_near_match(
        card_id=card.card_id,
        api_rows=api_rows,
        local_rows=local_rows,
        common_columns=common_columns,
        api_only_columns=api_only_columns,
        local_only_columns=local_only_columns,
        application_errors=application_errors,
    )

    api_row_count = len(api_rows)
    local_row_count = len(local_rows)

    if application_errors and api_row_count == 0:
        status = "api_error"
    elif not local_dataset:
        status = "missing_local_workbook"
    elif api_row_count == 0 and local_row_count == 0:
        status = "both_empty"
    elif api_row_count == local_row_count and api_row_count > 0 and exact_match_rows == api_row_count:
        status = "exact_match"
    elif near_match:
        status = "near_match"
    elif min(api_row_count, local_row_count) > 0 and exact_match_rows == min(api_row_count, local_row_count):
        status = "subset_match"
    elif exact_match_rows > 0:
        status = "partial_match"
    else:
        status = "mismatch"

    common_match_rate_api = (exact_match_rows / api_row_count) if api_row_count else None
    common_match_rate_local = (exact_match_rows / local_row_count) if local_row_count else None

    return {
        "card_id": card.card_id,
        "card_name": card.name,
        "role": card.role,
        "status": status,
        "api_row_count": api_row_count,
        "local_row_count": local_row_count,
        "exact_match_rows_on_common_columns": exact_match_rows,
        "common_match_rate_api": common_match_rate_api,
        "common_match_rate_local": common_match_rate_local,
        "api_columns": api_columns,
        "local_columns": local_columns,
        "common_columns": common_columns,
        "api_only_columns": api_only_columns,
        "local_only_columns": local_only_columns,
        "api_application_errors": application_errors,
        "api_archived_path": str(raw_result.archived_path) if raw_result and raw_result.archived_path else "",
        "local_workbook_path": local_dataset.raw_payload.get("workbook_path") if local_dataset else "",
        "local_sheet_name": local_dataset.raw_payload.get("sheet_name") if local_dataset else "",
        "local_fallback_info": local_dataset.summary.get("fallback_info", {}) if local_dataset else {},
        "numeric_column_checks": _compare_numeric_columns(api_rows, local_rows, common_columns),
        "api_unmatched_samples": _collect_unmatched_samples(api_rows, common_columns, local_counter),
        "local_unmatched_samples": _collect_unmatched_samples(local_rows, common_columns, api_counter),
        "api_scope_info": api_dataset.summary.get("scope_info", {}) if api_dataset else {},
        "local_scope_info": local_dataset.summary.get("scope_info", {}) if local_dataset else {},
        "near_match_notes": near_match_notes,
    }


def _build_signature(row: dict[str, Any], columns: list[str]) -> str:
    payload = {column: _canonicalize_value(row.get(column)) for column in columns}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _canonicalize_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            if "." in stripped:
                return round(float(stripped.replace(",", "")), 6)
            return int(stripped.replace(",", ""))
        except ValueError:
            return stripped
    return str(value)


def _collect_unmatched_samples(
    rows: list[dict[str, Any]],
    common_columns: list[str],
    other_counter: Counter[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not common_columns:
        return []
    remaining = Counter(other_counter)
    samples: list[dict[str, Any]] = []
    for row in rows:
        signature = _build_signature(row, common_columns)
        if remaining[signature] > 0:
            remaining[signature] -= 1
            continue
        samples.append({column: _canonicalize_value(row.get(column)) for column in common_columns[:12]})
        if len(samples) >= limit:
            break
    return samples


def _compare_numeric_columns(
    api_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    common_columns: list[str],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for column in common_columns:
        api_values = [_as_float(row.get(column)) for row in api_rows]
        local_values = [_as_float(row.get(column)) for row in local_rows]
        api_numbers = [value for value in api_values if value is not None]
        local_numbers = [value for value in local_values if value is not None]
        if not api_numbers and not local_numbers:
            continue
        checks.append(
            {
                "column": column,
                "api_count": len(api_numbers),
                "local_count": len(local_numbers),
                "api_sum": round(sum(api_numbers), 6) if api_numbers else None,
                "local_sum": round(sum(local_numbers), 6) if local_numbers else None,
                "api_min": round(min(api_numbers), 6) if api_numbers else None,
                "api_max": round(max(api_numbers), 6) if api_numbers else None,
                "local_min": round(min(local_numbers), 6) if local_numbers else None,
                "local_max": round(max(local_numbers), 6) if local_numbers else None,
                "sum_delta": round(sum(api_numbers) - sum(local_numbers), 6) if api_numbers or local_numbers else None,
            }
        )
    return checks[:20]


def _as_float(value: Any) -> float | None:
    canonical = _canonicalize_value(value)
    if isinstance(canonical, (int, float)):
        return float(canonical)
    return None


def _assess_near_match(
    card_id: str,
    api_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    common_columns: list[str],
    api_only_columns: list[str],
    local_only_columns: list[str],
    application_errors: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    if application_errors or not api_rows or not local_rows:
        return False, []
    if len(api_rows) != len(local_rows) or not common_columns or api_only_columns:
        return False, []

    allowed_local_only = DERIVED_LOCAL_ONLY_COLUMNS_BY_CARD.get(card_id, set())
    disallowed_local_only = [column for column in local_only_columns if column not in allowed_local_only]
    if disallowed_local_only:
        return False, []

    identifier_columns = _select_identifier_columns(api_rows, local_rows, common_columns)
    if not identifier_columns:
        return False, []

    api_by_key = _build_rows_by_key(api_rows, identifier_columns)
    local_by_key = _build_rows_by_key(local_rows, identifier_columns)
    if api_by_key is None or local_by_key is None or set(api_by_key) != set(local_by_key):
        return False, []

    for key, api_row in api_by_key.items():
        local_row = local_by_key[key]
        for column in common_columns:
            if not _values_approximately_equal(api_row.get(column), local_row.get(column)):
                return False, []

    notes = [
        "按标识列逐行比较通过，差异落在容差范围内。",
        f"整数允许差值 <= {int(INTEGER_COMPARISON_TOLERANCE)}，浮点允许差值 <= {FLOAT_COMPARISON_TOLERANCE:.5f}。",
    ]
    if local_only_columns:
        notes.append(f"本地额外列视为衍生列：{', '.join(local_only_columns)}。")
    notes.append(f"用于逐行对齐的标识列：{', '.join(identifier_columns)}。")
    return True, notes


def _select_identifier_columns(
    api_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    common_columns: list[str],
) -> list[str]:
    identifier_columns: list[str] = []
    combined_rows = [*api_rows, *local_rows]
    for column in common_columns:
        values = [row.get(column) for row in combined_rows if row.get(column) is not None]
        if values and all(_as_float(value) is None for value in values):
            identifier_columns.append(column)
    return identifier_columns


def _build_rows_by_key(
    rows: list[dict[str, Any]],
    identifier_columns: list[str],
) -> dict[str, dict[str, Any]] | None:
    keyed_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        signature = _build_signature(row, identifier_columns)
        if signature in keyed_rows:
            return None
        keyed_rows[signature] = row
    return keyed_rows


def _values_approximately_equal(left: Any, right: Any) -> bool:
    left_canonical = _canonicalize_value(left)
    right_canonical = _canonicalize_value(right)
    if left_canonical is None or right_canonical is None:
        return left_canonical == right_canonical

    left_number = _as_float(left)
    right_number = _as_float(right)
    if left_number is not None and right_number is not None:
        tolerance = _comparison_tolerance(left_number, right_number)
        return abs(left_number - right_number) <= tolerance
    return left_canonical == right_canonical


def _comparison_tolerance(left: float, right: float) -> float:
    if float(left).is_integer() and float(right).is_integer():
        return INTEGER_COMPARISON_TOLERANCE
    return FLOAT_COMPARISON_TOLERANCE


def _build_summary(
    report_month: str,
    run_id: str,
    comparison_items: list[dict[str, Any]],
    local_only_statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    counter = Counter(item["status"] for item in comparison_items)
    return {
        "report_month": report_month,
        "run_id": run_id,
        "compared_api_cards": len(comparison_items),
        "local_only_cards": len(local_only_statuses),
        "status_counts": dict(counter),
        "exact_match_cards": [item["card_id"] for item in comparison_items if item["status"] == "exact_match"],
        "near_match_cards": [item["card_id"] for item in comparison_items if item["status"] == "near_match"],
        "accepted_match_cards": [
            item["card_id"] for item in comparison_items if item["status"] in {"exact_match", "near_match", "subset_match", "both_empty"}
        ],
        "problem_cards": [
            item["card_id"]
            for item in comparison_items
            if item["status"] not in {"exact_match", "near_match", "subset_match", "both_empty"}
        ],
    }


def _render_markdown(
    summary: dict[str, Any],
    comparison_items: list[dict[str, Any]],
    local_only_statuses: list[dict[str, Any]],
) -> str:
    lines = [
        f"# API vs 本地卡片集合对比分析（{summary['report_month']}）",
        "",
        f"- 运行批次：`{summary['run_id']}`",
        f"- API 对比卡片数：`{summary['compared_api_cards']}`",
        f"- 仅本地卡片数：`{summary['local_only_cards']}`",
        f"- 状态分布：`{json.dumps(summary['status_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## 一、API 卡片对比总览",
        "",
        "| card_id | 角色 | 状态 | API行数 | 本地行数 | 公共列精确命中行数 |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for item in comparison_items:
        lines.append(
            "| {card_id} | {role} | {status} | {api_row_count} | {local_row_count} | {exact_match_rows_on_common_columns} |".format(
                **item
            )
        )

    lines.extend(["", "## 二、仅本地卡片状态", "", "| card_id | 角色 | 状态 | 行数 | 文件 |", "| --- | --- | --- | ---: | --- |"])
    for item in local_only_statuses:
        lines.append(
            f"| {item['card_id']} | {item['role']} | {item['status']} | {item['row_count']} | {item['workbook_path']} |"
        )

    lines.append("")
    lines.append("## 三、逐卡分析")
    for item in comparison_items:
        lines.extend(
            [
                "",
                f"### {item['card_name']}（{item['card_id']}）",
                "",
                f"- 角色：`{item['role']}`",
                f"- 对比状态：`{item['status']}`",
                f"- API 行数：`{item['api_row_count']}`；本地行数：`{item['local_row_count']}`",
                f"- 公共列数：`{len(item['common_columns'])}`；API 独有列数：`{len(item['api_only_columns'])}`；本地独有列数：`{len(item['local_only_columns'])}`",
                f"- API 原始归档：`{item['api_archived_path']}`",
                f"- 本地文件：`{item['local_workbook_path']}`",
            ]
        )
        if item["api_application_errors"]:
            lines.append(f"- API 错误：`{json.dumps(item['api_application_errors'], ensure_ascii=False)}`")
        if item["near_match_notes"]:
            lines.append(f"- 容差判定：`{' '.join(item['near_match_notes'])}`")
        if item["api_only_columns"]:
            lines.append(f"- API 独有列：`{', '.join(item['api_only_columns'][:15])}`")
        if item["local_only_columns"]:
            lines.append(f"- 本地独有列：`{', '.join(item['local_only_columns'][:15])}`")
        if item["numeric_column_checks"]:
            lines.append("- 数值字段抽样校验：")
            for check in item["numeric_column_checks"][:5]:
                lines.append(
                    "  - `{column}`: api_sum={api_sum}, local_sum={local_sum}, delta={sum_delta}".format(**check)
                )
        if item["api_unmatched_samples"]:
            lines.append(f"- API 未命中样例：`{json.dumps(item['api_unmatched_samples'], ensure_ascii=False)}`")
        if item["local_unmatched_samples"]:
            lines.append(f"- 本地未命中样例：`{json.dumps(item['local_unmatched_samples'], ensure_ascii=False)}`")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
