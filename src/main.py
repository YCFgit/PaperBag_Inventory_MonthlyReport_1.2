from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import replace
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.clients.auth_client import AuthClient
from src.clients.dingtalk_client import DingTalkClient
from src.clients.guanyuan_client import GuanYuanClient
from src.clients.llm_client import LLMClient
from src.models.schemas import TaskContext
from src.scheduler import build_scheduler
from src.services.analysis_service import AnalysisService
from src.services.card_collection_fallback_service import CardCollectionFallbackService
from src.services.card_service import CardService
from src.services.diagnosis_service import DiagnosisService
from src.services.integration_service import IntegrationService
from src.services.metrics_service import MetricsService
from src.services.report_service import ReportService
from src.services.send_service import SendService
from src.services.scope_filter_service import ScopeFilterService
from src.services.supplemental_data_service import SupplementalDataService
from src.services.token_service import TokenService
from src.services.transform_service import TransformService
from src.utils.config import load_app_config, load_cards, load_field_aliases, load_prompts, load_thresholds, validate_loaded_app_config
from src.utils.date_helper import resolve_report_month
from src.utils.logger import configure_logger


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    app_config = load_app_config(project_root)

    parser = argparse.ArgumentParser(description=f"{app_config.project_name} automation")
    parser.add_argument(
        "command",
        choices=["run-once", "schedule", "validate-config", "inspect-card", "inspect-latest-raw", "inspect-all-cards", "replay-raw"],
    )
    parser.add_argument("--month", help="Report month in YYYY-MM format")
    parser.add_argument("--card-id", help="Inspect a single card id")
    parser.add_argument("--skip-llm", action="store_true", help="Disable LLM analysis for the current run")
    parser.add_argument("--skip-send", action="store_true", help="Disable DingTalk delivery for the current run")
    parser.add_argument("--raw-file", help="Replay a previously archived raw json file")
    args = parser.parse_args()

    report_month = resolve_report_month(args.month)
    run_id = uuid.uuid4().hex[:8]
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)

    logger.info("Starting command=%s report_month=%s", args.command, report_month)

    if args.command == "validate-config":
        validate_config(project_root)
        logger.info("Configuration validation completed.")
        return

    if args.command == "inspect-card":
        inspect_card(project_root, report_month, run_id, args.card_id)
        return

    if args.command == "inspect-latest-raw":
        inspect_latest_raw(project_root, report_month, run_id)
        return

    if args.command == "inspect-all-cards":
        inspect_all_cards(project_root, report_month, run_id)
        return

    if args.command == "replay-raw":
        if not args.raw_file:
            raise ValueError("--raw-file is required for replay-raw")
        replay_raw(project_root, Path(args.raw_file), report_month, run_id, args.skip_llm, args.skip_send)
        return

    if args.command == "schedule":
        scheduler = build_scheduler(
            app_config.monthly_cron,
            lambda: run_pipeline(project_root),
            job_id=app_config.project_slug,
            timezone=app_config.timezone,
        )
        logger.info("Scheduler started with cron=%s timezone=%s", app_config.monthly_cron, app_config.timezone)
        scheduler.start()
        return

    report = run_pipeline(
        project_root,
        report_month=report_month,
        run_id=run_id,
        skip_llm=args.skip_llm,
        skip_send=args.skip_send,
    )
    logger.info("Run completed. report_path=%s", report.output_path)


def validate_config(project_root: Path) -> None:
    app_config = load_app_config(project_root)
    cards = load_cards(app_config.cards_path)
    thresholds = load_thresholds(app_config.thresholds_path)
    prompts = load_prompts(app_config.prompts_path)
    load_field_aliases(app_config.field_aliases_path)

    if not cards:
        raise ValueError("cards.yaml must contain at least one enabled card.")
    if thresholds.inventory_green_max <= 0:
        raise ValueError("thresholds.inventory_green_max must be greater than 0.")
    if "system_prompt" not in prompts:
        raise ValueError("prompts.yaml must contain system_prompt.")
    validation_errors = validate_loaded_app_config(app_config)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))


