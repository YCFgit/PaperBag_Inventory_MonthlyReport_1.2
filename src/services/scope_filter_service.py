from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.models.schemas import NormalizedDataset, ScopeConfig


class ScopeFilterService:
    TOTAL_REGION_TOKENS = ("总计", "合计", "全国", "小计")

    def __init__(self, scope_config: ScopeConfig, field_aliases: dict[str, Any], logger: Any) -> None:
        self.scope_config = scope_config
        self.field_aliases = field_aliases or {}
        self.logger = logger
        self.region_keys = self.field_aliases.get(
            "region_keys",
            ["大区", "原销售大区", "地区", "区域", "管理大区", "区域名称", "战区"],
        )
        self.brand_keys = self.field_aliases.get(
            "brand_keys",
            ["brd_no", "品牌", "品牌代码", "品牌编号", "品牌编码"],
        )

    def apply(self, datasets: list[NormalizedDataset]) -> list[NormalizedDataset]:
        scoped_datasets: list[NormalizedDataset] = []
        for dataset in datasets:
            scoped_datasets.append(self._apply_to_dataset(dataset))
        return scoped_datasets

    def _apply_to_dataset(self, dataset: NormalizedDataset) -> NormalizedDataset:
        input_rows = dataset.rows
        if not input_rows:
            scope_info = {
                "input_rows": 0,
                "output_rows": 0,
                "dropped_rows": 0,
                "region_fields": [],
                "brand_fields": [],
                "region_constraint_applied": False,
                "brand_constraint_applied": False,
                "warnings": [],
            }
            summary = dict(dataset.summary)
            summary["scope_info"] = scope_info
            return replace(dataset, summary=summary)

        scoped_rows: list[dict[str, Any]] = []
        detected_region_fields: set[str] = set()
        detected_brand_fields: set[str] = set()
        region_applied = False
        brand_applied = False

        for row in input_rows:
            row_region_fields = self._find_matching_fields(row, self.region_keys)
            row_brand_fields = self._find_matching_fields(row, self.brand_keys)
            detected_region_fields.update(row_region_fields)
            detected_brand_fields.update(row_brand_fields)

            if row_region_fields and self.scope_config.allowed_regions:
                region_applied = True
                if not self._row_matches_region_scope(row, row_region_fields):
                    continue

            if row_brand_fields and self.scope_config.allowed_brand_codes:
                brand_applied = True
                if not self._row_matches_brand_scope(row, row_brand_fields):
                    continue

            scoped_rows.append(row)

        warnings: list[str] = []
        if self.scope_config.allowed_regions and not region_applied:
            warnings.append("缺少可识别的大区字段，无法在本地严格应用大区白名单。")
        if self.scope_config.allowed_brand_codes and not brand_applied:
            warnings.append("缺少可识别的品牌字段，无法在本地严格应用 brd_no 白名单。")

        scope_info = {
            "input_rows": len(input_rows),
            "output_rows": len(scoped_rows),
            "dropped_rows": len(input_rows) - len(scoped_rows),
            "region_fields": sorted(detected_region_fields),
            "brand_fields": sorted(detected_brand_fields),
            "region_constraint_applied": region_applied,
            "brand_constraint_applied": brand_applied,
            "warnings": warnings,
        }
        summary = dict(dataset.summary)
        summary["row_count"] = len(scoped_rows)
        summary["columns"] = sorted({key for row in scoped_rows for key in row.keys()})
        summary["scope_info"] = scope_info

        if scope_info["dropped_rows"] > 0:
            self.logger.info(
                "Applied local scope to dataset role=%s rows=%s->%s",
                dataset.role,
                len(input_rows),
                len(scoped_rows),
            )

        return replace(dataset, rows=scoped_rows, summary=summary)

    def _find_matching_fields(self, row: dict[str, Any], keys: list[str]) -> list[str]:
        matches: list[str] = []
        for candidate_key in row.keys():
            if any(self._match_score(str(candidate_key), key) > 0 for key in keys):
                matches.append(str(candidate_key))
        return matches

    def _row_matches_region_scope(self, row: dict[str, Any], fields: list[str]) -> bool:
        values = [str(row[field]).strip() for field in fields if row.get(field) is not None]
        if not values:
            return True
        if self.scope_config.drop_total_rows_with_region_scope and any(self._is_total_region(value) for value in values):
            return False
        return any(value in self.scope_config.allowed_regions for value in values)

    def _row_matches_brand_scope(self, row: dict[str, Any], fields: list[str]) -> bool:
        values = [str(row[field]).strip() for field in fields if row.get(field) is not None]
        if not values:
            return True
        return any(value in self.scope_config.allowed_brand_codes for value in values)

    def _match_score(self, candidate_key: str, key: str) -> int:
        if candidate_key == key:
            return 100
        if candidate_key.startswith(key) or candidate_key.endswith(key):
            return 90
        if key in candidate_key:
            return 80
        return 0

    def _is_total_region(self, value: str) -> bool:
        return any(token in value for token in self.TOTAL_REGION_TOKENS)
