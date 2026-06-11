from __future__ import annotations

from typing import Any

from src.models.schemas import NormalizedDataset, RawCardResult


class TransformService:
    def normalize(self, raw_results: list[RawCardResult]) -> list[NormalizedDataset]:
        datasets: list[NormalizedDataset] = []
        for raw in raw_results:
            rows = []
            for page in raw.raw_payload.get("pages", []):
                rows.extend(self._extract_rows(page))
            summary = self._build_summary(rows)
            summary["application_errors"] = self._extract_application_errors(raw.raw_payload.get("pages", []))
            summary["allow_empty_result"] = getattr(raw.card, "allow_empty_result", False)
            summary["empty_reason"] = getattr(raw.card, "empty_reason", "")
            datasets.append(
                NormalizedDataset(
                    role=raw.card.role,
                    card_id=raw.card.card_id,
                    card_name=raw.card.name,
                    section=raw.card.section,
                    rows=[self._normalize_row(row) for row in rows],
                    summary=summary,
                    raw_payload=raw.raw_payload,
                )
            )
        return datasets

    def _extract_rows(self, page: dict[str, Any]) -> list[dict[str, Any]]:
        data = page.get("data")
        result = page.get("result")
        candidates = [
            page.get("rows"),
            data.get("rows") if isinstance(data, dict) else None,
            data.get("rowList") if isinstance(data, dict) else None,
            result.get("rows") if isinstance(result, dict) else None,
            data.get("list") if isinstance(data, dict) else None,
            page.get("list"),
        ]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
        return []

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            normalized[str(key).strip()] = self._normalize_value(value)
        return normalized

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip().replace(",", "")
            if stripped.endswith("%"):
                try:
                    return float(stripped[:-1]) / 100
                except ValueError:
                    return value
            try:
                if "." in stripped:
                    return float(stripped)
                return int(stripped)
            except ValueError:
                return value.strip()
        return value

    def _build_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "row_count": len(rows),
            "columns": sorted({key for row in rows for key in row.keys()}),
        }

    def _extract_application_errors(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for index, page in enumerate(pages):
            code = page.get("code")
            if code in (None, 0, 200):
                continue
            errors.append(
                {
                    "page_index": index,
                    "code": code,
                    "msg": page.get("msg") or page.get("message") or "",
                }
            )
        return errors