def run_pipeline(
    project_root: Path,
    report_month: str | None = None,
    run_id: str | None = None,
    skip_llm: bool = False,
    skip_send: bool = False,
):
    report_month = resolve_report_month(report_month)
    run_id = run_id or uuid.uuid4().hex[:8]
    app_config = load_app_config(project_root)
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    cards = load_cards(app_config.cards_path)
    thresholds = load_thresholds(app_config.thresholds_path)
    prompts = load_prompts(app_config.prompts_path)
    field_aliases = load_field_aliases(app_config.field_aliases_path)

    context = TaskContext(
        run_id=run_id,
        report_month=report_month,
        generated_at=datetime.now(),
        project_root=project_root,
        project_name=app_config.project_name,
        project_slug=app_config.project_slug,
    )
    logger.info("Pipeline context: %s", json.dumps({"run_id": run_id, "report_month": report_month}, ensure_ascii=False))

    auth_client = AuthClient(app_config.guanyuan_base_url, app_config.auth_token_path)
    guanyuan_client = GuanYuanClient(app_config.guanyuan_base_url, app_config.data_card_path_template)
    llm_client = (
        LLMClient(app_config.llm_base_url, app_config.llm_api_key, app_config.llm_model, app_config.llm_timeout_seconds)
        if app_config.llm_api_key and app_config.llm_base_url and app_config.llm_model
        else None
    )
    dingtalk_client = DingTalkClient()

    token_service = TokenService(
        auth_client=auth_client,
        client_id=app_config.guanyuan_client_id,
        client_secret=app_config.guanyuan_client_secret,
        cache_path=app_config.processed_data_dir / "token_cache.json",
        logger=logger,
    )
    card_service = CardService(guanyuan_client, app_config.guanyuan_user_id, logger)
    transform_service = TransformService()
    integration_service = IntegrationService(logger)
    metrics_service = MetricsService(thresholds, field_aliases)
    scope_filter_service = ScopeFilterService(app_config.scope_config, field_aliases, logger)
    card_collection_fallback_service = CardCollectionFallbackService(
        app_config.card_collection_dir,
        logger,
    )
    supplemental_data_service = SupplementalDataService(
        workbook_glob=app_config.forecast_workbook_glob,
        sheet_name=app_config.forecast_workbook_sheet,
        logger=logger,
        workbook_path=app_config.forecast_workbook_path,
        paper_bag_specs_workbook_path=app_config.paper_bag_specs_workbook_path,
        paper_bag_specs_sheet_name=app_config.paper_bag_specs_workbook_sheet,
    )
    analysis_service = AnalysisService(llm_client, prompts, app_config.enable_llm and not skip_llm, logger)
    report_service = ReportService(app_config.report_template_path, logger)
    send_service = SendService(
        dingtalk_client=dingtalk_client,
        webhook=app_config.dingtalk_webhook,
        openclaw_endpoint=app_config.openclaw_endpoint,
        openclaw_token=app_config.openclaw_token,
        enabled=app_config.enable_dingtalk and not skip_send,
        logger=logger,
    )

    raw_results = card_service.fetch_cards(
        cards=cards,
        token_getter=lambda force_refresh=False: token_service.get_valid_token(force_refresh=force_refresh),
        context=context,
        raw_data_dir=app_config.raw_data_dir,
        apply_remote_filters=app_config.scope_config.apply_remote_filters,
    )
    normalized = _prepare_datasets(
        raw_results=raw_results,
        transform_service=transform_service,
        card_collection_fallback_service=card_collection_fallback_service,
        scope_filter_service=scope_filter_service,
        supplemental_data_service=supplemental_data_service,
        report_month=report_month,
    )
    data_quality_report = integration_service.summarize_dataset_health(normalized)
    _save_json(
        app_config.processed_data_dir / "normalized" / report_month / f"{run_id}_normalized.json",
        [asdict(dataset) for dataset in normalized],
    )
    report_facts = metrics_service.build_report_facts(normalized, report_month)
    report_facts["data_quality"] = data_quality_report

    diagnosis_service = DiagnosisService(logger=logger)
    diagnosis_data = _run_diagnosis(diagnosis_service, report_month, logger, normalized)
    if diagnosis_data:
        report_facts["diagnosis"] = diagnosis_data
        diagnosis_actions = diagnosis_data.get("action_items", [])
        if diagnosis_actions:
            _merge_diagnosis_actions_into_ai_insights(report_facts, diagnosis_actions)

    _save_json(
        app_config.processed_data_dir / "facts" / report_month / f"{run_id}_report_facts.json",
        report_facts,
    )
    analyses = analysis_service.analyze_sections(report_facts)
    _save_analysis_metadata(app_config.processed_data_dir, report_month, run_id, analyses)
    report = report_service.render(
        context,
        analyses,
        report_facts["highlights"],
        report_facts,
        report_facts["data_quality"],
        app_config.report_dir,
    )

    delivery_results = send_service.send_report(report)
    _save_json(
        app_config.processed_data_dir / "delivery" / report_month / f"{run_id}_delivery_results.json",
        [asdict(result) for result in delivery_results],
    )
    for result in delivery_results:
        logger.info("Delivery channel=%s success=%s message=%s", result.channel, result.success, result.message)
    return report


