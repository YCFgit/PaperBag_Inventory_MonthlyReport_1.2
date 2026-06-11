from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from src.models.schemas import AppConfig, CardConfig, PaginationConfig, ScopeConfig, ThresholdConfig


def _derive_project_slug(project_root: Path, configured_slug: str = "") -> str:
    base = configured_slug.strip() or project_root.name
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base)
    slug = re.sub(r"[^0-9A-Za-z]+", "_", normalized).strip("_").lower()
    return slug or "paper_bag_inventory_monthly_report"


def _derive_project_name(project_root: Path, configured_name: str = "") -> str:
    if configured_name.strip():
        return configured_name.strip()

    raw_name = project_root.name.replace("_", " ").replace("-", " ")
    humanized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw_name)
    humanized = re.sub(r"\s+", " ", humanized).strip()
    return humanized or "Paper Bag Inventory Monthly Report"


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_app_config(project_root: Path) -> AppConfig:
    _load_dotenv(project_root / ".env")
    config = _read_yaml(project_root / "config" / "app.yaml")
    runtime_root = Path(os.getenv("PAPER_BAG_RUNTIME_DIR", str(project_root)))
    scope_config = ScopeConfig(**config.get("scope", {}))
    project_config = config.get("project", {})
    project_name = _derive_project_name(project_root, str(project_config.get("name", "")))
    project_slug = _derive_project_slug(project_root, str(project_config.get("slug", "")))

    return AppConfig(
        project_root=project_root,
        runtime_root=runtime_root,
        project_name=project_name,
        project_slug=project_slug,
        timezone=os.getenv("TZ", config.get("timezone", "Asia/Shanghai")),
        guanyuan_base_url=os.getenv("GUANYUAN_BASE_URL", config["guanyuan"]["base_url"]),
        auth_token_path=config["guanyuan"]["auth_token_path"],
        data_card_path_template=config["guanyuan"]["data_card_path_template"],
        guanyuan_client_id=os.getenv("GUANYUAN_CLIENT_ID", ""),
        guanyuan_client_secret=os.getenv("GUANYUAN_CLIENT_SECRET", ""),
        guanyuan_user_id=os.getenv("GUANYUAN_USER_ID", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", config.get("llm", {}).get("base_url", "")),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", config.get("llm", {}).get("model", "")),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", config.get("llm", {}).get("timeout_seconds", 60))),
        dingtalk_webhook=os.getenv("DINGTALK_WEBHOOK", ""),
        openclaw_endpoint=os.getenv("OPENCLAW_ENDPOINT", ""),
        openclaw_token=os.getenv("OPENCLAW_TOKEN", ""),
        monthly_cron=config.get("scheduler", {}).get("cron", "0 9 1 * *"),
        default_report_locale=config.get("report", {}).get("locale", "zh-CN"),
        enable_llm=str(os.getenv("ENABLE_LLM", str(config.get("llm", {}).get("enabled", True)))).lower() == "true",
        enable_dingtalk=str(os.getenv("ENABLE_DINGTALK", str(config.get("dingtalk", {}).get("enabled", True)))).lower()
        == "true",
        raw_data_dir=runtime_root / config.get("storage", {}).get("raw_data_dir", "data/raw"),
        processed_data_dir=runtime_root / config.get("storage", {}).get("processed_data_dir", "data/processed"),
        report_dir=runtime_root / config.get("storage", {}).get("report_dir", "data/reports"),
        scope_config=scope_config,
        card_collection_dir=Path(
            os.getenv(
                "CARD_COLLECTION_DIR",
                config.get("fallback_data", {}).get("card_collection_dir", str(project_root / "data/card_collection")),
            )
        ).expanduser(),
        forecast_workbook_path=os.getenv(
            "FORECAST_WORKBOOK_PATH",
            config.get("supplemental_data", {}).get("forecast_workbook_path", ""),
        ),
        forecast_workbook_glob=os.getenv(
            "FORECAST_WORKBOOK_GLOB",
            config.get("supplemental_data", {}).get(
                "forecast_workbook_glob",
                "~/Downloads/滔搏纸袋订购辅助-未来30天纸袋使用量预测 *.xlsx",
            ),
        ),
        forecast_workbook_sheet=os.getenv(
            "FORECAST_WORKBOOK_SHEET",
            config.get("supplemental_data", {}).get("forecast_workbook_sheet", "到大区型号"),
        ),
        paper_bag_specs_workbook_path=os.getenv(
            "PAPER_BAG_SPECS_WORKBOOK_PATH",
            config.get("supplemental_data", {}).get("paper_bag_specs_workbook_path", ""),
        ),
        paper_bag_specs_workbook_sheet=os.getenv(
            "PAPER_BAG_SPECS_WORKBOOK_SHEET",
            config.get("supplemental_data", {}).get("paper_bag_specs_workbook_sheet", "纸袋规格"),
        ),
        report_template_path=project_root / config.get("report", {}).get("template_path", "config/report_template.md.j2"),
        prompts_path=project_root / "config" / "prompts.yaml",
        cards_path=project_root / "config" / "cards.yaml",
        thresholds_path=project_root / "config" / "thresholds.yaml",
        field_aliases_path=project_root / "config" / "field_aliases.yaml",
    )


