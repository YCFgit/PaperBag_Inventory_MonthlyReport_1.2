from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PaginationConfig:
    limit: int = 200
    offset: int = 0
    max_pages: int = 20


@dataclass(slots=True)
class CardConfig:
    card_id: str
    name: str
    role: str
    section: str
    enabled: bool = True
    local_only: bool = False
    allow_empty_result: bool = False
    empty_reason: str = ""
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    request_body: dict[str, Any] = field(default_factory=dict)
    filters: list[dict[str, Any]] = field(default_factory=list)
    dynamic_params: list[dict[str, Any]] = field(default_factory=list)
    preset_refs: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(slots=True)
class ThresholdConfig:
    inventory_green_max: float = 2.5
    inventory_yellow_max: float = 3.5
    purchase_urgent_max: float = 0.0
    purchase_focus_max: float = 0.5
    purchase_watch_max: float = 1.0
    purchase_excess_max: float = 3.5
    purchase_inventory_min: float = 10000.0
    purchase_future_ratio_min: float = 2.5
    purchase_inbound_min: float = 0.0
    order_anomaly_ratio_min: float = 1.0
    inventory_loss_rate_max: float = 0.05
    inventory_loss_amount_3m_max: float = 1000.0
    regional_inventory_loss_amount_max: float = 1000.0
    regional_inventory_loss_qty_max: float = 1000.0


@dataclass(slots=True)
class ScopeConfig:
    allowed_regions: list[str] = field(default_factory=list)
    allowed_brand_codes: list[str] = field(default_factory=list)
    apply_remote_filters: bool = False
    drop_total_rows_with_region_scope: bool = True


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    runtime_root: Path
    project_name: str
    project_slug: str
    timezone: str
    guanyuan_base_url: str
    auth_token_path: str
    data_card_path_template: str
    guanyuan_client_id: str
    guanyuan_client_secret: str
    guanyuan_user_id: str
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 60
    dingtalk_webhook: str = ""
    openclaw_endpoint: str = ""
    openclaw_token: str = ""
    monthly_cron: str = "0 9 1 * *"
    default_report_locale: str = "zh-CN"
    enable_llm: bool = True
    enable_dingtalk: bool = True
    raw_data_dir: Path = Path("data/raw")
    processed_data_dir: Path = Path("data/processed")
    report_dir: Path = Path("data/reports")
    scope_config: ScopeConfig = field(default_factory=ScopeConfig)
    card_collection_dir: Path = Path("data/card_collection")
    forecast_workbook_path: str = ""
    forecast_workbook_glob: str = "~/Downloads/滔搏纸袋订购辅助-未来30天纸袋使用量预测 *.xlsx"
    forecast_workbook_sheet: str = "到大区型号"
    paper_bag_specs_workbook_path: str = ""
    paper_bag_specs_workbook_sheet: str = "纸袋规格"
    report_template_path: Path = Path("config/report_template.md.j2")
    prompts_path: Path = Path("config/prompts.yaml")
    cards_path: Path = Path("config/cards.yaml")
    thresholds_path: Path = Path("config/thresholds.yaml")
    field_aliases_path: Path = Path("config/field_aliases.yaml")


@dataclass(slots=True)
class TaskContext:
    run_id: str
    report_month: str
    generated_at: datetime
    project_root: Path
    project_name: str = ""
    project_slug: str = ""


@dataclass(slots=True)
class RawCardResult:
    card: CardConfig
    raw_payload: dict[str, Any]
    archived_path: Path | None = None


@dataclass(slots=True)
class NormalizedDataset:
    role: str
    card_id: str
    card_name: str
    section: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SectionAnalysis:
    section_key: str
    title: str
    summary: str
    insights: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReportDocument:
    report_month: str
    title: str
    markdown: str
    output_path: Path
    executive_summary: str
    sections: list[SectionAnalysis] = field(default_factory=list)


@dataclass(slots=True)
class DeliveryResult:
    channel: str
    success: bool
    message: str
    response_payload: dict[str, Any] = field(default_factory=dict)