def inspect_card(project_root: Path, report_month: str, run_id: str, card_id: str | None) -> None:
    app_config = load_app_config(project_root)
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    cards = load_cards(app_config.cards_path)
    selected_cards = [replace(card, enabled=True) for card in cards if card.card_id == card_id] if card_id else [replace(cards[0], enabled=True)] if cards else []
    if not selected_cards:
        raise ValueError(f"Card not found: {card_id}")

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
    integration_service = IntegrationService(logger)
    context = TaskContext(
        run_id=run_id,
        report_month=report_month,
        generated_at=datetime.now(),
        project_root=project_root,
        project_name=app_config.project_name,
        project_slug=app_config.project_slug,
    )

    raw_results = card_service.fetch_cards(
        cards=selected_cards,
        token_getter=lambda force_refresh=False: token_service.get_valid_token(force_refresh=force_refresh),
        context=context,
        raw_data_dir=app_config.raw_data_dir,
        apply_remote_filters=app_config.scope_config.apply_remote_filters,
    )
    for raw_result in raw_results:
        inspection = integration_service.inspect_raw_card(raw_result)
        output_path = app_config.processed_data_dir / "inspection" / report_month / f"{raw_result.card.card_id}_raw_inspection.json"
        integration_service.save_report(inspection, output_path)
        logger.info("Raw inspection summary: %s", json.dumps(inspection, ensure_ascii=False))


