from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.models.schemas import CardConfig, NormalizedDataset, RawCardResult


class IntegrationService:
    def __init__(self, logger: Any) -> None:
        self.logger = logger

    def inspect_raw_card(self, raw_result: RawCardResult) -> dict[str, Any]:
        pages = raw_result.raw_payload.get("pages", [])
        rows = []
        for page in pages:
            rows.extend(self._extract_rows(page))

        field_counter: Counter[str] = Counter()
        samples: dict[str, list[Any]] = {}
        for row in rows:
            for key, value in row.items():
                field_counter[str(key)] += 1
                samples.setdefault(str(key), [])
                if len(samples[str(key)]) < 3 and value not in samples[str(key)]:
                    samples[str(key)].append(value)

        report = {
            "card_id": raw_result.card.card_id,
            "card_name": raw_result.card.name,
            "role": raw_result.card.role,
            "section": raw_result.card.section,
            "page_count": len(pages),
            "row_count": len(rows),
            "fields": [
                {"name": field, "occurrences": count, "samples": samples.get(field, [])}
                for field, count in field_counter.most_common()
            ],
        }
        return report

    def inspect_normalized_dataset(self, dataset: NormalizedDataset) -> dict[str, Any]:
        field_counter: Counter[str] = Counter()
        samples: dict[str, list[Any]] = {}
        numeric_candidates: Counter[str] = Counter()

        for row in dataset.rows:
            for key, value in row.items():
                field_counter[key] += 1
                samples.setdefault(key, [])
                if len(samples[key]) < 3 and value not in samples[key]:
                    samples[key].append(value)
                if isinstance(value, (int, float)):
                    numeric_candidates[key] += 1

        return {
            "role": dataset.role,
            "card_id": dataset.card_id,
            "card_name": dataset.card_name,
            "row_count": len(dataset.rows),
            "application_errors": dataset.summary.get("application_errors", []),
            "field_presence": field_counter.most_common(),
            "numeric_candidates": numeric_candidates.most_common(),
            "samples": samples,
        }

    def summarize_dataset_health(self, datasets: list[NormalizedDataset]) -> dict[str, Any]:
        dataset_statuses = []
        empty_cards = []
        scope_warnings: list[str] = []
        for dataset in datasets:
            scope_info = dataset.summary.get("scope_info", {})
            application_errors = dataset.summary.get("application_errors", [])
            fallback_info = dataset.summary.get("fallback_info")
            allow_empty_result = dataset.summary.get("allow_empty_result", False)
            status_value = (
                "fallback"
                if application_errors and fallback_info
                else "error"
                if application_errors
                else "empty_allowed"
                if not dataset.rows and allow_empty_result
                else "empty"
                if not dataset.rows
                else "ready"
            )
            status = {
                "role": dataset.role,
                "card_id": dataset.card_id,
                "card_name": dataset.card_name,
                "section": dataset.section,
                "row_count": len(dataset.rows),
                "status": status_value,
                "columns": dataset.summary.get("columns", []),
                "scope_info": scope_info,
                "application_errors": application_errors,
                "fallback_info": fallback_info,
                "empty_reason": dataset.summary.get("empty_reason", ""),
            }
            dataset_statuses.append(status)
            if status["status"] == "empty":
                empty_cards.append(status)
            for warning in scope_info.get("warnings", []):
                scope_warnings.append(f"{dataset.card_name}：{warning}")

        warnings = []
        if empty_cards:
            warnings.append(f"共有 {len(empty_cards)} 张卡片当前返回空数据，相关章节结论可能不完整。")
        fallback_cards = [item for item in dataset_statuses if item["status"] == "fallback"]
        if fallback_cards:
            warnings.append(
                "以下数据源接口异常，但已自动切换为本地卡片集合兜底："
                + "；".join(
                    f"{item['card_name']}({item['card_id']})"
                    for item in fallback_cards[:6]
                )
            )
        hard_error_cards = [item for item in dataset_statuses if item["status"] == "error"]
        if hard_error_cards:
            warnings.append(
                "以下数据源返回了观远应用层错误，且暂无可用兜底："
                + "；".join(
                    f"{item['card_name']}({item['card_id']}) code={item['application_errors'][0]['code']}"
                    for item in hard_error_cards[:4]
                )
            )
        if scope_warnings:
            warnings.append("部分数据源无法在本地严格应用范围约束：" + "；".join(scope_warnings[:4]))
        expected_empty_cards = [item for item in dataset_statuses if item["status"] == "empty_allowed"]
        if expected_empty_cards:
            warnings.append(
                "以下数据源本期为空但属于正常现象："
                + "；".join(
                    f"{item['card_name']}（{item['empty_reason'] or '允许空结果'}）"
                    for item in expected_empty_cards[:4]
                )
            )

        return {
            "dataset_statuses": dataset_statuses,
            "empty_cards": empty_cards,
            "warnings": warnings,
        }

    def save_report(self, payload: dict[str, Any], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("Integration inspection written to %s", output_path)
        return output_path

    def _extract_rows(self, page: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = [
            page.get("rows"),
            page.get("data", {}).get("rows") if isinstance(page.get("data"), dict) else None,
            page.get("data", {}).get("rowList") if isinstance(page.get("data"), dict) else None,
            page.get("result", {}).get("rows") if isinstance(page.get("result"), dict) else None,
            page.get("data", {}).get("list") if isinstance(page.get("data"), dict) else None,
            page.get("list"),
        ]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
        return []
