from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import replace
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from src.clients.auth_client import AuthClient
from src.clients.dingtalk_oapi_client import DingTalkOapiClient
from src.clients.dingtalk_workspace_client import DingTalkWorkspaceClient
from src.clients.guanyuan_client import GuanYuanClient
from src.clients.llm_client import LLMClient
from src.models.schemas import TaskContext
from src.scheduler import build_scheduler
from src.services.analysis_service import AnalysisService
from src.services.card_collection_fallback_service import CardCollectionFallbackService
from src.services.card_service import CardService
from src.services.diagnosis_service import DiagnosisService
from src.services.dingtalk_binding_service import DingTalkBindingService
from src.services.dingtalk_file_sender import DingTalkFileSender
from src.services.integration_service import IntegrationService
from src.services.dingtalk_jsapi_service import DingTalkJsapiService
from src.services.metrics_service import MetricsService
from src.services.report_service import ReportService
from src.services.send_service import SendService
from src.services.scope_filter_service import ScopeFilterService
from src.services.supplemental_data_service import SupplementalDataService
from src.services.token_service import TokenService
from src.services.transform_service import TransformService
from src.utils.config import load_app_config, load_cards, load_field_aliases, load_prompts, load_thresholds, validate_loaded_app_config
from src.utils.date_helper import month_label, resolve_report_month
from src.utils.logger import configure_logger


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    app_config = load_app_config(project_root)

    parser = argparse.ArgumentParser(description=f"{app_config.project_name} automation")
    parser.add_argument(
        "command",
        choices=[
            "run-once",
            "schedule",
            "validate-config",
            "check-dingtalk",
            "inspect-card",
            "inspect-latest-raw",
            "inspect-all-cards",
            "replay-raw",
            "send-existing-report",
            "serve-dingtalk-jsapi",
        ],
    )
    parser.add_argument("--month", help="Report month in YYYY-MM format")
    parser.add_argument("--card-id", help="Inspect a single card id")
    parser.add_argument("--skip-llm", action="store_true", help="Disable LLM analysis for the current run")
    parser.add_argument("--skip-send", action="store_true", help="Disable DingTalk delivery for the current run")
    parser.add_argument("--raw-file", help="Replay a previously archived raw json file")
    parser.add_argument("--report-file", help="Existing markdown report file path for send-existing-report or check-dingtalk")
    parser.add_argument("--host", default="127.0.0.1", help="Host for serve-dingtalk-jsapi")
    parser.add_argument("--port", type=int, default=8000, help="Port for serve-dingtalk-jsapi")
    args = parser.parse_args()

    report_month = resolve_report_month(args.month)
    run_id = uuid.uuid4().hex[:8]
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)

    logger.info("Starting command=%s report_month=%s", args.command, report_month)

    if args.command == "validate-config":
        validate_config(project_root)
        logger.info("Configuration validation completed.")
        return

    if args.command == "check-dingtalk":
        check_dingtalk(project_root, report_month, run_id, args.report_file)
        return

    if args.command == "serve-dingtalk-jsapi":
        serve_dingtalk_jsapi(project_root, args.host, args.port)
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

    if args.command == "send-existing-report":
        send_existing_report(project_root, report_month, run_id, args.report_file)
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