def inspect_latest_raw(project_root: Path, report_month: str, run_id: str) -> None:
    app_config = load_app_config(project_root)
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    integration_service = IntegrationService(logger)
    raw_dir = app_config.raw_data_dir / report_month
    if not raw_dir.exists():
        raise FileNotFoundError(f"No raw data archived for month: {report_month}")

    latest_files = sorted(raw_dir.rglob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not latest_files:
        raise FileNotFoundError(f"No raw json files under: {raw_dir}")

    transform_service = TransformService()
    scope_filter_service = ScopeFilterService(app_config.scope_config, load_field_aliases(app_config.field_aliases_path), logger)
    card_collection_fallback_service = CardCollectionFallbackService(
        app_config.card_collection_dir,
        logger,
    )
    supplemental_data_service = SupplementalDataService(
        workbook_glob=app_config.forecast_workbook_glob,
        sheet_name=app_config.forecast_workbook_sheet,
        logger=logger,
        workbook_path=app_config.forecast_workbook_path,
        paper_bag_specs_workbook_path=app_config.paper_bag_specs_workbook_path,
        paper_bag_specs_sheet_name=app_config.paper_bag_specs_workbook_sheet,
    )
    for file_path in latest_files[:5]:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        card = _card_from_payload(payload)
        raw_result = type("ArchiveRaw", (), {"card": card, "raw_payload": payload})()
        inspection = integration_service.inspect_raw_card(raw_result)
        normalized_datasets = _prepare_datasets(
            raw_results=[raw_result],
            transform_service=transform_service,
            card_collection_fallback_service=card_collection_fallback_service,
            scope_filter_service=scope_filter_service,
            supplemental_data_service=supplemental_data_service,
            report_month=report_month,
            include_supplemental=False,
        )
        normalized_report = integration_service.inspect_normalized_dataset(normalized_datasets[0])
        output_dir = app_config.processed_data_dir / "inspection" / report_month
        integration_service.save_report(inspection, output_dir / f"{card.card_id}_raw_inspection.json")
        integration_service.save_report(normalized_report, output_dir / f"{card.card_id}_normalized_inspection.json")
        logger.info("Inspected archived raw file %s", file_path)


def inspect_all_cards(project_root: Path, report_month: str, run_id: str) -> None:
    app_config = load_app_config(project_root)
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    cards = load_cards(app_config.cards_path)
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
    integration_service = IntegrationService(logger)
    transform_service = TransformService()
    field_aliases = load_field_aliases(app_config.field_aliases_path)
    scope_filter_service = ScopeFilterService(app_config.scope_config, field_aliases, logger)
    card_collection_fallback_service = CardCollectionFallbackService(
        app_config.card_collection_dir,
        logger,
    )
    supplemental_data_service = SupplementalDataService(
        workbook_glob=app_config.forecast_workbook_glob,
        sheet_name=app_config.forecast_workbook_sheet,
        logger=logger,
        workbook_path=app_config.forecast_workbook_path,
        paper_bag_specs_workbook_path=app_config.paper_bag_specs_workbook_path,
        paper_bag_specs_sheet_name=app_config.paper_bag_specs_workbook_sheet,
    )
    context = TaskContext(
        run_id=run_id,
        report_month=report_month,
        generated_at=datetime.now(),
        project_root=project_root,
        project_name=app_config.project_name,
        project_slug=app_config.project_slug,
    )
    raw_results = card_service.fetch_cards(
        cards=cards,
        token_getter=lambda force_refresh=False: token_service.get_valid_token(force_refresh=force_refresh),
        context=context,
        raw_data_dir=app_config.raw_data_dir,
        apply_remote_filters=app_config.scope_config.apply_remote_filters,
    )
    normalized = _prepare_datasets(
        raw_results=raw_results,
        transform_service=transform_service,
        card_collection_fallback_service=card_collection_fallback_service,
        scope_filter_service=scope_filter_service,
        supplemental_data_service=supplemental_data_service,
        report_month=report_month,
    )
    inspection_payload = {
        "raw_cards": [integration_service.inspect_raw_card(item) for item in raw_results],
        "normalized_cards": [integration_service.inspect_normalized_dataset(item) for item in normalized],
        "health": integration_service.summarize_dataset_health(normalized),
    }
    output_path = app_config.processed_data_dir / "inspection" / report_month / f"{run_id}_all_cards_inspection.json"
    integration_service.save_report(inspection_payload, output_path)
    logger.info("Full card inspection generated at %s", output_path)


def replay_raw(
    project_root: Path,
    raw_file: Path,
    report_month: str,
    run_id: str,
    skip_llm: bool,
    skip_send: bool,
) -> None:
    app_config = load_app_config(project_root)
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    thresholds = load_thresholds(app_config.thresholds_path)
    prompts = load_prompts(app_config.prompts_path)
    field_aliases = load_field_aliases(app_config.field_aliases_path)
    llm_client = (
        LLMClient(app_config.llm_base_url, app_config.llm_api_key, app_config.llm_model, app_config.llm_timeout_seconds)
        if app_config.llm_api_key and app_config.llm_base_url and app_config.llm_model
        else None
    )
    dingtalk_client = DingTalkClient()
    transform_service = TransformService()
    metrics_service = MetricsService(thresholds, field_aliases)
    scope_filter_service = ScopeFilterService(app_config.scope_config, field_aliases, logger)
    card_collection_fallback_service = CardCollectionFallbackService(
        app_config.card_collection_dir,
        logger,
    )
    supplemental_data_service = SupplementalDataService(
        workbook_glob=app_config.forecast_workbook_glob,
        sheet_name=app_config.forecast_workbook_sheet,
        logger=logger,
        workbook_path=app_config.forecast_workbook_path,
        paper_bag_specs_workbook_path=app_config.paper_bag_specs_workbook_path,
        paper_bag_specs_sheet_name=app_config.paper_bag_specs_workbook_sheet,
    )
    integration_service = IntegrationService(logger)
    analysis_service = AnalysisService(llm_client, prompts, app_config.enable_llm and not skip_llm, logger)
    report_service = ReportService(app_config.report_template_path, logger)
    send_service = SendService(
        dingtalk_client=dingtalk_client,
        webhook=app_config.dingtalk_webhook,
        openclaw_endpoint=app_config.openclaw_endpoint,
        openclaw_token=app_config.openclaw_token,
        enabled=app_config.enable_dingtalk and not skip_send,
        logger=logger,
    )
    payload = json.loads(raw_file.read_text(encoding="utf-8"))
    card = _card_from_payload(payload)
    raw_result = type("ArchiveRaw", (), {"card": card, "raw_payload": payload, "archived_path": raw_file})()
    normalized = _prepare_datasets(
        raw_results=[raw_result],
        transform_service=transform_service,
        card_collection_fallback_service=card_collection_fallback_service,
        scope_filter_service=scope_filter_service,
        supplemental_data_service=supplemental_data_service,
        report_month=report_month,
    )
    report_facts = metrics_service.build_report_facts(normalized, report_month)
    report_facts["data_quality"] = integration_service.summarize_dataset_health(normalized)

    diagnosis_service = DiagnosisService(logger=logger)
    diagnosis_data = _run_diagnosis(diagnosis_service, report_month, logger, normalized)
    if diagnosis_data:
        report_facts["diagnosis"] = diagnosis_data
        diagnosis_actions = diagnosis_data.get("action_items", [])
        if diagnosis_actions:
            _merge_diagnosis_actions_into_ai_insights(report_facts, diagnosis_actions)

    analyses = analysis_service.analyze_sections(report_facts)
    _save_analysis_metadata(app_config.processed_data_dir, report_month, run_id, analyses)
    context = TaskContext(
        run_id=run_id,
        report_month=report_month,
        generated_at=datetime.now(),
        project_root=project_root,
        project_name=app_config.project_name,
        project_slug=app_config.project_slug,
    )
    report = report_service.render(
        context,
        analyses,
        report_facts["highlights"],
        report_facts,
        report_facts["data_quality"],
        app_config.report_dir,
    )
    send_service.send_report(report)
    logger.info("Replay finished using raw file %s", raw_file)


def _card_from_payload(payload: dict[str, Any]):
    from src.models.schemas import CardConfig, PaginationConfig

    return CardConfig(
        card_id=payload["card_id"],
        name=payload.get("card_name", payload["card_id"]),
        role=payload.get("role", "unknown"),
        section=payload.get("section", "unknown"),
        enabled=True,
        pagination=PaginationConfig(),
    )


def _merge_diagnosis_actions_into_ai_insights(
    report_facts: dict[str, Any],
    diagnosis_actions: list[dict[str, Any]],
) -> None:
    ai_insights = report_facts.get("ai_insights") or {}
    existing_actions = [
        action
        for action in list(ai_insights.get("regional_actions") or [])
        if isinstance(action, dict)
    ]
    existing_keys = {
        (
            action.get("region"),
            action.get("source") or "metrics",
            action.get("issue_key"),
        )
        for action in existing_actions
        if isinstance(action, dict)
    }

    for item in diagnosis_actions:
        if not isinstance(item, dict):
            continue
        key = (item.get("region"), item.get("source") or "diagnosis", item.get("issue_key"))
        if key in existing_keys:
            continue
        existing_actions.append(item)
        existing_keys.add(key)

    priority_order = {"P1": 0, "P2": 1, "P3": 2}
    existing_actions.sort(
        key=lambda action: (
            priority_order.get(str(action.get("priority")), 99),
            -float(action.get("severity_score") or 0),
            str(action.get("region") or ""),
            str(action.get("source") or "metrics"),
        )
    )
    ai_insights["regional_actions"] = existing_actions
    p1_count = sum(1 for action in existing_actions if action.get("priority") == "P1")
    p2_count = sum(1 for action in existing_actions if action.get("priority") == "P2")
    ai_insights["summary_sentence"] = (
        f"本期共识别{len(existing_actions)}个重点区域，"
        f"其中P1优先级{p1_count}个、P2优先级{p2_count}个。"
    )
    report_facts["ai_insights"] = ai_insights


def _run_diagnosis(
    diagnosis_service: DiagnosisService,
    report_month: str,
    logger: Any,
    normalized_datasets: list[Any] | None = None,
) -> dict[str, Any] | None:
    """尝试运行纸袋健康度诊断。

    数据来源优先级：
    1. 理论需求 CSV/JSON + a597 地区型号卡片透视出的近30天销售量和期末业务库存量
    2. data/input_data/{report_month}理论需求量/实际消耗量/月末库存量.csv（旧版人工 SQL 下载结果）
    3. data/processed/diagnosis/{report_month}/ 下的 JSON 文件（旧版预计算结果）
    """
    import json as _json

    project_root = Path(__file__).resolve().parent.parent
    diagnosis_dir = project_root / "data" / "processed" / "diagnosis" / report_month

    theory_rows: list[dict[str, Any]] | None = None
    try:
        theory_rows = diagnosis_service.load_theory_input_rows(report_month)
    except Exception as exc:
        logger.warning("Diagnosis theory CSV failed, trying processed JSON: %s", exc)

    theory_file = diagnosis_dir / "theory_demand.json"
    if theory_rows is None and theory_file.exists():
        try:
            theory_rows = _json.loads(theory_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Diagnosis theory JSON failed: %s", exc)

    model_dataset = next(
        (
            dataset
            for dataset in (normalized_datasets or [])
            if getattr(dataset, "role", "") == "regional_model_purchase_analysis" and getattr(dataset, "rows", None)
        ),
        None,
    )
    if theory_rows and model_dataset:
        try:
            actual_rows, stock_rows = diagnosis_service.build_actual_and_stock_rows_from_model_card(
                getattr(model_dataset, "rows", []),
                report_month,
            )
            if actual_rows and stock_rows:
                result = diagnosis_service.build_diagnosis(theory_rows, actual_rows, stock_rows, report_month)
                logger.info(
                    "Diagnosis module completed from a597 normalized card data: %s regions scored.",
                    result.get("total_regions", 0),
                )
                return result
            logger.warning("Diagnosis a597 card data was present but could not be pivoted; falling back to legacy inputs.")
        except Exception as exc:
            logger.warning("Diagnosis a597 card pivot failed, falling back to legacy inputs: %s", exc)

    try:
        csv_rows = diagnosis_service.load_input_csv_rows(report_month)
        if csv_rows:
            theory_rows, actual_rows, stock_rows = csv_rows
            result = diagnosis_service.build_diagnosis(theory_rows, actual_rows, stock_rows, report_month)
            logger.info("Diagnosis module completed from input CSV: %s regions scored.", result.get("total_regions", 0))
            return result
    except Exception as exc:
        logger.warning("Diagnosis input CSV failed, falling back to processed JSON: %s", exc)

    actual_file = diagnosis_dir / "actual_consumption.json"
    stock_file = diagnosis_dir / "inventory.json"

    if not all(f.exists() for f in [theory_file, actual_file, stock_file]):
        logger.info("Diagnosis data files not found in %s, skipping diagnosis module.", diagnosis_dir)
        return None

    try:
        theory_rows = _json.loads(theory_file.read_text(encoding="utf-8"))
        actual_rows = _json.loads(actual_file.read_text(encoding="utf-8"))
        stock_rows = _json.loads(stock_file.read_text(encoding="utf-8"))
        result = diagnosis_service.build_diagnosis(theory_rows, actual_rows, stock_rows, report_month)
        logger.info("Diagnosis module completed: %s regions scored.", result.get("total_regions", 0))
        return result
    except Exception as exc:
        logger.warning("Diagnosis module failed, skipping: %s", exc)
        return None


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _save_analysis_metadata(processed_data_dir: Path, report_month: str, run_id: str, analyses: list[Any]) -> None:
    payload = [
        {
            "section_key": analysis.section_key,
            "title": analysis.title,
            "metadata": analysis.metadata,
        }
        for analysis in analyses
    ]
    _save_json(processed_data_dir / "analysis" / report_month / f"{run_id}_analysis_metadata.json", payload)


def _prepare_datasets(
    raw_results: list[Any],
    transform_service: TransformService,
    card_collection_fallback_service: CardCollectionFallbackService,
    scope_filter_service: ScopeFilterService,
    supplemental_data_service: SupplementalDataService,
    report_month: str,
    include_supplemental: bool = True,
) -> list[Any]:
    normalized = transform_service.normalize(raw_results)
    normalized = card_collection_fallback_service.apply(normalized, report_month=report_month)
    if include_supplemental:
        normalized.extend(supplemental_data_service.load_datasets(report_month=report_month))
    return scope_filter_service.apply(normalized)



if __name__ == "__main__":
    main()
