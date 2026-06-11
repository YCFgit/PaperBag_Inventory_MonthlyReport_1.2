from __future__ import annotations

from typing import Any

import requests

from src.models.schemas import CardConfig


class GuanYuanClient:
    def __init__(self, base_url: str, path_template: str, timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.path_template = path_template
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def fetch_card_page(
        self,
        card: CardConfig,
        auth_token: str,
        user_id: str,
        limit: int,
        offset: int,
        resolved_request_body: dict[str, Any] | None = None,
        resolved_dynamic_params: list[dict[str, Any]] | None = None,
        resolved_filters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(resolved_request_body or card.request_body or {})
        payload.update(
            {
                "userId": user_id,
                "limit": limit,
                "offset": offset,
            }
        )
        payload.setdefault("view", "GRID")
        payload["dynamicParams"] = (
            resolved_dynamic_params
            if resolved_dynamic_params is not None
            else (card.dynamic_params or card.request_body.get("dynamicParams", []))
        )
        filters = resolved_filters if resolved_filters is not None else (card.filters or card.request_body.get("filters", []))
        payload["filters"] = normalize_filters(filters)
        response = self.session.post(
            f"{self.base_url}{self.path_template.format(card_id=card.card_id)}",
            headers={"Content-Type": "application/json", "auth-token": auth_token},
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def fetch_card_all_pages(
        self,
        card: CardConfig,
        auth_token: str,
        user_id: str,
        resolved_request_body: dict[str, Any] | None = None,
        resolved_dynamic_params: list[dict[str, Any]] | None = None,
        resolved_filters: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        offset = card.pagination.offset

        for _ in range(card.pagination.max_pages):
            page = self.fetch_card_page(
                card=card,
                auth_token=auth_token,
                user_id=user_id,
                limit=card.pagination.limit,
                offset=offset,
                resolved_request_body=resolved_request_body,
                resolved_dynamic_params=resolved_dynamic_params,
                resolved_filters=resolved_filters,
            )
            pages.append(page)
            rows = _extract_rows_from_payload(page)
            if not rows or len(rows) < card.pagination.limit:
                break
            offset += card.pagination.limit
        return pages


def _extract_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        payload.get("rows"),
        payload.get("data", {}).get("rows") if isinstance(payload.get("data"), dict) else None,
        payload.get("data", {}).get("rowList") if isinstance(payload.get("data"), dict) else None,
        payload.get("result", {}).get("rows") if isinstance(payload.get("result"), dict) else None,
        payload.get("data", {}).get("list") if isinstance(payload.get("data"), dict) else None,
        payload.get("list"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


def normalize_filters(filters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not filters:
        return []

    normalized: list[dict[str, Any]] = []
    for item in filters:
        if not isinstance(item, dict):
            continue

        if {"name", "filterType", "filterValue"}.issubset(item.keys()):
            filter_type = str(item.get("filterType", "")).strip().upper()
            filter_values = _normalize_filter_values(item.get("filterValue"))
            if filter_type in {"BETWEEN", "BT"} and len(filter_values) >= 2:
                normalized.extend(
                    [
                        {**item, "filterType": "GE", "filterValue": [filter_values[0]]},
                        {**item, "filterType": "LE", "filterValue": [filter_values[1]]},
                    ]
                )
                continue

            normalized.append(
                {
                    **item,
                    "filterType": filter_type,
                    "filterValue": filter_values,
                }
            )
            continue

        name = item.get("name") or item.get("fieldName")
        operator = item.get("filterType") or item.get("operator")
        values = _normalize_filter_values(item.get("filterValue") if "filterValue" in item else item.get("values"))
        if not name or not operator:
            normalized.append(item)
            continue

        filter_type = str(operator).strip().upper()
        if filter_type in {"BETWEEN", "BT"} and len(values) >= 2:
            normalized.extend(
                [
                    {"name": str(name), "filterType": "GE", "filterValue": [values[0]]},
                    {"name": str(name), "filterType": "LE", "filterValue": [values[1]]},
                ]
            )
            continue

        normalized.append({"name": str(name), "filterType": filter_type, "filterValue": values})
    return normalized


def _normalize_filter_values(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (list, tuple, set)):
        return [str(value) for value in values if value is not None]
    return [str(values)]