def load_cards(path: Path) -> list[CardConfig]:
    payload = _read_yaml(path)
    presets: dict[str, dict[str, Any]] = payload.get("presets", {})
    cards: list[CardConfig] = []

    for item in payload.get("cards", []):
        merged_request_body: dict[str, Any] = {}
        merged_filters: list[dict[str, Any]] = []
        merged_dynamic_params: list[dict[str, Any]] = []

        for preset_name in item.get("preset_refs", []):
            preset = presets.get(preset_name, {})
            merged_request_body.update(preset.get("request_body", {}))
            merged_filters.extend(preset.get("filters", []))
            merged_dynamic_params.extend(preset.get("dynamic_params", []))

        merged_request_body.update(item.get("request_body", {}))
        merged_filters.extend(item.get("filters", []))
        merged_dynamic_params.extend(item.get("dynamic_params", []))

        pagination = PaginationConfig(**item.get("pagination", {}))
        cards.append(
            CardConfig(
                card_id=item["card_id"],
                name=item["name"],
                role=item["role"],
                section=item["section"],
                enabled=item.get("enabled", True),
                local_only=item.get("local_only", False),
                allow_empty_result=item.get("allow_empty_result", False),
                empty_reason=item.get("empty_reason", ""),
                pagination=pagination,
                request_body=merged_request_body,
                filters=merged_filters,
                dynamic_params=merged_dynamic_params,
                preset_refs=item.get("preset_refs", []),
                notes=item.get("notes", ""),
            )
        )
    return cards


def load_thresholds(path: Path) -> ThresholdConfig:
    payload = _read_yaml(path)
    return ThresholdConfig(**payload.get("thresholds", {}))


def load_prompts(path: Path) -> dict[str, Any]:
    return _read_yaml(path)


def load_field_aliases(path: Path) -> dict[str, Any]:
    return _read_yaml(path)


def validate_loaded_app_config(app_config: AppConfig) -> list[str]:
    errors: list[str] = []

    if not app_config.guanyuan_client_id:
        errors.append("GUANYUAN_CLIENT_ID is required.")
    if not app_config.guanyuan_client_secret:
        errors.append("GUANYUAN_CLIENT_SECRET is required.")
    if not app_config.guanyuan_user_id:
        errors.append("GUANYUAN_USER_ID is required.")

    if app_config.enable_llm:
        if not app_config.llm_base_url:
            errors.append("LLM_BASE_URL is required when LLM is enabled.")
        if not app_config.llm_api_key:
            errors.append("LLM_API_KEY is required when LLM is enabled.")
        if not app_config.llm_model:
            errors.append("LLM_MODEL is required when LLM is enabled.")

    if not app_config.raw_data_dir:
        errors.append("storage.raw_data_dir must be configured.")
    if not app_config.processed_data_dir:
        errors.append("storage.processed_data_dir must be configured.")
    if not app_config.report_dir:
        errors.append("storage.report_dir must be configured.")

    return errors
