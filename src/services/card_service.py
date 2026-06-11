from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from requests import HTTPError, RequestException

from src.clients.guanyuan_client import GuanYuanClient, normalize_filters
from src.models.schemas import CardConfig, RawCardResult, TaskContext
from src.utils.date_helper import resolve_month_boundaries
from src.utils.template import render_nested_templates


class CardService:
    def __init__(self, client: GuanYuanClient, user_id: str, logger: Any) -> None:
        self.client = client
        self.user_id = user_id
        self.logger = logger

    def fetch_cards(
        self,
        cards: list[CardConfig],
        token_getter: Any,
        context: TaskContext,
        raw_data_dir: Path,
        apply_remote_filters: bool = False,
    ) -> list[RawCardResult]:
        results: list[RawCardResult] = []
        report_raw_dir = raw_data_dir / context.report_month / context.run_id
        report_raw_dir.mkdir(parents=True, exist_ok=True)
        template_variables = resolve_month_boundaries(context.report_month)

        for card in cards:
            if not card.enabled:
                continue

            self.logger.info("Fetching card %s (%s).", card.name, card.card_id)
            resolved_request_body = render_nested_templates(card.request_body, template_variables)
            resolved_dynamic_params = render_nested_templates(card.dynamic_params, template_variables)
            resolved_filters = render_nested_templates(card.filters, template_variables)
            api_filters = normalize_filters(resolved_filters) if apply_remote_filters else []
            if card.local_only:
                payload = {
                    "card_id": card.card_id,
                    "card_name": card.name,
                    "role": card.role,
                    "section": card.section,
                    "resolved_request_body": resolved_request_body,
                    "resolved_dynamic_params": resolved_dynamic_params,
                    "resolved_filters": api_filters,
                    "pages": [],
                    "local_only": True,
                }
                archive_path = report_raw_dir / f"{card.role}_{card.card_id}.json"
                archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                results.append(RawCardResult(card=card, raw_payload=payload, archived_path=archive_path))
                continue
            try:
                token = token_getter()
                pages = self.client.fetch_card_all_pages(
                    card,
                    token,
                    self.user_id,
                    resolved_request_body=resolved_request_body,
                    resolved_dynamic_params=resolved_dynamic_params,
                    resolved_filters=api_filters,
                )
            except HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    self.logger.warning("Token expired while requesting %s, trying refresh.", card.card_id)
                    token = token_getter(force_refresh=True)
                    try:
                        pages = self.client.fetch_card_all_pages(
                            card,
                            token,
                            self.user_id,
                            resolved_request_body=resolved_request_body,
                            resolved_dynamic_params=resolved_dynamic_params,
                            resolved_filters=api_filters,
                        )
                    except RequestException as retry_exc:
                        pages = [self._build_request_error_page(retry_exc, "retry_after_401")]
                else:
                    pages = [self._build_request_error_page(exc, "http_error")]
            except RequestException as exc:
                pages = [self._build_request_error_page(exc, "request_exception")]

            payload = {
                "card_id": card.card_id,
                "card_name": card.name,
                "role": card.role,
                "section": card.section,
                "resolved_request_body": resolved_request_body,
                "resolved_dynamic_params": resolved_dynamic_params,
                "resolved_filters": api_filters,
                "pages": pages,
            }
            archive_path = report_raw_dir / f"{card.role}_{card.card_id}.json"
            archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(RawCardResult(card=card, raw_payload=payload, archived_path=archive_path))

        return results

    def _build_request_error_page(self, exc: RequestException, reason: str) -> dict[str, Any]:
        response = getattr(exc, "response", None)
        status_code = response.status_code if response is not None else "request_exception"
        message = str(exc)
        if response is not None:
            try:
                message = response.text[:500]
            except Exception:
                message = str(exc)
        message = self._redact_sensitive_text(message)
        self.logger.warning("Card request failed reason=%s status=%s message=%s", reason, status_code, message)
        return {
            "code": status_code,
            "msg": message,
            "request_error_reason": reason,
            "rows": [],
        }

    def _redact_sensitive_text(self, text: str) -> str:
        redacted = text
        redacted = re.sub(r"(client_secret=)[^&\s]+", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)
        redacted = re.sub(r"(auth-token[=:]\s*)([^\s,;]+)", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)
        redacted = re.sub(r"(Authorization:\s*Bearer\s+)[^\s]+", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)
        redacted = re.sub(r"(x-api-key[=:]\s*)([^\s,;]+)", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)
        return redacted