def serve_dingtalk_jsapi(project_root: Path, host: str, port: int) -> None:
    app_config = load_app_config(project_root)
    run_id = "dingtalkjsapi"
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    missing_values = []
    if not app_config.dingtalk_app_key:
        missing_values.append("DINGTALK_APP_KEY")
    if not app_config.dingtalk_app_secret:
        missing_values.append("DINGTALK_APP_SECRET")
    if not app_config.dingtalk_agent_id:
        missing_values.append("DINGTALK_AGENT_ID")
    if missing_values:
        raise ValueError(f"serve-dingtalk-jsapi requires: {', '.join(missing_values)}")

    oapi_client = DingTalkOapiClient()
    jsapi_service = DingTalkJsapiService(
        oapi_client=oapi_client,
        app_key=app_config.dingtalk_app_key,
        app_secret=app_config.dingtalk_app_secret,
        agent_id=app_config.dingtalk_agent_id,
        cache_path=app_config.processed_data_dir / "dingtalk_jsapi_ticket.json",
        logger=logger,
    )
    binding_service = DingTalkBindingService(
        binding_path=app_config.processed_data_dir / "dingtalk_binding.json",
        logger=logger,
        configured_corp_id=app_config.dingtalk_corp_id,
        configured_open_conversation_id=app_config.dingtalk_open_conversation_id,
    )
    html_path = project_root / "docs" / "dingtalk_choose_conversation.html"

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._send_common_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)

            if parsed.path == "/health":
                self._send_json(200, {"status": "ok"})
                return

            if parsed.path in {"/", "/dingtalk/choose-conversation"}:
                html = html_path.read_text(encoding="utf-8")
                body = html.encode("utf-8")
                self.send_response(200)
                self._send_common_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/dingtalk/binding":
                binding = binding_service.load_binding()
                if binding is None:
                    self._send_json(404, {"error": "No DingTalk conversation binding found."})
                else:
                    self._send_json(200, binding_service.to_payload(binding))
                return

            if parsed.path != "/api/dingtalk/jsapi-config":
                self._send_json(404, {"error": "Not found"})
                return

            try:
                query = parse_qs(parsed.query)
                url = (query.get("url") or [""])[0]
                corp_id = (query.get("corpId") or [""])[0]
                payload = jsapi_service.build_config(url=url, corp_id=corp_id)
                self._send_json(200, payload)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed to build DingTalk JSAPI config")
                self._send_json(500, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != "/api/dingtalk/binding":
                self._send_json(404, {"error": "Not found"})
                return

            try:
                body_size = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(body_size)
                payload = json.loads(raw_body.decode("utf-8") or "{}")
                corp_id = str(payload.get("corpId", "")).strip()
                if not corp_id:
                    corp_id = app_config.dingtalk_corp_id
                open_conversation_id = str(payload.get("openConversationId", "")).strip()
                if not open_conversation_id:
                    raise ValueError("openConversationId is required.")
                union_id = str(payload.get("unionId", "")).strip()
                user_id = str(payload.get("userId", "")).strip()
                operator_name = str(payload.get("operatorName", "")).strip()
                auth_code = str(payload.get("authCode", "")).strip()
                if auth_code and not union_id:
                    access_token_payload = oapi_client.get_access_token(
                        app_config.dingtalk_app_key,
                        app_config.dingtalk_app_secret,
                    )
                    user_context = oapi_client.get_user_info_by_auth_code(
                        str(access_token_payload["access_token"]),
                        auth_code,
                    )
                    union_id = str(
                        user_context.get("unionid")
                        or user_context.get("unionId")
                        or user_context.get("associated_unionid")
                        or ""
                    ).strip()
                    user_id = user_id or str(user_context.get("userid") or user_context.get("userId") or "").strip()
                    operator_name = operator_name or str(user_context.get("name") or "").strip()
                if not union_id:
                    raise ValueError("unionId is required. Please open the binding page inside DingTalk and authorize again.")
                binding = binding_service.save_binding(
                    corp_id=corp_id,
                    open_conversation_id=open_conversation_id,
                    title=str(payload.get("title", "")).strip(),
                    chat_id=str(payload.get("chatId", "")).strip(),
                    union_id=union_id,
                    user_id=user_id,
                    operator_name=operator_name,
                    space_id=str(payload.get("spaceId", "")).strip(),
                )
                self._send_json(200, binding_service.to_payload(binding))
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed to save DingTalk conversation binding")
                self._send_json(500, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            logger.info("DingTalk JSAPI server: " + format, *args)

        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self._send_common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_common_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")

    server = ThreadingHTTPServer((host, port), Handler)
    logger.info("Serving DingTalk JSAPI config at http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping DingTalk JSAPI config server")
    finally:
        server.server_close()


def _build_dingtalk_file_sender(app_config, logger: Any) -> DingTalkFileSender | None:
    if not app_config.dingtalk_app_key or not app_config.dingtalk_app_secret or not app_config.dingtalk_agent_id:
        return None

    binding_service = DingTalkBindingService(
        binding_path=app_config.processed_data_dir / "dingtalk_binding.json",
        logger=logger,
        configured_corp_id=app_config.dingtalk_corp_id,
        configured_open_conversation_id=app_config.dingtalk_open_conversation_id,
    )
    return DingTalkFileSender(
        oapi_client=DingTalkOapiClient(),
        workspace_client=DingTalkWorkspaceClient(),
        app_key=app_config.dingtalk_app_key,
        app_secret=app_config.dingtalk_app_secret,
        agent_id=app_config.dingtalk_agent_id,
        binding_service=binding_service,
        token_cache_path=app_config.processed_data_dir / "dingtalk_access_token.json",
        logger=logger,
    )


def check_dingtalk(project_root: Path, report_month: str, run_id: str, report_file: str | None) -> None:
    app_config = load_app_config(project_root)
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    binding_service = DingTalkBindingService(
        binding_path=app_config.processed_data_dir / "dingtalk_binding.json",
        logger=logger,
        configured_corp_id=app_config.dingtalk_corp_id,
        configured_open_conversation_id=app_config.dingtalk_open_conversation_id,
    )
    binding = binding_service.load_binding()
    resolved_report_path = _resolve_existing_report_path(app_config.report_dir, report_month, report_file)
    resolved_pdf_path = resolved_report_path.with_suffix(".pdf") if resolved_report_path else None

    payload = {
        "reportMonth": report_month,
        "deliveryMode": app_config.dingtalk_delivery_mode,
        "robotFileConfig": {
            "appKeyConfigured": bool(app_config.dingtalk_app_key),
            "appSecretConfigured": bool(app_config.dingtalk_app_secret),
            "agentIdConfigured": bool(app_config.dingtalk_agent_id),
            "corpIdConfigured": bool(app_config.dingtalk_corp_id),
        },
        "binding": binding_service.to_payload(binding),
        "bindingPath": str(binding_service.binding_path),
        "report": {
            "markdownPath": str(resolved_report_path) if resolved_report_path else "",
            "markdownExists": bool(resolved_report_path and resolved_report_path.exists()),
            "pdfPath": str(resolved_pdf_path) if resolved_pdf_path else "",
            "pdfExists": bool(resolved_pdf_path and resolved_pdf_path.exists()),
        },
    }
    payload["readyForConversationFileSend"] = all(
        [
            payload["robotFileConfig"]["appKeyConfigured"],
            payload["robotFileConfig"]["appSecretConfigured"],
            payload["robotFileConfig"]["agentIdConfigured"],
            bool(payload["binding"]),
            bool(payload["binding"].get("unionId")),
            payload["report"]["pdfExists"],
        ]
    )
    checks = [
        {
            "name": "app_key",
            "ok": payload["robotFileConfig"]["appKeyConfigured"],
            "message": "DINGTALK_APP_KEY 已配置" if payload["robotFileConfig"]["appKeyConfigured"] else "缺少 DINGTALK_APP_KEY",
        },
        {
            "name": "app_secret",
            "ok": payload["robotFileConfig"]["appSecretConfigured"],
            "message": "DINGTALK_APP_SECRET 已配置" if payload["robotFileConfig"]["appSecretConfigured"] else "缺少 DINGTALK_APP_SECRET",
        },
        {
            "name": "agent_id",
            "ok": payload["robotFileConfig"]["agentIdConfigured"],
            "message": "DINGTALK_AGENT_ID 已配置" if payload["robotFileConfig"]["agentIdConfigured"] else "缺少 DINGTALK_AGENT_ID",
        },
        {
            "name": "binding",
            "ok": bool(payload["binding"]),
            "message": "目标群已绑定" if payload["binding"] else "尚未绑定目标群",
        },
        {
            "name": "union_id",
            "ok": bool(payload["binding"].get("unionId")),
            "message": "unionId 已绑定" if payload["binding"].get("unionId") else "尚未绑定 unionId，请重新在钉钉 H5 页面绑定一次",
        },
        {
            "name": "pdf",
            "ok": payload["report"]["pdfExists"],
            "message": "PDF 已存在" if payload["report"]["pdfExists"] else "未找到 PDF 文件",
        },
    ]
    missing_steps = [item["message"] for item in checks if not item["ok"]]
    payload["checks"] = checks
    payload["nextAction"] = (
        "可以直接执行 python -m src.main send-existing-report --month "
        f"{report_month}"
        if payload["readyForConversationFileSend"]
        else "先在钉钉内打开绑定页完成选群绑定，再执行 send-existing-report 手工验证。"
    )
    payload["blockingItems"] = missing_steps
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def send_existing_report(project_root: Path, report_month: str, run_id: str, report_file: str | None) -> None:
    app_config = load_app_config(project_root)
    logger = configure_logger(app_config.runtime_root, run_id, app_config.project_slug)
    resolved_report_path = _resolve_existing_report_path(app_config.report_dir, report_month, report_file)
    if resolved_report_path is None:
        raise FileNotFoundError(f"No existing report markdown found for month: {report_month}")

    report = _load_existing_report(resolved_report_path, report_month)
    send_service = SendService(
        file_sender=_build_dingtalk_file_sender(app_config, logger),
        enabled=app_config.enable_dingtalk,
        logger=logger,
    )
    results = send_service.send_report(report)
    payload = [
        {
            "channel": result.channel,
            "success": result.success,
            "message": result.message,
            "responsePayload": result.response_payload,
        }
        for result in results
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _resolve_existing_report_path(report_dir: Path, report_month: str, report_file: str | None) -> Path | None:
    if report_file:
        path = Path(report_file).expanduser()
        return path if path.exists() else None

    month_dir = report_dir / report_month
    if not month_dir.exists():
        return None

    preferred_path = month_dir / f"{report_month.replace('-', '')}-月度纸袋分析报告.md"
    if preferred_path.exists():
        return preferred_path

    candidates = sorted(
        [
            path
            for path in month_dir.glob("*.md")
            if "followup" not in path.stem.lower()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_existing_report(markdown_path: Path, report_month: str):
    from src.models.schemas import ReportDocument

    markdown = markdown_path.read_text(encoding="utf-8")
    title = _extract_report_title(markdown, report_month)
    executive_summary = _extract_executive_summary(markdown)
    return ReportDocument(
        report_month=report_month,
        title=title,
        markdown=markdown,
        output_path=markdown_path,
        executive_summary=executive_summary,
    )


def _extract_report_title(markdown: str, report_month: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or f"{report_month.replace('-', '')}-月度纸袋分析报告"
    return f"{report_month.replace('-', '')}-月度纸袋分析报告"


def _extract_executive_summary(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return "本月报告已生成。"


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
        file_sender=_build_dingtalk_file_sender(app_config, logger),
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
        file_sender=_build_dingtalk_file_sender(app_config, logger),
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
    1. 观远 a597 卡片原始行 + 理论需求 CSV/JSON
    2. data/input_data/{report_month}理论需求量/实际消耗量/月末库存量.csv 本地兜底
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
            if getattr(dataset, "role", "") == "regional_model_purchase_analysis"
            and (getattr(dataset, "rows", None) or getattr(dataset, "raw_payload", None))
        ),
        None,
    )
    if theory_rows and model_dataset:
        try:
            model_rows = diagnosis_service.extract_model_card_rows(model_dataset)
            actual_rows, stock_rows = diagnosis_service.build_actual_and_stock_rows_from_model_card(
                model_rows,
                report_month,
            )
            if actual_rows and stock_rows:
                result = diagnosis_service.build_diagnosis(theory_rows, actual_rows, stock_rows, report_month)
                logger.info(
                    "Diagnosis module completed from a597 card data: %s regions scored.",
                    result.get("total_regions", 0),
                )
                return result
            logger.warning("Diagnosis a597 card data was present but could not be pivoted; trying local CSV fallback.")
        except Exception as exc:
            logger.warning("Diagnosis a597 card pivot failed, trying local CSV fallback: %s", exc)

    try:
        csv_rows = diagnosis_service.load_input_csv_rows(report_month)
        if csv_rows:
            csv_theory_rows, actual_rows, stock_rows = csv_rows
            result = diagnosis_service.build_diagnosis(csv_theory_rows, actual_rows, stock_rows, report_month)
            logger.info(
                "Diagnosis module completed from local CSV fallback: %s regions scored.",
                result.get("total_regions", 0),
            )
            return result
    except Exception as exc:
        logger.warning("Diagnosis local CSV fallback failed: %s", exc)

    if theory_rows is None:
        logger.info("Diagnosis theory input was unavailable for %s, skipping diagnosis module.", report_month)
        return None

    if model_dataset is None:
        logger.warning("Diagnosis a597 card data was unavailable and local CSV fallback was missing; skipping diagnosis module.")
    else:
        logger.warning("Diagnosis a597 card data and local CSV fallback were both unavailable; skipping diagnosis module.")

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
