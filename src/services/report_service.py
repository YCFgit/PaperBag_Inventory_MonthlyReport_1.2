from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
import calendar

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models.schemas import ReportDocument, SectionAnalysis, TaskContext
from src.utils.date_helper import month_label


class ReportService:
    def __init__(self, template_path: Path, logger: Any) -> None:
        self.template_path = template_path
        self.logger = logger
        self.env = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=select_autoescape(enabled_extensions=()),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["rich_text"] = self._render_rich_text
        self.env.filters["emphasize_text"] = self._emphasize_text

    def render(
        self,
        context: TaskContext,
        analyses: list[SectionAnalysis],
        highlights: list[str],
        report_facts: dict[str, Any],
        data_quality: dict[str, Any],
        report_dir: Path,
    ) -> ReportDocument:
        report_dir = report_dir / context.report_month
        report_dir.mkdir(parents=True, exist_ok=True)

        template = self.env.get_template(self.template_path.name)
        template_context = self._build_template_context(context, report_facts, data_quality)
        markdown = template.render(
            **template_context,
            highlights=highlights,
            sections=analyses,
        ).strip() + "\n"
        markdown = self._center_table_headers(markdown)

        output_path = report_dir / f"{self._report_base_name(context.report_month)}.md"
        output_path.write_text(markdown, encoding="utf-8")
        self.logger.info("Report markdown generated at %s", output_path)
        self._generate_pdf(output_path)
        self._write_followup_document(report_dir, context, template_context, output_path)
        executive_summary = highlights[0] if highlights else "本月报告已生成。"
        return ReportDocument(
            report_month=context.report_month,
            title=self._report_display_title(context.report_month),
            markdown=markdown,
            output_path=output_path,
            executive_summary=executive_summary,
            sections=analyses,
        )

    def _build_template_context(
        self,
        context: TaskContext,
        report_facts: dict[str, Any],
        data_quality: dict[str, Any],
    ) -> dict[str, Any]:
        inventory = report_facts["sections"]["inventory_diagnosis"]["facts"]
        consumption = report_facts["sections"]["consumption_exceptions"]["facts"]

        inventory_overview = inventory["inventory_overview"]
        regional_status = inventory["regional_status"]
        purchase_analysis = inventory["purchase_analysis"]
        consumption_exceptions = consumption["consumption_exceptions"]
        stocktake_risks = consumption["stocktake_risks"]
        ai_insights = report_facts.get("ai_insights", {"summary_sentence": "", "regional_actions": []})
        ai_display_actions = [
            {
                **item,
                "root_cause_multiline": item.get("root_cause_multiline") or self._format_numbered_multiline_text(item.get("root_cause", "")),
                "issue_type_label": self._normalize_ai_issue_type_label(
                    item.get("issue_type_label") or self._describe_ai_issue_type(item)
                ),
                "priority_reason": item.get("priority_reason") or self._build_ai_priority_reason_text(item),
                "priority_rule": item.get("priority_rule") or self._build_ai_priority_rule_text(item),
                "review_metric_text": item.get("review_metric_text") or self._build_ai_review_metric_text(item),
                "issue_type_brief": self._build_ai_issue_type_brief(
                    item.get("issue_type_label") or self._describe_ai_issue_type(item)
                ),
                "priority_reason_brief": self._build_ai_priority_reason_brief(item),
                "root_cause_brief": self._build_ai_root_cause_brief(item),
                "business_plan_brief": self._build_ai_business_plan_brief(item),
                "review_metric_brief": self._build_ai_review_metric_brief(item),
            }
            for item in ai_insights.get("regional_actions", [])
            if isinstance(item, dict) and item.get("priority") in {"P1", "P2"}
        ]
        ai_display_summary = (
            f"本期保留{len(ai_display_actions)}个重点区域，"
            f"P1 {sum(1 for item in ai_display_actions if item.get('priority') == 'P1')}个，"
            f"P2 {sum(1 for item in ai_display_actions if item.get('priority') == 'P2')}个。"
            if ai_display_actions
            else "本期未识别到需要展示的P1、P2级AI洞察。"
        )
        priority_inventory_items, priority_usage_items, priority_terminal_items = self._split_priority_action_groups(
            ai_display_actions,
            max_per_group=2,
        )
        thresholds = report_facts.get("thresholds", {})
        inventory_green_max = float(thresholds.get("inventory_green_max", 2.5))
        inventory_yellow_max = float(thresholds.get("inventory_yellow_max", 3.5))
        inventory_mid_max = (inventory_green_max + inventory_yellow_max) / 2

        regional_rows = [
            {
                **row,
                "status_badge": self._status_badge(row.get("status")),
            }
            for row in regional_status["regional_rows"]
        ]
        regional_rows_display = self._build_regional_rows_display(regional_rows)
        regional_status_table_html = self._build_regional_status_table_html(regional_rows_display)
        purchase_joined_rows = purchase_analysis.get("joined_rows", [])
        purchase_alerts = purchase_analysis.get("history_evaluations") or purchase_analysis.get("report_rows", [])
        purchase_risk_rows = self._build_purchase_risk_rows(
            purchase_alerts=purchase_alerts,
            inventory_green_max=inventory_green_max,
            inventory_yellow_max=inventory_yellow_max,
        )
        purchase_priority_risk_rows = [
            row for row in purchase_risk_rows if str(row.get("risk_level", "")).startswith(("P1", "P2"))
        ]
        purchase_risk_summary_table_html = self._build_purchase_risk_summary_table(purchase_risk_rows)
        purchase_priority_risk_summary_table_html = self._build_purchase_risk_summary_table(purchase_priority_risk_rows)
        purchase_high_inbound_alerts = self._filter_purchase_scenario_rows(
            purchase_alerts,
            purchase_risk_rows,
            scenario="高库销高进销",
            fallback_level="P1（高风险）",
        )
        purchase_low_inbound_alerts = self._filter_purchase_scenario_rows(
            purchase_alerts,
            purchase_risk_rows,
            scenario="高库销低进销",
            fallback_level="P2（中风险）",
        )
        model_inventory_models = purchase_analysis.get("model_inventory_models", [])
        model_inventory_share_rows = purchase_analysis.get("model_inventory_share_rows", [])
        model_usage_share_rows = purchase_analysis.get("model_usage_share_rows", [])
        model_inventory_analysis = purchase_analysis.get("model_inventory_analysis", [])
        model_inventory_problem_analysis = [
            {
                **row,
                "structure_label_display": self._format_structure_label_with_gap(row),
            }
            for row in model_inventory_analysis
            if row.get("structure_label") != "结构相对均衡"
        ]
        top_order_anomalies = consumption_exceptions["order_anomalies"][:10]
        top_regional_anomalies = consumption_exceptions.get("regional_anomaly_rows", [])[:10]
        order_anomaly_empty_is_normal = consumption_exceptions.get("order_anomaly_empty_is_normal", False)
        order_anomaly_empty_reason = consumption_exceptions.get("order_anomaly_empty_reason", "")
        focus_regions = stocktake_risks["focus_regions"][:10]
        stocktake_difference_rows = stocktake_risks.get("difference_rows", [])[:20]
        empty_cards = data_quality.get("empty_cards", [])
        month_title = month_label(context.report_month)
        previous_month = self._previous_month(context.report_month)
        ai_actions_p1 = [item for item in ai_display_actions if item.get("priority") == "P1"]
        ai_actions_p2 = [item for item in ai_display_actions if item.get("priority") == "P2"]
        ai_inventory_actions_p1, ai_usage_actions_p1, ai_terminal_actions_p1 = self._split_priority_action_groups(
            ai_actions_p1,
            max_per_group=None,
        )
        ai_inventory_actions_p2, ai_usage_actions_p2, ai_terminal_actions_p2 = self._split_priority_action_groups(
            ai_actions_p2,
            max_per_group=None,
        )
        priority_action_groups = self._build_priority_action_group_metas(
            inventory_preview_items=priority_inventory_items,
            usage_preview_items=priority_usage_items,
            terminal_preview_items=priority_terminal_items,
            inventory_all_items=ai_inventory_actions_p1 + ai_inventory_actions_p2,
            usage_all_items=ai_usage_actions_p1 + ai_usage_actions_p2,
            terminal_all_items=ai_terminal_actions_p1 + ai_terminal_actions_p2,
        )
        ai_action_overview_groups = self._build_priority_action_group_metas(
            inventory_preview_items=ai_inventory_actions_p1 + ai_inventory_actions_p2,
            usage_preview_items=ai_usage_actions_p1 + ai_usage_actions_p2,
            terminal_preview_items=ai_terminal_actions_p1 + ai_terminal_actions_p2,
            inventory_all_items=ai_inventory_actions_p1 + ai_inventory_actions_p2,
            usage_all_items=ai_usage_actions_p1 + ai_usage_actions_p2,
            terminal_all_items=ai_terminal_actions_p1 + ai_terminal_actions_p2,
            include_empty_groups=True,
        )
        ai_p1_action_groups = self._build_priority_action_group_metas(
            inventory_preview_items=ai_inventory_actions_p1,
            usage_preview_items=ai_usage_actions_p1,
            terminal_preview_items=ai_terminal_actions_p1,
            inventory_all_items=ai_inventory_actions_p1,
            usage_all_items=ai_usage_actions_p1,
            terminal_all_items=ai_terminal_actions_p1,
            include_empty_groups=True,
            scope_label="P1",
        )
        ai_p2_action_groups = self._build_priority_action_group_metas(
            inventory_preview_items=ai_inventory_actions_p2,
            usage_preview_items=ai_usage_actions_p2,
            terminal_preview_items=ai_terminal_actions_p2,
            inventory_all_items=ai_inventory_actions_p2,
            usage_all_items=ai_usage_actions_p2,
            terminal_all_items=ai_terminal_actions_p2,
            include_empty_groups=True,
            scope_label="P2",
        )
        priority_action_preview_grid_items = self._build_priority_action_preview_grid_items(priority_action_groups)
        core_summary = self._build_core_summary(
            inventory_overview=inventory_overview,
            regional_rows=regional_rows,
            purchase_analysis=purchase_analysis,
            model_inventory_analysis=model_inventory_analysis,
            consumption_exceptions=consumption_exceptions,
            stocktake_risks=stocktake_risks,
            inventory_green_max=inventory_green_max,
            inventory_yellow_max=inventory_yellow_max,
        )
        consumption_trend_summary = self._build_consumption_trend_summary(
            consumption_exceptions.get("ratio_history", []),
            context.report_month,
        )

        consumption_history_values = self._extract_chart_values(consumption_exceptions.get("ratio_history", []), "value")
        stocktake_monthly_values = self._extract_chart_values(stocktake_risks.get("monthly_rows", []), "loss_amount")
        if not stocktake_monthly_values:
            stocktake_monthly_values = self._extract_chart_values(stocktake_risks.get("monthly_rows", []), "net_loss_qty")

        stocktake_region_values = self._extract_chart_values(stocktake_risks.get("regional_rows", []), "loss_amount")
        if not stocktake_region_values:
            stocktake_region_values = self._extract_chart_values(stocktake_risks.get("regional_rows", []), "net_loss_qty")

        diagnosis = report_facts.get("diagnosis", {})
        diagnosis_ranking = diagnosis.get("diagnosis_ranking", [])
        red_light_details = diagnosis.get("red_light_details", [])
        problem_light_details = diagnosis.get("problem_light_details", red_light_details)
        yellow_light_summary = [
            {
                **row,
                "usage_issue": self._dedupe_delimited_text(row.get("usage_issue"), fallback="使用基本合规"),
                "stock_issue": self._dedupe_delimited_text(row.get("stock_issue"), fallback="库存基本合理"),
                "suggestion": self._dedupe_delimited_text(row.get("suggestion"), fallback="持续跟踪"),
            }
            for row in diagnosis.get("yellow_light_summary", [])
        ]
        diagnosis_management_conclusion = self._build_diagnosis_management_conclusion(diagnosis)

        return {
            "title": self._report_display_title(context.report_month),
            "report_month": context.report_month,
            "report_month_label": month_title,
            "previous_month_label": month_label(previous_month),
            "fiscal_year_label": self._fiscal_year_label(context.report_month),
            "report_month_end": self._month_end(context.report_month),
            "generated_at": context.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "report_thresholds": {
                "inventory_green_max": inventory_green_max,
                "inventory_mid_max": inventory_mid_max,
                "inventory_yellow_max": inventory_yellow_max,
            },
            "regional_status_badges": {
                "green": self._status_badge("绿灯"),
                "yellow": self._status_badge("黄灯"),
                "red": self._status_badge("红灯"),
            },
            "inventory_overview": inventory_overview,
            "core_summary": core_summary,
            "inventory_management_conclusion": self._build_inventory_management_conclusion(
                inventory_overview=inventory_overview,
                report_month_label=month_title,
                report_month_end=self._month_end(context.report_month),
            ),
            "regional_status": regional_status,
            "regional_rows": regional_rows,
            "regional_rows_display": regional_rows_display,
            "regional_status_table_html": regional_status_table_html,
            "regional_management_conclusion": self._build_regional_management_conclusion(regional_status, regional_rows),
            "purchase_analysis": purchase_analysis,
            "purchase_alerts": purchase_alerts,
            "purchase_joined_rows": purchase_joined_rows,
            "purchase_risk_rows": purchase_risk_rows,
            "purchase_priority_risk_rows": purchase_priority_risk_rows,
            "purchase_risk_summary_table_html": purchase_risk_summary_table_html,
            "purchase_priority_risk_summary_table_html": purchase_priority_risk_summary_table_html,
            "purchase_future_ratio_explainer": "次月期末库销测算 = (筛选日期末库存 - 测算未来30天纸袋销量) / 测算未来30天纸袋销量",
            "purchase_report_empty_message": self._build_purchase_report_empty_message(
                purchase_alerts=purchase_alerts,
                purchase_joined_rows=purchase_joined_rows,
            ),
            "purchase_high_inbound_alerts": purchase_high_inbound_alerts,
            "purchase_low_inbound_alerts": purchase_low_inbound_alerts,
            "purchase_management_conclusion": self._build_purchase_management_conclusion(
                purchase_alerts=purchase_alerts,
                high_inbound_alerts=purchase_high_inbound_alerts,
                low_inbound_alerts=purchase_low_inbound_alerts,
            ),
            "model_focus": purchase_analysis["model_focus"],
            "model_inventory_models": model_inventory_models,
            "model_inventory_share_rows": model_inventory_share_rows,
            "model_usage_share_rows": model_usage_share_rows,
            "model_inventory_analysis": model_inventory_analysis,
            "model_inventory_problem_analysis": model_inventory_problem_analysis,
            "model_management_conclusion": self._build_model_management_conclusion(model_inventory_analysis),
            "ai_priority_standard": self._build_ai_priority_standard(),
            "consumption_exceptions": consumption_exceptions,
            "consumption_trend_summary": consumption_trend_summary,
            "consumption_management_conclusion": self._build_consumption_management_conclusion(
                consumption_exceptions=consumption_exceptions,
                report_month_label=month_title,
                previous_month_label=month_label(previous_month),
                fiscal_year_label=self._fiscal_year_label(context.report_month),
                consumption_trend_summary=consumption_trend_summary,
            ),
            "order_control_management_conclusion": self._build_order_control_management_conclusion(
                consumption_exceptions=consumption_exceptions,
                top_order_anomalies=top_order_anomalies,
                top_regional_anomalies=top_regional_anomalies,
                order_anomaly_empty_is_normal=order_anomaly_empty_is_normal,
                order_anomaly_empty_reason=order_anomaly_empty_reason,
            ),
            "stocktake_risks": stocktake_risks,
            "stocktake_management_conclusion": self._build_stocktake_management_conclusion(stocktake_risks),
            "stocktake_difference_rows": stocktake_difference_rows,
            "ai_insights": ai_insights,
            "ai_display_actions": ai_display_actions,
            "ai_actions_p1": ai_actions_p1,
            "ai_actions_p2": ai_actions_p2,
            "ai_inventory_actions_p1": ai_inventory_actions_p1,
            "ai_usage_actions_p1": ai_usage_actions_p1,
            "ai_terminal_actions_p1": ai_terminal_actions_p1,
            "ai_inventory_actions_p2": ai_inventory_actions_p2,
            "ai_usage_actions_p2": ai_usage_actions_p2,
            "ai_terminal_actions_p2": ai_terminal_actions_p2,
            "ai_display_summary": ai_display_summary,
            "priority_action_groups": priority_action_groups,
            "priority_action_preview_grid_items": priority_action_preview_grid_items,
            "ai_action_overview_groups": ai_action_overview_groups,
            "ai_p1_action_groups": ai_p1_action_groups,
            "ai_p2_action_groups": ai_p2_action_groups,
            "priority_inventory_items": priority_inventory_items,
            "priority_usage_items": priority_usage_items,
            "priority_terminal_items": priority_terminal_items,
            "top_order_anomalies": top_order_anomalies,
            "top_regional_anomalies": top_regional_anomalies,
            "order_anomaly_empty_is_normal": order_anomaly_empty_is_normal,
            "order_anomaly_empty_reason": order_anomaly_empty_reason,
            "focus_regions": focus_regions,
            "diagnosis": diagnosis,
            "diagnosis_ranking": diagnosis_ranking,
            "red_light_details": red_light_details,
            "problem_light_details": problem_light_details,
            "yellow_light_summary": yellow_light_summary,
            "diagnosis_management_conclusion": diagnosis_management_conclusion,
            "data_quality": data_quality,
            "empty_cards": empty_cards,
            "charts": {
                "inventory_trend": self._build_mermaid_xychart_multi(
                    f"{month_title}公司纸袋库销比历史变化趋势",
                    [item["label"] for item in inventory_overview.get("trend_series", [])],
                    [
                        {
                            "chart_type": "bar",
                            "values": [
                                (item["inventory_qty"] / 1000000) if item.get("inventory_qty") is not None else None
                                for item in inventory_overview.get("trend_series", [])
                            ],
                        },
                        {
                            "chart_type": "line",
                            "values": [item["ratio"] for item in inventory_overview.get("trend_series", [])],
                        },
                    ],
                    self._resolve_axis_max(
                        [
                            *((item["inventory_qty"] / 1000000) for item in inventory_overview.get("trend_series", []) if item.get("inventory_qty") is not None),
                            *(item["ratio"] for item in inventory_overview.get("trend_series", []) if item.get("ratio") is not None),
                        ],
                        10.0,
                    ),
                    max_points=7,
                    y_axis_label="库存(百万个)/库销比",
                ),
                "inventory_trend_labeled": self._build_svg_multi_line_combo_chart(
                    title=f"{month_title}纸袋库销比历史变化趋势",
                    subtitle="柱看库存规模，双折线分别看本期与去年同期库销比；关键数值已直接标注在图内。",
                    labels=[item["label"] for item in inventory_overview.get("trend_series", [])],
                    bar_values=[
                        (item["inventory_qty"] / 1000000) if item.get("inventory_qty") is not None else None
                        for item in inventory_overview.get("trend_series", [])
                    ],
                    line_series=[
                        {
                            "values": [item["ratio"] for item in inventory_overview.get("trend_series", [])],
                            "color": "#0F766E",
                            "label_formatter": lambda value: f"{float(value):.2f}" if value is not None else "",
                            "label_position": "below_center",
                        },
                        {
                            "values": [item.get("compare_ratio") for item in inventory_overview.get("trend_series", [])],
                            "color": "#94A3B8",
                            "label_formatter": lambda value: f"{float(value):.2f}" if value is not None else "",
                            "label_position": "above_center",
                        },
                    ],
                    max_value=self._resolve_axis_max(
                        [
                            *((item["inventory_qty"] / 1000000) for item in inventory_overview.get("trend_series", []) if item.get("inventory_qty") is not None),
                            *(item["ratio"] for item in inventory_overview.get("trend_series", []) if item.get("ratio") is not None),
                            *(item["compare_ratio"] for item in inventory_overview.get("trend_series", []) if item.get("compare_ratio") is not None),
                        ],
                        10.0,
                    ),
                    max_points=11,
                    bar_label_formatter=lambda value: f"{float(value):.1f}百万" if value is not None else "",
                    bar_color="#CBD5E1",
                    y_axis_label="库存(百万个)/库销比",
                    legend_items=[("#CBD5E1", "库存量"), ("#0F766E", "本期库销比"), ("#94A3B8", "去年同期库销比")],
                    bar_label_position="above_center",
                ),
                "regional_ratio_light_chart": "",
                "purchase_risk_table": self._build_purchase_risk_table(purchase_priority_risk_rows[:10]),
                "purchase_joined_table": self._build_purchase_joined_table(purchase_joined_rows[:20]),
                "purchase_risk_summary_table_html": purchase_risk_summary_table_html,
                "consumption_ratio_bar": self._build_svg_combo_chart(
                    title=self._get_consumption_chart_title(context.report_month),
                    subtitle="柱线同口径展示纸袋配比，纵轴按财年波动区间收窄。",
                    labels=[item["label"] for item in consumption_exceptions.get("ratio_history", [])],
                    bar_values=[item["value"] for item in consumption_exceptions.get("ratio_history", [])],
                    line_values=[item["value"] for item in consumption_exceptions.get("ratio_history", [])],
                    min_value=self._resolve_axis_min(consumption_history_values, 0.0),
                    max_value=self._resolve_axis_max(
                        consumption_history_values,
                        max(consumption_history_values, default=1.0),
                    ),
                    max_points=13,
                    bar_label_formatter=lambda value: f"{float(value):.3f}" if value is not None else "",
                    line_label_formatter=lambda value: f"{float(value):.3f}" if value is not None else "",
                    bar_color="#D6D3D1",
                    line_color="#C2410C",
                    y_axis_label="纸袋配比",
                    legend_items=[("#D6D3D1", "月度配比"), ("#C2410C", "趋势线")],
                    show_bar_labels=True,
                    show_line_labels=False,
                    bar_label_position="above_center",
                ),
                "model_inventory_share_matrix": self._build_inventory_matrix(
                    rows=model_inventory_share_rows,
                    models=model_inventory_models,
                    value_key="model_shares",
                    total_key="total_inventory_qty",
                    title="各大区纸袋型号库存占比矩阵",
                    subtitle="在使用端确认偏大尺码异常后，再看库存端是否同步偏大，以识别订购结构是否放大了问题。",
                    color_rgb=(37, 99, 235),
                    value_formatter=lambda value: f"{float(value) * 100:.1f}%" if value is not None else "待补充",
                    total_formatter=lambda value: f"{(value / 10000):.1f}万" if value is not None else "待补充",
                ),
                "model_usage_share_matrix": self._build_inventory_matrix(
                    rows=model_usage_share_rows,
                    models=model_inventory_models,
                    value_key="model_shares",
                    total_key="total_sales_qty",
                    title="各大区纸袋使用量占比矩阵",
                    subtitle="先看各尺码实际使用占比是否偏离理论配比，再判断是否存在尺码错配或大袋小用风险。",
                    color_rgb=(2, 132, 199),
                    value_formatter=lambda value: f"{float(value) * 100:.1f}%" if value is not None else "待补充",
                    total_formatter=lambda value: f"{(value / 10000):.1f}万" if value is not None else "待补充",
                ),
                "stocktake_monthly_bar": self._build_svg_signed_bar_line_chart(
                    title=f"{month_title}全国纸袋盘点走势",
                    subtitle="盘盈为正、盘差为负，折线为盘盈与盘差合计后的总计值，0 刻度线位于图表中轴。",
                    labels=[item["label"] for item in stocktake_risks.get("monthly_rows", [])],
                    loss_values=[item.get("loss_qty") for item in stocktake_risks.get("monthly_rows", [])],
                    gain_values=[item.get("gain_qty") for item in stocktake_risks.get("monthly_rows", [])],
                    line_values=[item.get("total_qty") for item in stocktake_risks.get("monthly_rows", [])],
                    max_value=self._resolve_axis_max(
                        [
                            *(abs(item["loss_qty"]) for item in stocktake_risks.get("monthly_rows", []) if item.get("loss_qty") is not None),
                            *(abs(item["gain_qty"]) for item in stocktake_risks.get("monthly_rows", []) if item.get("gain_qty") is not None),
                            *(abs(item["total_qty"]) for item in stocktake_risks.get("monthly_rows", []) if item.get("total_qty") is not None),
                        ],
                        1.0,
                    ),
                    max_points=13,
                    y_axis_label="数量",
                    footer_note="柱状图分别展示盘差数量与盘盈数量，折线代表两者相加后的总计数量。",
                ),
                "stocktake_difference_bar": self._build_svg_signed_bar_line_chart(
                    title=f"{month_title}盘差率大于5%大区盘点分布",
                    subtitle="来源于盘差率大于5%大区明细卡片；盘盈为正、盘差为负，折线为盘盈与盘差合计后的总计值。",
                    labels=[item["region"] for item in stocktake_risks.get("difference_chart_rows", [])[:10]],
                    loss_values=[item.get("loss_qty") for item in stocktake_risks.get("difference_chart_rows", [])[:10]],
                    gain_values=[item.get("gain_qty") for item in stocktake_risks.get("difference_chart_rows", [])[:10]],
                    line_values=[item.get("total_qty") for item in stocktake_risks.get("difference_chart_rows", [])[:10]],
                    max_value=self._resolve_axis_max(
                        [
                            *(abs(item["loss_qty"]) for item in stocktake_risks.get("difference_chart_rows", [])[:10] if item.get("loss_qty") is not None),
                            *(abs(item["gain_qty"]) for item in stocktake_risks.get("difference_chart_rows", [])[:10] if item.get("gain_qty") is not None),
                            *(abs(item["total_qty"]) for item in stocktake_risks.get("difference_chart_rows", [])[:10] if item.get("total_qty") is not None),
                        ],
                        1.0,
                    ),
                    max_points=10,
                    y_axis_label="数量",
                    footer_note="用于替代原按大区盘点分布图，聚焦盘差率大于5%的重点大区。",
                ),
                "stocktake_difference_fiscal_qty_bar": self._build_svg_signed_bar_line_chart(
                    title=f"{month_title}盘差率大于5%盘点财年数量统计",
                    subtitle="来源于 nb692ce19d26a49569de3ca8；按财年展示盘亏数量、盘盈数量与净合计。",
                    labels=[item["label"] for item in stocktake_risks.get("difference_fiscal_rows", [])],
                    loss_values=[
                        self._scale_value(item.get("loss_qty"), 10000)
                        for item in stocktake_risks.get("difference_fiscal_rows", [])
                    ],
                    gain_values=[
                        self._scale_value(item.get("gain_qty"), 10000)
                        for item in stocktake_risks.get("difference_fiscal_rows", [])
                    ],
                    line_values=[
                        self._scale_value(item.get("total_qty"), 10000)
                        for item in stocktake_risks.get("difference_fiscal_rows", [])
                    ],
                    max_value=self._resolve_axis_max(
                        [
                            self._scale_value(abs(item["loss_qty"]), 10000)
                            for item in stocktake_risks.get("difference_fiscal_rows", [])
                            if item.get("loss_qty") is not None
                        ]
                        + [
                            self._scale_value(abs(item["gain_qty"]), 10000)
                            for item in stocktake_risks.get("difference_fiscal_rows", [])
                            if item.get("gain_qty") is not None
                        ]
                        + [
                            self._scale_value(abs(item["total_qty"]), 10000)
                            for item in stocktake_risks.get("difference_fiscal_rows", [])
                            if item.get("total_qty") is not None
                        ],
                        1.0,
                    ),
                    max_points=10,
                    y_axis_label="数量（万）",
                    footer_note="单位：万。柱状图分别展示盘亏数量与盘盈数量，折线代表两者相加后的净合计。",
                    value_formatter=lambda value: f"{float(value):.2f}".rstrip("0").rstrip("."),
                    legend_items=[("#DC2626", "盘亏数量"), ("#16A34A", "盘盈数量"), ("#0F172A", "净合计")],
                ),
                "stocktake_difference_fiscal_amount_bar": self._build_svg_signed_bar_line_chart(
                    title=f"{month_title}盘差率大于5%盘点财年金额统计",
                    subtitle="来源于 nb692ce19d26a49569de3ca8；按财年展示盘亏金额、盘盈金额与净合计。",
                    labels=[item["label"] for item in stocktake_risks.get("difference_fiscal_rows", [])],
                    loss_values=[
                        self._scale_value(item.get("loss_amount"), 1000000)
                        for item in stocktake_risks.get("difference_fiscal_rows", [])
                    ],
                    gain_values=[
                        self._scale_value(item.get("gain_amount"), 1000000)
                        for item in stocktake_risks.get("difference_fiscal_rows", [])
                    ],
                    line_values=[
                        self._scale_value(item.get("total_amount"), 1000000)
                        for item in stocktake_risks.get("difference_fiscal_rows", [])
                    ],
                    max_value=self._resolve_axis_max(
                        [
                            self._scale_value(abs(item["loss_amount"]), 1000000)
                            for item in stocktake_risks.get("difference_fiscal_rows", [])
                            if item.get("loss_amount") is not None
                        ]
                        + [
                            self._scale_value(abs(item["gain_amount"]), 1000000)
                            for item in stocktake_risks.get("difference_fiscal_rows", [])
                            if item.get("gain_amount") is not None
                        ]
                        + [
                            self._scale_value(abs(item["total_amount"]), 1000000)
                            for item in stocktake_risks.get("difference_fiscal_rows", [])
                            if item.get("total_amount") is not None
                        ],
                        0.01,
                    ),
                    max_points=10,
                    y_axis_label="金额（百万）",
                    footer_note="单位：百万。柱状图分别展示盘亏金额与盘盈金额，折线代表两者相加后的净合计。",
                    value_formatter=lambda value: f"{float(value):.3f}".rstrip("0").rstrip("."),
                    legend_items=[("#DC2626", "盘亏金额"), ("#16A34A", "盘盈金额"), ("#0F172A", "净合计")],
                ),
                "stocktake_monthly_matrix": self._build_stocktake_metric_matrix(
                    rows=stocktake_risks.get("monthly_rows", []),
                    row_key="label",
                    title="全国纸袋盘点月度矩阵",
                    subtitle="盘差数量保留正负号，总计为盘差数量与盘盈数量加总；色块越深表示绝对规模越高。",
                    metrics=[
                        {
                            "label": "盘差数量",
                            "value_getter": lambda item: item.get("loss_qty"),
                            "formatter": lambda value: self._fmt_int(value) if value is not None else "待补充",
                        },
                        {
                            "label": "盘盈数量",
                            "value_getter": lambda item: abs(item["gain_qty"]) if item.get("gain_qty") is not None else None,
                            "formatter": lambda value: self._fmt_int(value) if value is not None else "待补充",
                        },
                        {
                            "label": "总计",
                            "value_getter": lambda item: item.get("total_qty"),
                            "formatter": lambda value: self._fmt_int(value) if value is not None else "待补充",
                        },
                    ],
                    color_rgb=(217, 119, 6),
                ),
                "stocktake_region_bar": self._build_svg_signed_bar_line_chart(
                    title=f"{month_title}各大区纸袋盘点分布",
                    subtitle="盘盈为正、盘差为负，折线为盘盈与盘差合计后的总计值，0 刻度线位于图表中轴。",
                    labels=[item["region"] for item in stocktake_risks.get("regional_rows", [])[:10]],
                    loss_values=[item.get("loss_qty") for item in stocktake_risks.get("regional_rows", [])[:10]],
                    gain_values=[item.get("gain_qty") for item in stocktake_risks.get("regional_rows", [])[:10]],
                    line_values=[item.get("total_qty") for item in stocktake_risks.get("regional_rows", [])[:10]],
                    max_value=self._resolve_axis_max(
                        [
                            *(abs(item["loss_qty"]) for item in stocktake_risks.get("regional_rows", [])[:10] if item.get("loss_qty") is not None),
                            *(abs(item["gain_qty"]) for item in stocktake_risks.get("regional_rows", [])[:10] if item.get("gain_qty") is not None),
                            *(abs(item["total_qty"]) for item in stocktake_risks.get("regional_rows", [])[:10] if item.get("total_qty") is not None),
                        ],
                        1.0,
                    ),
                    max_points=10,
                    y_axis_label="数量",
                    footer_note="柱状图分别展示盘差数量与盘盈数量，折线代表两者相加后的总计数量。",
                ),
                "stocktake_region_matrix": self._build_stocktake_metric_matrix(
                    rows=stocktake_risks.get("regional_rows", [])[:10],
                    row_key="region",
                    title="按大区纸袋盘点矩阵",
                    subtitle="盘差数量保留正负号，总计为盘差数量与盘盈数量加总；色块越深表示绝对规模越高。",
                    metrics=[
                        {
                            "label": "盘差数量",
                            "value_getter": lambda item: item.get("loss_qty"),
                            "formatter": lambda value: self._fmt_int(value) if value is not None else "待补充",
                        },
                        {
                            "label": "盘盈数量",
                            "value_getter": lambda item: abs(item["gain_qty"]) if item.get("gain_qty") is not None else None,
                            "formatter": lambda value: self._fmt_int(value) if value is not None else "待补充",
                        },
                        {
                            "label": "总计",
                            "value_getter": lambda item: item.get("total_qty"),
                            "formatter": lambda value: self._fmt_int(value) if value is not None else "待补充",
                        },
                    ],
                    color_rgb=(220, 38, 38),
                ),
                "stocktake_difference_cards": self._build_stocktake_difference_cards(stocktake_difference_rows),
                "order_anomaly_region_bar": self._build_svg_bar_chart(
                    f"{month_title}重点地区异常订单分布",
                    [item["region"] for item in top_regional_anomalies],
                    [item["count"] for item in top_regional_anomalies],
                    self._resolve_axis_max(
                        [float(item["count"]) for item in top_regional_anomalies if item.get("count") is not None],
                        1.0,
                    ),
                    subtitle="用于识别异常订单更集中出现的地区。",
                ),
                "order_control_summary_cards": self._build_order_control_summary_cards(
                    total_orders=len(consumption_exceptions.get("order_anomalies", [])),
                    total_regions=len(top_regional_anomalies),
                    max_ratio=top_order_anomalies[0].get("ratio") if top_order_anomalies else None,
                ),
                "order_anomaly_cards": self._build_order_anomaly_cards(top_order_anomalies),
                "order_anomaly_region_table": self._build_order_anomaly_region_table(top_regional_anomalies),
                "order_anomaly_status_card": self._build_state_card(
                    title="配比控制状态",
                    message=order_anomaly_empty_reason if order_anomaly_empty_is_normal else "本期未识别异常订单。",
                    tone="success" if order_anomaly_empty_is_normal else "neutral",
                ),
            },
        }

    def _render_rich_text(self, value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        return text.replace("\n", "<br>")

    def _emphasize_text(self, value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""

        normalized = text.replace("<br>", "\n")
        placeholders: dict[str, str] = {}

        def alpha_token(index: int) -> str:
            result = ""
            current = index
            while True:
                result = chr(65 + (current % 26)) + result
                current = current // 26 - 1
                if current < 0:
                    break
            return result

        def protect(pattern: str, source: str) -> str:
            def replacer(match: re.Match[str]) -> str:
                token = f"ZZEMPH{alpha_token(len(placeholders))}ZZ"
                placeholders[token] = match.group(0)
                return token

            return re.sub(pattern, replacer, source, flags=re.DOTALL)

        protected = normalized
        protected = protect(r"\*\*.*?\*\*", protected)
        protected = protect(r"<strong\b[^>]*>.*?</strong>", protected)
        protected = protect(r"<code\b[^>]*>.*?</code>", protected)
        protected = protect(r"<[^>]+>", protected)
        protected = re.sub(
            r"(^|[\n；。])([ \t]*)([^：\n<>]{1,18}：)",
            lambda match: f"{match.group(1)}{match.group(2)}**{match.group(3)}**",
            protected,
        )
        protected = protect(r"\*\*.*?\*\*", protected)
        unit_pattern = r"(?:个地区型号|个地区|个大区|个型号|个百分点|个月|万元|万|元|分|单|家|月|天|倍|条|项|个|%)"
        for pattern in [
            rf"(?<![\d/])((?:>=|<=|>|<|±)\s*[+-]?\d+(?:\.\d+)?(?:\s*{unit_pattern})?)(?![\d/])",
            rf"(?<![\d/])([+-]?\d+(?:\.\d+)?(?:\s*{unit_pattern}))(?![\d/])",
            r"(?<![\d/])([+-]?\d+\.\d+)(?![\d/])",
        ]:
            protected = re.sub(pattern, r"**\1**", protected)
            protected = protect(r"\*\*.*?\*\*", protected)
        protected = re.sub(
            r"(红灯|黄灯|绿灯|P1|P2|P3|高风险|中风险|关注风险|补货压力|结构错配|异常订单|盘点损失|库存积压|库存短缺|优先处理|立即复核)",
            r"**\1**",
            protected,
        )
        for token, raw in placeholders.items():
            protected = protected.replace(token, raw)
        return protected.replace("\n", "<br>")

    def _generate_pdf(self, md_path: Path) -> None:
        pdf_path = md_path.with_suffix(".pdf")
        script = Path(__file__).resolve().parent.parent.parent / "scripts" / "html_to_pdf.js"
        if not script.exists():
            self._log_warning("PDF script not found at %s, skipping PDF generation", script)
            return
        try:
            result = subprocess.run(
                ["node", str(script), str(md_path), str(pdf_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                self.logger.info("Report PDF generated at %s", pdf_path)
            else:
                self._log_warning("PDF generation failed: %s", result.stderr.strip())
        except Exception as exc:
            self._log_warning("PDF generation error: %s", exc)

    def _log_warning(self, message: str, *args: Any) -> None:
        log_method = getattr(self.logger, "warning", None) or getattr(self.logger, "info", None)
        if log_method is not None:
            log_method(message, *args)

    def _center_table_headers(self, markdown: str) -> str:
        html_centered = re.sub(
            r'(<th\b[^>]*style="[^"]*)text-align:(?:left|right|center);',
            r"\1text-align:center;",
            markdown,
        )
        centered_lines: list[str] = []
        for line in html_centered.splitlines():
            if self._is_markdown_table_separator(line):
                cells = line.strip().strip("|").split("|")
                centered_lines.append("|" + "|".join(":---:" for _ in cells) + "|")
            else:
                centered_lines.append(line)
        return "\n".join(centered_lines) + ("\n" if html_centered.endswith("\n") else "")

    def _is_markdown_table_separator(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            return False
        cells = stripped.strip("|").split("|")
        return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells)

    def _build_mermaid_pie(self, title: str, items: list[tuple[str, int]]) -> str:
        valid_items = [(label, value) for label, value in items if value is not None]
        if not valid_items:
            return ""
        lines = ["```mermaid", "pie showData", f"    title {title}"]
        for label, value in valid_items:
            lines.append(f'    "{label}" : {value}')
        lines.append("```")
        return "\n".join(lines)

    def _build_mermaid_xychart(
        self,
        title: str,
        labels: list[str],
        values: list[float | None],
        max_value: float,
        chart_type: str = "bar",
        max_points: int | None = None,
        extra_series: list[dict[str, Any]] | None = None,
        y_axis_label: str = "数值",
    ) -> str:
        pairs = [(label, value) for label, value in zip(labels, values) if value is not None]
        if max_points:
            pairs = self._downsample_pairs(pairs, max_points)
        if not pairs:
            return ""

        chart_labels = ",".join(f'"{self._format_chart_label(label)}"' for label, _ in pairs)
        chart_values = ",".join(f"{value:.2f}" for _, value in pairs)
        lines = [
            "```mermaid",
            "xychart-beta",
            f'    title "{title}"',
            f"    x-axis [{chart_labels}]",
            f'    y-axis "{y_axis_label}" 0 --> {max_value:.2f}',
            f"    {chart_type} [{chart_values}]",
        ]
        if extra_series:
            for series in extra_series:
                series_values = series.get("values", [])
                if not series_values:
                    continue
                formatted_values = ",".join(f"{float(item):.2f}" for item in series_values)
                lines.append(f"    {series.get('chart_type', 'line')} [{formatted_values}]")
        lines.append("```")
        return "\n".join(lines)

    def _build_mermaid_xychart_multi(
        self,
        title: str,
        labels: list[str],
        series: list[dict[str, Any]],
        max_value: float,
        max_points: int | None = None,
        y_axis_label: str = "数值",
    ) -> str:
        if not labels or not series:
            return ""

        indices = self._downsample_indices(len(labels), max_points)
        sampled_labels = [labels[index] for index in indices]
        sampled_series: list[dict[str, Any]] = []
        for item in series:
            values = item.get("values", [])
            if not values:
                continue
            sampled_values = [values[index] if index < len(values) else None for index in indices]
            if not any(value is not None for value in sampled_values):
                continue
            sampled_series.append(
                {
                    "chart_type": item.get("chart_type", "bar"),
                    "values": sampled_values,
                }
            )

        if not sampled_labels or not sampled_series:
            return ""

        chart_labels = ",".join(f'"{self._format_chart_label(label)}"' for label in sampled_labels)
        lines = [
            "```mermaid",
            "xychart-beta",
            f'    title "{title}"',
            f"    x-axis [{chart_labels}]",
            f'    y-axis "{y_axis_label}" 0 --> {max_value:.2f}',
        ]
        for item in sampled_series:
            formatted_values = ",".join(
                f"{float(value):.2f}" if value is not None else "0.00"
                for value in item["values"]
            )
            lines.append(f"    {item['chart_type']} [{formatted_values}]")
        lines.append("```")
        return "\n".join(lines)

    def _build_panel_header(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        tag: str = "图表导读",
    ) -> str:
        tag_block = (
            f'<div style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#EEF2FF;color:#4338CA;font-size:10px;font-weight:700;letter-spacing:0.02em;">{tag}</div>'
            if tag
            else ""
        )
        subtitle_block = (
            f'<div style="max-width:56%;text-align:right;font-size:11px;color:#64748B;line-height:1.6;">{subtitle}</div>'
            if subtitle
            else ""
        )
        title_block = (
            f'<div style="font-size:13px;font-weight:600;color:#334155;margin-top:7px;line-height:1.5;">{title}</div>'
            if title
            else ""
        )
        return (
            '<div class="chart-heading" style="padding:12px 14px;background:linear-gradient(180deg,#FBFDFF 0%,#F8FAFC 100%);border-bottom:1px solid #E5E7EB;">'
            '<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">'
            '<div>'
            f"{tag_block}"
            f"{title_block}"
            '</div>'
            f'{subtitle_block}'
            '</div>'
            '</div>'
        )

    def _build_panel_footer(
        self,
        *,
        legend_items: list[tuple[str, str]] | None = None,
        note: str | None = None,
    ) -> str:
        parts: list[str] = []
        if legend_items:
            legend_parts = ['<div style="display:flex;flex-wrap:wrap;gap:14px 18px;align-items:center;">']
            for color, label in legend_items:
                legend_parts.append(
                    '<div style="display:flex;align-items:center;gap:6px;">'
                    f'<span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:{color};"></span>'
                    f'<span>{label}</span>'
                    '</div>'
                )
            legend_parts.append('</div>')
            parts.append("".join(legend_parts))
        if note:
            parts.append(f'<div style="font-size:11px;color:#64748B;line-height:1.6;">{note}</div>')
        if not parts:
            return ""
        return (
            '<div style="border-top:1px solid #E5E7EB;background:#FCFCFD;padding:9px 14px 10px 14px;display:grid;gap:6px;font-size:11px;color:#475569;">'
            + "".join(parts)
            + '</div>'
        )

    def _build_svg_bar_chart(
        self,
        title: str,
        labels: list[str],
        values: list[float | None],
        max_value: float,
        *,
        subtitle: str | None = None,
    ) -> str:
        pairs = [(label, value) for label, value in zip(labels, values) if value is not None]
        if not pairs:
            return ""

        chart_height = 180
        width = max(680, len(pairs) * 88)
        height = 250
        baseline_y = 196
        left_padding = 48
        step = (width - left_padding * 2) / max(1, len(pairs))
        bar_width = min(40, step * 0.46)
        scale = chart_height / max(max_value, 1.0)

        svg_parts = [
            f'<div class="chart-panel" style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header(title, subtitle),
            '<div style="padding:12px 14px 10px 14px;">',
            f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;overflow:visible;">',
            '<text x="6" y="16" fill="#6B7280" font-size="12">异常订单数</text>',
            f'<line x1="{left_padding}" y1="{baseline_y}" x2="{width - left_padding}" y2="{baseline_y}" stroke="#D1D5DB" stroke-width="1" />',
        ]

        for index, (label, value) in enumerate(pairs):
            center_x = left_padding + step * index + step / 2
            bar_height = float(value) * scale
            bar_y = baseline_y - bar_height
            svg_parts.append(
                f'<rect x="{center_x - bar_width / 2:.1f}" y="{bar_y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" '
                'rx="6" fill="#0F766E" opacity="0.88"></rect>'
            )
            svg_parts.append(
                f'<text x="{center_x:.1f}" y="{max(14, bar_y - 6):.1f}" text-anchor="middle" fill="#0F172A" font-size="11" font-weight="700">'
                f"{int(round(float(value)))}</text>"
            )
            svg_parts.append(
                f'<text x="{center_x:.1f}" y="{baseline_y + 18}" text-anchor="middle" fill="#475569" font-size="11">{self._format_chart_label(label)}</text>'
            )

        svg_parts.append("</svg></div></div>")
        return "\n".join(svg_parts)

    def _build_svg_combo_chart(
        self,
        title: str,
        labels: list[str],
        bar_values: list[float | None],
        line_values: list[float | None],
        max_value: float,
        *,
        min_value: float = 0.0,
        max_points: int | None = None,
        bar_label_formatter: Any,
        line_label_formatter: Any,
        bar_color: str,
        line_color: str,
        y_axis_label: str,
        subtitle: str | None = None,
        footer_note: str | None = None,
        legend_items: list[tuple[str, str]] | None = None,
        show_bar_labels: bool = True,
        show_line_labels: bool = True,
        bar_label_position: str = "above",
        line_label_position: str = "above",
    ) -> str:
        pairs = [
            (label, bar_value, line_value)
            for label, bar_value, line_value in zip(labels, bar_values, line_values)
            if bar_value is not None or line_value is not None
        ]
        if not pairs:
            return ""
        if max_points:
            indices = self._downsample_indices(len(pairs), max_points)
            pairs = [pairs[index] for index in indices]

        chart_height = 180
        width = max(680, len(pairs) * 88)
        height = 270
        baseline_y = 200
        left_padding = 48
        step = (width - left_padding * 2) / max(1, len(pairs))
        bar_width = min(34, step * 0.42)
        axis_span = max(max_value - min_value, 0.01)
        scale = chart_height / axis_span

        line_points: list[str] = []
        svg_parts = [
            f'<div class="chart-panel" style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header(title, subtitle),
            '<div style="padding:12px 14px 10px 14px;">',
            f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;overflow:visible;">',
            f'<text x="6" y="16" fill="#6B7280" font-size="12">{y_axis_label}</text>',
            f'<text x="8" y="{baseline_y + 4}" fill="#94A3B8" font-size="10">{min_value:.3f}</text>',
            f'<text x="8" y="{baseline_y - chart_height + 12}" fill="#94A3B8" font-size="10">{max_value:.3f}</text>',
            f'<line x1="{left_padding}" y1="{baseline_y}" x2="{width - left_padding}" y2="{baseline_y}" stroke="#D1D5DB" stroke-width="1" />',
        ]

        for index, (label, bar_value, line_value) in enumerate(pairs):
            center_x = left_padding + step * index + step / 2
            label_text = self._format_chart_label(label)
            if bar_value is not None:
                adjusted_bar_value = max(float(bar_value) - min_value, 0.0)
                bar_height = adjusted_bar_value * scale
                bar_y = baseline_y - bar_height
                bar_label_x = center_x - (10 if index % 2 == 0 else -10)
                bar_label_anchor = "end" if index % 2 == 0 else "start"
                if bar_label_position == "above_center":
                    bar_label_x = center_x
                    bar_label_anchor = "middle"
                    bar_label_y = max(16, bar_y - 4)
                elif bar_label_position == "below_center":
                    bar_label_x = center_x
                    bar_label_anchor = "middle"
                    bar_label_y = min(height - 28, baseline_y + 18)
                elif bar_label_position == "below":
                    bar_label_y = min(height - 28, baseline_y + 16 + (6 if index % 2 == 0 else 0))
                else:
                    bar_label_y = max(16, bar_y - 6 - (6 if index % 2 == 0 else 0))
                svg_parts.append(
                    f'<rect x="{center_x - bar_width / 2:.1f}" y="{bar_y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" '
                    f'rx="6" fill="{bar_color}" opacity="0.9"></rect>'
                )
                if show_bar_labels:
                    svg_parts.append(
                        f'<text x="{bar_label_x:.1f}" y="{bar_label_y:.1f}" text-anchor="{bar_label_anchor}" fill="#334155" font-size="11">'
                        f'{bar_label_formatter(bar_value)}</text>'
                    )
            if line_value is not None:
                point_y = baseline_y - max(float(line_value) - min_value, 0.0) * scale
                line_points.append(f"{center_x:.1f},{point_y:.1f}")
                line_label_x = center_x + (10 if index % 2 == 0 else -10)
                line_label_anchor = "start" if index % 2 == 0 else "end"
                if line_label_position == "below_center":
                    line_label_x = center_x
                    line_label_anchor = "middle"
                    line_label_y = min(height - 28, point_y + 18)
                elif line_label_position == "above_center":
                    line_label_x = center_x
                    line_label_anchor = "middle"
                    line_label_y = max(14, point_y - 12)
                elif line_label_position == "below":
                    line_label_y = min(height - 28, point_y + 18 + (6 if index % 2 == 1 else 0))
                else:
                    line_label_y = max(14, point_y - 12 - (6 if index % 2 == 1 else 0))
                svg_parts.append(
                    f'<circle cx="{center_x:.1f}" cy="{point_y:.1f}" r="4.5" fill="{line_color}" stroke="#FFFFFF" stroke-width="2"></circle>'
                )
                if show_line_labels:
                    svg_parts.append(
                        f'<text x="{line_label_x:.1f}" y="{line_label_y:.1f}" text-anchor="{line_label_anchor}" fill="{line_color}" font-size="11" font-weight="700">'
                        f'{line_label_formatter(line_value)}</text>'
                    )
            svg_parts.append(
                f'<text x="{center_x:.1f}" y="{baseline_y + 18}" text-anchor="middle" fill="#475569" font-size="11">{label_text}</text>'
            )

        if line_points:
            svg_parts.append(
                f'<polyline fill="none" stroke="{line_color}" stroke-width="2.5" points="{" ".join(line_points)}"></polyline>'
            )
        svg_parts.append('</svg></div>')
        if legend_items or footer_note:
            svg_parts.append(self._build_panel_footer(legend_items=legend_items, note=footer_note))
        svg_parts.append('</div>')
        return "\n".join(svg_parts)

    def _build_svg_multi_line_combo_chart(
        self,
        title: str,
        labels: list[str],
        bar_values: list[float | None],
        line_series: list[dict[str, Any]],
        max_value: float,
        *,
        min_value: float = 0.0,
        max_points: int | None = None,
        bar_label_formatter: Any,
        bar_color: str,
        y_axis_label: str,
        subtitle: str | None = None,
        footer_note: str | None = None,
        legend_items: list[tuple[str, str]] | None = None,
        show_bar_labels: bool = True,
        bar_label_position: str = "above",
    ) -> str:
        pairs = [
            (label, bar_value, [series.get("values", [])[index] if index < len(series.get("values", [])) else None for series in line_series])
            for index, (label, bar_value) in enumerate(zip(labels, bar_values))
            if bar_value is not None
            or any(
                (index < len(series.get("values", [])) and series.get("values", [])[index] is not None)
                for series in line_series
            )
        ]
        if not pairs:
            return ""
        if max_points:
            indices = self._downsample_indices(len(pairs), max_points)
            pairs = [pairs[index] for index in indices]

        chart_height = 180
        width = max(680, len(pairs) * 88)
        height = 270
        baseline_y = 200
        left_padding = 48
        step = (width - left_padding * 2) / max(1, len(pairs))
        bar_width = min(34, step * 0.42)
        axis_span = max(max_value - min_value, 0.01)
        scale = chart_height / axis_span

        polyline_points: list[list[str]] = [[] for _ in line_series]
        svg_parts = [
            f'<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header(title, subtitle),
            '<div style="padding:12px 14px 10px 14px;">',
            f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;overflow:visible;">',
            f'<text x="6" y="16" fill="#6B7280" font-size="12">{y_axis_label}</text>',
            f'<text x="8" y="{baseline_y + 4}" fill="#94A3B8" font-size="10">{min_value:.3f}</text>',
            f'<text x="8" y="{baseline_y - chart_height + 12}" fill="#94A3B8" font-size="10">{max_value:.3f}</text>',
            f'<line x1="{left_padding}" y1="{baseline_y}" x2="{width - left_padding}" y2="{baseline_y}" stroke="#D1D5DB" stroke-width="1" />',
        ]

        for index, (label, bar_value, line_values) in enumerate(pairs):
            center_x = left_padding + step * index + step / 2
            label_text = self._format_chart_label(label)
            if bar_value is not None:
                adjusted_bar_value = max(float(bar_value) - min_value, 0.0)
                bar_height = adjusted_bar_value * scale
                bar_y = baseline_y - bar_height
                bar_label_x = center_x - (10 if index % 2 == 0 else -10)
                bar_label_anchor = "end" if index % 2 == 0 else "start"
                if bar_label_position == "above_center":
                    bar_label_x = center_x
                    bar_label_anchor = "middle"
                    bar_label_y = max(16, bar_y - 4)
                elif bar_label_position == "below_center":
                    bar_label_x = center_x
                    bar_label_anchor = "middle"
                    bar_label_y = min(height - 28, baseline_y + 18)
                elif bar_label_position == "below":
                    bar_label_y = min(height - 28, baseline_y + 16 + (6 if index % 2 == 0 else 0))
                else:
                    bar_label_y = max(16, bar_y - 6 - (6 if index % 2 == 0 else 0))
                svg_parts.append(
                    f'<rect x="{center_x - bar_width / 2:.1f}" y="{bar_y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" '
                    f'rx="6" fill="{bar_color}" opacity="0.9"></rect>'
                )
                if show_bar_labels:
                    svg_parts.append(
                        f'<text x="{bar_label_x:.1f}" y="{bar_label_y:.1f}" text-anchor="{bar_label_anchor}" fill="#334155" font-size="11">'
                        f'{bar_label_formatter(bar_value)}</text>'
                    )

            for series_index, series in enumerate(line_series):
                line_value = line_values[series_index] if series_index < len(line_values) else None
                if line_value is None:
                    continue
                point_y = baseline_y - max(float(line_value) - min_value, 0.0) * scale
                polyline_points[series_index].append(f"{center_x:.1f},{point_y:.1f}")
                color = series.get("color", "#0F172A")
                label_formatter = series.get("label_formatter", lambda value: str(value))
                label_position = series.get("label_position", "above")
                if label_position == "below_center":
                    line_label_x = center_x
                    line_label_anchor = "middle"
                    line_label_y = min(height - 28, point_y + 18)
                elif label_position == "above_center":
                    line_label_x = center_x
                    line_label_anchor = "middle"
                    line_label_y = max(14, point_y - 12)
                elif label_position == "below":
                    line_label_x = center_x + (10 if index % 2 == 0 else -10)
                    line_label_anchor = "start" if index % 2 == 0 else "end"
                    line_label_y = min(height - 28, point_y + 18 + (6 if index % 2 == 1 else 0))
                else:
                    line_label_x = center_x + (10 if index % 2 == 0 else -10)
                    line_label_anchor = "start" if index % 2 == 0 else "end"
                    line_label_y = max(14, point_y - 12 - (6 if index % 2 == 1 else 0))
                svg_parts.append(
                    f'<circle cx="{center_x:.1f}" cy="{point_y:.1f}" r="4.5" fill="{color}" stroke="#FFFFFF" stroke-width="2"></circle>'
                )
                svg_parts.append(
                    f'<text x="{line_label_x:.1f}" y="{line_label_y:.1f}" text-anchor="{line_label_anchor}" fill="{color}" font-size="11" font-weight="700">'
                    f'{label_formatter(line_value)}</text>'
                )

            svg_parts.append(
                f'<text x="{center_x:.1f}" y="{baseline_y + 18}" text-anchor="middle" fill="#475569" font-size="11">{label_text}</text>'
            )

        for series_index, series in enumerate(line_series):
            if not polyline_points[series_index]:
                continue
            svg_parts.append(
                f'<polyline fill="none" stroke="{series.get("color", "#0F172A")}" stroke-width="2.5" points="{" ".join(polyline_points[series_index])}"></polyline>'
            )
        svg_parts.append('</svg></div>')
        if legend_items or footer_note:
            svg_parts.append(self._build_panel_footer(legend_items=legend_items, note=footer_note))
        svg_parts.append('</div>')
        return "\n".join(svg_parts)

    def _build_svg_signed_bar_line_chart(
        self,
        title: str,
        labels: list[str],
        loss_values: list[float | None],
        gain_values: list[float | None],
        line_values: list[float | None],
        max_value: float,
        *,
        max_points: int | None = None,
        y_axis_label: str,
        subtitle: str | None = None,
        footer_note: str | None = None,
        value_formatter: Any | None = None,
        legend_items: list[tuple[str, str]] | None = None,
    ) -> str:
        pairs = [
            (label, loss_value, gain_value, line_value)
            for label, loss_value, gain_value, line_value in zip(labels, loss_values, gain_values, line_values)
            if loss_value is not None or gain_value is not None or line_value is not None
        ]
        if not pairs:
            return ""
        if max_points:
            indices = self._downsample_indices(len(pairs), max_points)
            pairs = [pairs[index] for index in indices]

        width = max(760, len(pairs) * 96)
        height = 300
        chart_top = 28
        chart_bottom = 236
        baseline_y = (chart_top + chart_bottom) / 2
        half_height = (chart_bottom - chart_top) / 2
        left_padding = 48
        step = (width - left_padding * 2) / max(1, len(pairs))
        bar_width = min(18, step * 0.22)
        scale = half_height / max(max_value, 1.0)
        line_points: list[str] = []
        formatter = value_formatter or self._format_compact_quantity
        legend = legend_items or [("#DC2626", "盘差数量"), ("#16A34A", "盘盈数量"), ("#0F172A", "总计")]
        bar_label_style = 'paint-order:stroke;stroke:#FFFFFF;stroke-width:4px;stroke-linejoin:round;'
        line_label_style = 'paint-order:stroke;stroke:#FFFFFF;stroke-width:2.5px;stroke-linejoin:round;'
        svg_parts = [
            f'<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header(title, subtitle),
            '<div style="padding:12px 14px 10px 14px;">',
            f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;overflow:visible;">',
            f'<text x="6" y="16" fill="#6B7280" font-size="12">{y_axis_label}</text>',
            f'<text x="8" y="{chart_top + 8:.1f}" fill="#94A3B8" font-size="10">{formatter(max_value)}</text>',
            f'<text x="8" y="{baseline_y + 4:.1f}" fill="#94A3B8" font-size="10">0</text>',
            f'<text x="8" y="{chart_bottom + 4:.1f}" fill="#94A3B8" font-size="10">{formatter(-max_value)}</text>',
            f'<line x1="{left_padding}" y1="{chart_top}" x2="{width - left_padding}" y2="{chart_top}" stroke="#E5E7EB" stroke-width="1" stroke-dasharray="3 4" />',
            f'<line x1="{left_padding}" y1="{baseline_y}" x2="{width - left_padding}" y2="{baseline_y}" stroke="#D1D5DB" stroke-width="1" />',
            f'<line x1="{left_padding}" y1="{chart_bottom}" x2="{width - left_padding}" y2="{chart_bottom}" stroke="#E5E7EB" stroke-width="1" stroke-dasharray="3 4" />',
        ]

        def has_label_overlap(
            placed_labels: list[tuple[float, float]],
            x: float,
            y: float,
            *,
            x_gap: float = 26.0,
            y_gap: float = 16.0,
        ) -> bool:
            return any(abs(existing_x - x) < x_gap and abs(existing_y - y) < y_gap for existing_x, existing_y in placed_labels)

        for index, (label, loss_value, gain_value, line_value) in enumerate(pairs):
            center_x = left_padding + step * index + step / 2
            label_text = self._format_chart_label(label)
            rendered_labels: set[str] = set()
            placed_labels: list[tuple[float, float]] = []

            point_y: float | None = None
            line_label_x = center_x
            line_label_anchor = "middle"
            line_label_text: str | None = None
            line_label_candidates: list[float] = []
            if line_value is not None:
                point_y = baseline_y - float(line_value) * scale
                line_points.append(f"{center_x:.1f},{point_y:.1f}")
                line_offset = 10 if abs(point_y - baseline_y) > 10 else 14
                line_label_text = formatter(float(line_value))
                preferred_line_label_y = min(height - 20, point_y + line_offset)
                alternate_line_label_y = max(14, point_y - line_offset)
                line_label_candidates = [preferred_line_label_y]
                if abs(alternate_line_label_y - preferred_line_label_y) >= 8:
                    line_label_candidates.append(alternate_line_label_y)

            bar_center_x = center_x
            series_bars = [
                (loss_value, "#DC2626", "loss"),
                (gain_value, "#16A34A", "gain"),
            ]
            for value, color, kind in series_bars:
                if value in (None, 0):
                    continue
                numeric_value = float(value)
                bar_height = abs(numeric_value) * scale
                if numeric_value >= 0:
                    bar_y = baseline_y - bar_height
                    label_y_candidates = [
                        max(14, bar_y - 3),
                        max(14, bar_y - 15),
                    ]
                else:
                    bar_y = baseline_y
                    label_y_candidates = [
                        min(height - 20, baseline_y + bar_height + 18),
                        min(height - 20, baseline_y + bar_height + 30),
                    ]
                label_x = bar_center_x
                label_anchor = "middle"
                label_text_value = formatter(numeric_value)
                svg_parts.append(
                    f'<rect x="{bar_center_x - bar_width / 2:.1f}" y="{bar_y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" '
                    f'rx="6" fill="{color}" opacity="0.9"></rect>'
                )
                should_render_label = label_text_value not in rendered_labels
                if should_render_label:
                    for label_y in label_y_candidates:
                        if has_label_overlap(placed_labels, label_x, label_y):
                            continue
                        svg_parts.append(
                            f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="{label_anchor}" fill="#475569" font-size="10" style="{bar_label_style}">'
                            f"{label_text_value}</text>"
                        )
                        rendered_labels.add(label_text_value)
                        placed_labels.append((label_x, label_y))
                        break
            if line_value is not None:
                svg_parts.append(
                    f'<circle cx="{center_x:.1f}" cy="{point_y:.1f}" r="4" fill="#0F172A" stroke="#FFFFFF" stroke-width="2"></circle>'
                )
                if line_label_text not in rendered_labels:
                    for line_label_y in line_label_candidates:
                        if has_label_overlap(placed_labels, line_label_x, line_label_y, y_gap=18.0):
                            continue
                        svg_parts.append(
                            f'<text x="{line_label_x:.1f}" y="{line_label_y:.1f}" text-anchor="{line_label_anchor}" fill="#0F172A" font-size="11" font-weight="800" style="{line_label_style}">'
                            f"{line_label_text}</text>"
                        )
                        rendered_labels.add(line_label_text)
                        placed_labels.append((line_label_x, line_label_y))
                        break
            svg_parts.append(
                f'<text x="{center_x:.1f}" y="{chart_bottom + 20:.1f}" text-anchor="middle" fill="#475569" font-size="11">{label_text}</text>'
            )

        if line_points:
            svg_parts.append(
                f'<polyline fill="none" stroke="#0F172A" stroke-width="2.5" points="{" ".join(line_points)}"></polyline>'
            )
        svg_parts.append('</svg></div>')
        svg_parts.append(
            self._build_panel_footer(
                legend_items=legend,
                note=footer_note,
            )
        )
        svg_parts.append('</div>')
        return "\n".join(svg_parts)

    def _format_compact_quantity(self, value: float | int | None) -> str:
        if value is None:
            return "待补充"
        numeric = float(value)
        abs_numeric = abs(numeric)
        sign = "-" if numeric < 0 else ""
        if abs_numeric >= 100000000:
            compact = abs_numeric / 100000000
            return f"{sign}{compact:.1f}".rstrip("0").rstrip(".") + "亿"
        if abs_numeric >= 10000:
            compact = abs_numeric / 10000
            return f"{sign}{compact:.1f}".rstrip("0").rstrip(".") + "万"
        if abs_numeric >= 1000:
            compact = abs_numeric / 10000
            return f"{sign}{compact:.2f}".rstrip("0").rstrip(".") + "万"
        if abs_numeric.is_integer():
            return f"{sign}{int(abs_numeric)}"
        return f"{numeric:.1f}".rstrip("0").rstrip(".")

    def _resolve_axis_max(self, values: list[float | None], fallback: float) -> float:
        valid_values = [value for value in values if value is not None]
        if not valid_values:
            return fallback
        upper = max(valid_values)
        return max(fallback, upper * 1.2 if upper > 0 else fallback)

    def _scale_value(self, value: Any, divisor: float) -> float | None:
        if value is None:
            return None
        if divisor == 0:
            return float(value)
        return float(value) / divisor

    def _resolve_axis_min(self, values: list[float | None], floor: float) -> float:
        valid_values = [float(value) for value in values if value is not None]
        if len(valid_values) < 2:
            return floor
        lower = min(valid_values)
        upper = max(valid_values)
        spread = upper - lower
        if spread <= 0:
            return max(floor, lower * 0.95)
        padding = max(spread * 0.18, 0.01)
        return max(floor, lower - padding)

    def _downsample_pairs(self, pairs: list[tuple[str, float]], max_points: int) -> list[tuple[str, float]]:
        if max_points <= 0 or len(pairs) <= max_points:
            return pairs

        indices = self._downsample_indices(len(pairs), max_points)
        sampled = [pairs[index] for index in indices]
        return sampled

    def _downsample_indices(self, size: int, max_points: int | None) -> list[int]:
        if max_points is None or max_points <= 0 or size <= max_points:
            return list(range(size))
        step = max(1, size // (max_points - 1))
        indices = list(range(0, size, step))
        if indices[-1] != size - 1:
            indices.append(size - 1)
        if len(indices) > max_points:
            indices = indices[: max_points - 1] + [size - 1]
        return indices

    def _extract_chart_values(self, rows: list[dict[str, Any]], key: str) -> list[float]:
        return [float(item[key]) for item in rows if item.get(key) is not None]

    def _short_model(self, model: str) -> str:
        return model.replace("滔搏纸袋-", "")

    def _truncate_label(self, label: str, limit: int = 10) -> str:
        return label if len(label) <= limit else f"{label[:limit]}..."

    def _format_chart_label(self, label: str) -> str:
        normalized = str(label).strip().replace("/", "-")
        try:
            dt = datetime.strptime(normalized, "%Y-%m-%d")
            return f"{dt.month:02d}-{dt.day:02d}"
        except ValueError:
            pass
        if len(normalized) == 7:
            return normalized
        return self._truncate_label(normalized, 12)

    def _month_end(self, report_month: str) -> str:
        year, month = map(int, report_month.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-{last_day:02d}"

    def _fiscal_year_label(self, report_month: str) -> str:
        year = int(report_month.split("-")[0])
        return f"{year % 100:02d}财年"

    def _get_consumption_chart_title(self, report_month: str) -> str:
        """生成财年纸袋配比趋势图表标题，格式为：XX年- YY年财年纸袋配比趋势"""
        year = int(report_month.split("-")[0])
        fiscal_start_year = year - 1
        fiscal_end_year = year
        return f"{fiscal_start_year}年-{fiscal_end_year}年财年纸袋配比趋势"

    def _build_core_summary(
        self,
        *,
        inventory_overview: dict[str, Any],
        regional_rows: list[dict[str, Any]],
        purchase_analysis: dict[str, Any],
        model_inventory_analysis: list[dict[str, Any]],
        consumption_exceptions: dict[str, Any],
        stocktake_risks: dict[str, Any],
        inventory_green_max: float,
        inventory_yellow_max: float,
    ) -> dict[str, str]:
        ratio = inventory_overview.get("ratio")
        status = inventory_overview.get("status")
        yoy = inventory_overview.get("yoy")
        mom = inventory_overview.get("mom")
        yoy_base_ratio = inventory_overview.get("yoy_base_ratio")
        mom_base_ratio = inventory_overview.get("mom_base_ratio")

        ratio_text = (
            f"{self._strong_html(f'{ratio:.2f}')}（{status}）" if ratio is not None and status else "待补充"
        )
        trend_text = (
            f"同比 {self._strong_html(self._fmt_percent(yoy))}，环比 {self._strong_html(self._fmt_percent(mom))}，"
            f"同比对比基准：去年同月期末日库销比约为{self._strong_html(self._fmt_decimal(yoy_base_ratio))}，"
            f"环比对比基准：上月期末日库销比约为{self._strong_html(self._fmt_decimal(mom_base_ratio))}，"
            f"{self._inventory_trend_phase_label(mom)}"
        )

        flagged_regions = [row.get("region") for row in regional_rows if row.get("status") in {"红灯", "黄灯"}][:2]
        demand_gap_count = len(purchase_analysis.get("future_demand_gaps", []))
        structure_regions = [
            row.get("region")
            for row in model_inventory_analysis
            if row.get("structure_label") in {"库存偏小码积压", "库存偏大码积压", "使用偏大尺码"}
        ][:2]
        focus_stocktake_regions = [row.get("region") for row in stocktake_risks.get("focus_regions", [])[:2]]
        order_anomaly_count = sum(int(item.get("count") or 0) for item in consumption_exceptions.get("regional_anomaly_rows", []))

        problem_parts: list[str] = []
        if flagged_regions:
            problem_parts.append(f"整体压力仍集中在{'、'.join(str(item) for item in flagged_regions if item)}等大区库存未回到目标区间")
        if demand_gap_count:
            problem_parts.append(f"缺口侧仍有{demand_gap_count}个地区型号存在补货压力")
        if structure_regions:
            problem_parts.append(f"{'、'.join(str(item) for item in structure_regions if item)}等地区存在型号结构错配")
        if focus_stocktake_regions:
            problem_parts.append(f"{'、'.join(str(item) for item in focus_stocktake_regions if item)}等地区存在盘点损失，需立即复核并评估追损")
        if order_anomaly_count > 0:
            problem_parts.append(f"终端侧仍有{order_anomaly_count}单订单异常待复盘")
        if not problem_parts:
            problem_parts.append("整体库存、结构与终端执行风险可控")

        action_parts: list[str] = []
        if any(row.get("status") == "红灯" for row in regional_rows):
            action_parts.append("继续压降红黄灯大区库存")
        elif any(row.get("status") == "黄灯" for row in regional_rows):
            action_parts.append("继续压降黄灯大区库存")
        if purchase_analysis.get("history_evaluations"):
            action_parts.append("高风险型号停订去化")
        if purchase_analysis.get("future_demand_gaps"):
            action_parts.append("按未来30天预测补齐缺口型号")
        if any(row.get("structure_label") in {"库存偏小码积压", "库存偏大码积压", "使用偏大尺码"} for row in model_inventory_analysis):
            action_parts.append("纠正错配地区的型号结构")
        if order_anomaly_count > 0:
            action_parts.append("异常订单复盘纠偏")
        if stocktake_risks.get("focus_regions"):
            action_parts.append("完成重点盘点差异复核并评估追损")
        if not action_parts:
            action_parts.append("保持当前节奏并持续跟踪")

        return {
            "ratio_text": ratio_text,
            "trend_text": trend_text,
            "problem_text": "；".join(action for action in problem_parts),
            "action_text": "；".join(action for action in action_parts),
        }

    def _build_regional_rows_display(self, regional_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        display_rows: list[dict[str, Any]] = []
        for row in regional_rows:
            remark_parts: list[str] = []
            status = row.get("status")
            inbound_ratio = row.get("inbound_ratio")
            if status == "红灯":
                remark_parts.append("库存压力大，优先控订去化")
            elif status == "黄灯":
                remark_parts.append("库存偏高，需关注去化")
            elif status == "绿灯":
                remark_parts.append("处于目标区间")
            if inbound_ratio is not None and float(inbound_ratio) > 2:
                remark_parts.append("进销比偏高")
            elif inbound_ratio is not None and float(inbound_ratio) <= 1:
                remark_parts.append("进货节奏偏慢")
            display_rows.append(
                {
                    **row,
                    "status_text": status or "待补充",
                    "remark": "；".join(remark_parts) if remark_parts else "待补充",
                }
            )
        return display_rows

    def _build_regional_status_table_html(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        row_palette = {
            "红灯": ("rgba(254, 242, 242, 1)", "#7F1D1D", "#FECACA", "#FEE2E2"),
            "黄灯": ("rgba(254, 249, 195, 1)", "#713F12", "#FDE68A", "#FEF3C7"),
            "绿灯": ("rgba(240, 253, 244, 1)", "#14532D", "#BBF7D0", "#DCFCE7"),
        }
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">',
            '<thead style="background:#F8FAFC;color:#111827;">',
            '<tr>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">原销售大区</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计纸袋销售量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末业务库存量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末库销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计厂入量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">进销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">状态（红/黄/绿）</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">备注（问题/亮点）</th>'
            '</tr>',
            '</thead>',
            '<tbody>',
        ]
        for row in rows:
            status = row.get("status_text") or "待补充"
            row_bg, text_color, border_color, status_bg = row_palette.get(status, ("#FFFFFF", "#111827", "#E5E7EB", "#F8FAFC"))
            lines.append(
                f'<tr style="background:{row_bg};color:{text_color};">'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};font-weight:600;">{row.get("region", "待补充")}</td>'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("sales_qty"))}</strong></td>'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("inventory_qty"))}</strong></td>'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("ratio"))}</strong></td>'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("inbound_qty"))}</strong></td>'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("inbound_ratio"))}</strong></td>'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:center;">'
                f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:{status_bg};border:1px solid {border_color};font-weight:700;color:{text_color};">{status}</span>'
                f'</td>'
                f'<td style="padding:8px;border-bottom:1px solid {border_color};">{row.get("remark", "待补充")}</td>'
                '</tr>'
            )
        lines.extend(['</tbody>', '</table>', '</div>'])
        return "\n".join(lines)

    def _describe_ai_issue_type(self, item: dict[str, Any]) -> str:
        action_details = item.get("action_details", []) if isinstance(item, dict) else []
        action_types = {detail.get("type") for detail in action_details if isinstance(detail, dict)}
        if "stocktake" in action_types and ("overstock" in action_types or "shortage" in action_types or "shortage_buffer" in action_types):
            return "库存与盘点复合问题"
        if "stocktake" in action_types and "order_anomaly" in action_types:
            return "终端与盘点复合问题"
        if "order_anomaly" in action_types and ("overstock" in action_types or "shortage" in action_types or "shortage_buffer" in action_types):
            return "库存与终端复合问题"
        if {"overstock", "shortage"} <= action_types:
            return "库存与补货并发"
        if "overstock" in action_types:
            return "高库存去化"
        if "shortage" in action_types or "shortage_buffer" in action_types:
            return "缺口补货"
        if "order_anomaly" in action_types:
            return "终端执行偏差"
        if "stocktake" in action_types:
            return "盘点差异复核"
        return "综合优化"

    def _normalize_ai_issue_type_label(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        parts = [
            re.sub(r"\s+", " ", part).strip()
            for part in re.split(r"\s*(?:\+|/|｜|\||、|，|；)\s*", text)
            if str(part).strip()
        ]
        normalized_parts: list[str] = []
        seen: set[str] = set()
        for part in parts:
            if part in seen:
                continue
            seen.add(part)
            normalized_parts.append(part)
        return " + ".join(normalized_parts)

    def _dedupe_delimited_text(self, value: Any, fallback: str = "") -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        parts = [
            re.sub(r"[。]+$", "", part.strip())
            for part in re.split(r"[；;]+", text)
            if str(part).strip()
        ]
        deduped_parts: list[str] = []
        seen: set[str] = set()
        for part in parts:
            if not part or part in seen:
                continue
            seen.add(part)
            deduped_parts.append(part)
        return "；".join(deduped_parts) if deduped_parts else fallback

    def _build_priority_action_group_metas(
        self,
        *,
        inventory_preview_items: list[dict[str, Any]],
        usage_preview_items: list[dict[str, Any]],
        terminal_preview_items: list[dict[str, Any]],
        inventory_all_items: list[dict[str, Any]],
        usage_all_items: list[dict[str, Any]],
        terminal_all_items: list[dict[str, Any]],
        include_empty_groups: bool = False,
        scope_label: str = "",
    ) -> list[dict[str, Any]]:
        group_specs = [
            {
                "key": "inventory",
                "label": "库销与库存类",
                "tone": "blue",
                "description": "聚焦高库存、缺口补货与结构修正。",
                "empty_message": f"本期暂无{scope_label + ' ' if scope_label else ''}库销与库存类动作，常规跟踪即可。",
                "preview_items": inventory_preview_items,
                "all_items": inventory_all_items,
            },
            {
                "key": "usage",
                "label": "纸袋使用合规类",
                "tone": "orange",
                "description": "聚焦大袋小用、小袋多用与尺码纠偏。",
                "empty_message": f"本期暂无{scope_label + ' ' if scope_label else ''}纸袋使用合规类动作，维持当前口径。",
                "preview_items": usage_preview_items,
                "all_items": usage_all_items,
            },
            {
                "key": "terminal",
                "label": "终端异常 / 盘点类",
                "tone": "yellow",
                "description": "聚焦异常订单与盘点差异整改。",
                "empty_message": f"本期暂无{scope_label + ' ' if scope_label else ''}终端异常 / 盘点类动作，持续监控即可。",
                "preview_items": terminal_preview_items,
                "all_items": terminal_all_items,
            },
        ]
        groups = [
            self._build_priority_action_group_meta(
                key=spec["key"],
                label=spec["label"],
                tone=spec["tone"],
                description=spec["description"],
                preview_items=spec["preview_items"],
                all_items=spec["all_items"],
                empty_message=spec["empty_message"],
            )
            for spec in group_specs
        ]
        if include_empty_groups:
            return groups
        return [group for group in groups if group["total_count"] > 0]

    def _build_priority_action_group_meta(
        self,
        *,
        key: str,
        label: str,
        tone: str,
        description: str,
        preview_items: list[dict[str, Any]],
        all_items: list[dict[str, Any]],
        empty_message: str,
    ) -> dict[str, Any]:
        total_count = len(all_items)
        p1_count = sum(1 for item in all_items if item.get("priority") == "P1")
        p2_count = sum(1 for item in all_items if item.get("priority") == "P2")
        issue_labels: list[str] = []
        for item in all_items:
            label_text = self._normalize_ai_issue_type_label(item.get("issue_type_label"))
            if label_text and label_text not in issue_labels:
                issue_labels.append(label_text)
        display_count = len(preview_items)
        issue_snapshot = self._summarize_action_group_issue_snapshot(key, issue_labels)
        return {
            "key": key,
            "label": label,
            "tone": tone,
            "description": description,
            "items": preview_items,
            "total_count": total_count,
            "display_count": display_count,
            "count_label": f"{total_count}项动作" if total_count else "暂无动作",
            "priority_mix": f"P1 {p1_count}项 / P2 {p2_count}项" if total_count else "本期无重点动作",
            "issue_snapshot": issue_snapshot,
            "display_hint": (
                f"当前仅展示前{display_count}项，完整清单见第七部分。"
                if total_count and display_count and display_count < total_count
                else ""
            ),
            "empty_message": empty_message,
        }

    def _build_priority_action_preview_grid_items(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        preview_items: list[dict[str, Any]] = []
        for group in groups:
            for item in group.get("items", []):
                preview_items.append(
                    {
                        **item,
                        "group_label": group.get("label", ""),
                        "group_tone": group.get("tone", "neutral"),
                    }
                )
        return preview_items

    def _summarize_action_group_issue_snapshot(self, key: str, issue_labels: list[str]) -> str:
        if not issue_labels:
            return ""
        if key == "usage":
            parts: list[str] = []
            for label in issue_labels:
                for part in label.split(" + "):
                    normalized = part.strip()
                    if normalized and normalized not in parts:
                        parts.append(normalized)
            summary_parts: list[str] = []
            if any("大袋小用" in part for part in parts):
                summary_parts.append("大袋小用")
            elif parts:
                summary_parts.append(parts[0])
            inventory_parts = [part for part in parts if "库存" in part]
            if inventory_parts:
                summary_parts.append("库存健康问题" if len(inventory_parts) > 1 else inventory_parts[0])
            return "、".join(summary_parts[:2])
        return "、".join(issue_labels[:2])

    def _split_priority_action_groups(
        self,
        items: list[dict[str, Any]],
        max_per_group: int | None = 2,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        inventory_items: list[dict[str, Any]] = []
        usage_items: list[dict[str, Any]] = []
        terminal_items: list[dict[str, Any]] = []
        for item in items:
            group = self._classify_priority_action_group(item)
            if group == "usage":
                if max_per_group is None or len(usage_items) < max_per_group:
                    usage_items.append(item)
            elif group == "terminal":
                if max_per_group is None or len(terminal_items) < max_per_group:
                    terminal_items.append(item)
            else:
                if max_per_group is None or len(inventory_items) < max_per_group:
                    inventory_items.append(item)
        return inventory_items, usage_items, terminal_items

    def _classify_priority_action_group(self, item: dict[str, Any]) -> str:
        label = str(item.get("issue_type_label") or "")
        action_details = item.get("action_details", []) if isinstance(item, dict) else []
        action_types = {detail.get("type") for detail in action_details if isinstance(detail, dict)}

        usage_keywords = ("大袋小用", "使用", "合规")
        terminal_keywords = ("终端", "异常订单", "盘点")
        inventory_keywords = ("库存", "库销", "补货", "缺口", "高库存")

        if any(keyword in label for keyword in usage_keywords):
            return "usage"
        if "diagnosis" in action_types:
            return "usage"
        if any(keyword in label for keyword in terminal_keywords):
            return "terminal"
        if action_types & {"order_anomaly", "stocktake"}:
            return "terminal"
        if any(keyword in label for keyword in inventory_keywords):
            return "inventory"
        if action_types & {"overstock", "shortage", "shortage_buffer"}:
            return "inventory"
        return "inventory"

    def _build_ai_review_metric_text(self, item: dict[str, Any]) -> str:
        baseline = item.get("baseline", {}) if isinstance(item, dict) else {}
        parts = [
            f"高库存组合{self._strong_html(str(int(baseline.get('high_inventory_count') or 0)))}个",
            f"需求缺口{self._strong_html(str(int(baseline.get('future_gap_count') or 0)))}个",
            f"异常订单{self._strong_html(str(int(baseline.get('order_anomaly_count') or 0)))}单",
            f"净盘差{self._strong_html(self._fmt_int(baseline.get('stocktake_net_loss_qty'))) if baseline.get('stocktake_net_loss_qty') is not None else '无'}",
        ]
        return "；".join(parts)

    def _build_ai_issue_type_brief(self, value: Any) -> str:
        text = self._normalize_ai_issue_type_label(value)
        parts = [part.strip() for part in text.split(" + ") if part.strip()]
        has_usage = any(part in {"大袋小用", "未合并装袋（小袋多用）", "合包问题"} for part in parts)
        has_blocking_stock = any(part == "库存无法支持合理使用" for part in parts)
        has_structure_stock = any(part == "库存结构不科学" for part in parts)
        brief_parts: list[str] = []
        if has_usage:
            brief_parts.append("使用失衡")
        if has_blocking_stock:
            brief_parts.append("库存受限")
        elif has_structure_stock:
            brief_parts.append("库存错配")
        if not brief_parts:
            return text
        return " + ".join(brief_parts)

    def _build_ai_priority_reason_brief(self, item: dict[str, Any]) -> str:
        baseline = item.get("baseline", {}) if isinstance(item, dict) else {}
        parts: list[str] = []
        if baseline.get("diagnosis_composite_score") is not None:
            parts.append(f"{float(baseline.get('diagnosis_composite_score')):g}分")
        elif item.get("severity_score") is not None:
            parts.append(f"{float(item['severity_score']):g}分")
        root_cause_brief = self._build_ai_root_cause_brief(item)
        issue_count = len([part for part in re.split(r"[；;]", str(root_cause_brief)) if str(part).strip()])
        if issue_count:
            parts.append(f"{issue_count}类")
        return "｜".join(parts) if parts else str(item.get("priority_reason") or item.get("priority_rule") or "待补充")

    def _build_ai_root_cause_brief(self, item: dict[str, Any]) -> str:
        raw = str(item.get("root_cause_multiline") or item.get("root_cause") or "").strip()
        if not raw:
            return "待补充"
        parts = [part.strip() for part in re.split(r"(?:<br>|；|;)", raw) if part.strip()]
        simplified: list[str] = []
        for part in parts:
            clean = re.sub(r"^\d+\.\s*", "", part)
            clean = re.sub(r"<[^>]+>", "", clean).strip()
            overstock_match = re.search(r"(.+?)期末库存.*?超储(\d+)个", clean)
            if overstock_match:
                model_text, qty_text = overstock_match.groups()
                simplified.append(f"{model_text.strip()}超储{int(qty_text):,}个")
                continue
            shortage_match = re.search(r"(.+?)期末库存.*?需补(\d+)个", clean)
            if shortage_match:
                model_text, qty_text = shortage_match.groups()
                simplified.append(f"{model_text.strip()}需补{int(qty_text):,}个")
                continue
            if "理论使用需求占比" in clean or "实际使用占比" in clean and "大袋小用" not in clean:
                continue
            if "大袋小用" in clean:
                simplified.append("大袋小用偏高")
                continue
            if "小袋多用订单占比" in clean:
                match = re.search(r"小袋多用订单占比([^。；<]+)", clean)
                ratio_text = match.group(1).strip() if match else ""
                simplified.append(f"小袋多用{ratio_text}".rstrip("。"))
                continue
            if "无法支撑门店按推荐方案使用" in clean:
                size_match = re.search(r"([A-Z]+)码", clean)
                size_text = size_match.group(1) + "码" if size_match else "目标尺码"
                simplified.append(f"{size_text}缺口，暂不纠偏")
                continue
            if "存在积压风险" in clean:
                size_match = re.search(r"([A-Z]+)码", clean)
                size_text = size_match.group(1) + "码" if size_match else "相关尺码"
                simplified.append(f"{size_text}偏高，先去化")
                continue
            if "需在后续订购中补齐" in clean:
                size_match = re.search(r"([A-Z]+)码", clean)
                size_text = size_match.group(1) + "码" if size_match else "相关尺码"
                simplified.append(f"{size_text}偏低，后续补齐")
                continue
        deduped: list[str] = []
        for part in simplified:
            if part not in deduped:
                deduped.append(part)
        return "；".join(deduped[:3]) if deduped else self._dedupe_delimited_text(raw, "待补充")

    def _build_ai_business_plan_brief(self, item: dict[str, Any]) -> str:
        raw = str(item.get("business_plan") or "").strip()
        if not raw:
            return "待补充"
        lines = [line.strip() for line in raw.split("<br>") if line.strip()]
        compact: list[str] = []
        for line in lines:
            text = re.sub(r"<[^>]+>", "", line).rstrip("。")
            text = re.sub(r"^紧急补齐(.+?)码库存，目标库存深度≥1个月$", r"补\1码至1个月", text)
            text = re.sub(r"^暂停或压降(.+?)码订购，优先调拨与消化存量$", r"停\1码去化", text)
            text = re.sub(r"^复盘(.+?)码替代(.+?)码的场景，按理论配比纠偏，避免大袋小用$", r"纠偏\1替\2", text)
            text = re.sub(r"^复核合包规则与门店执行，重点减少重复拆分装袋和额外加袋$", "压降拆分装袋", text)
            text = re.sub(r"^复核合包规则与门店执行，减少偏小尺码拆分装袋$", "压降小码拆袋", text)
            text = re.sub(r"^\d+\.\s*(.+?)：库存积压.*立即停止订购$", r"\1停订去化", text)
            text = re.sub(r"^\d+\.\s*(.+?)：库存偏紧.*预留补货(\d+)个$", lambda m: f"{m.group(1)}补货{int(m.group(2)):,}个", text)
            text = re.sub(r"^\d+\.\s*(.+?)：库存短缺.*尽快补货(\d+)个$", lambda m: f"{m.group(1)}补货{int(m.group(2)):,}个", text)
            compact.append(text)
        return "<br>".join(compact[:3]) if compact else "待补充"

    def _build_ai_review_metric_brief(self, item: dict[str, Any]) -> str:
        text = str(item.get("review_metric_text") or "").strip()
        match = re.search(r"下月综合得分目标≥\s*([0-9.]+)分（当前([0-9.]+)分）", text)
        if match:
            target, current = match.groups()
            return f"综合分≥{target}（现{current}）"
        baseline = item.get("baseline", {}) if isinstance(item, dict) else {}
        bits: list[str] = []
        if baseline.get("high_inventory_count"):
            bits.append(f"高库存{int(baseline.get('high_inventory_count') or 0)}")
        if baseline.get("future_gap_count"):
            bits.append(f"缺口{int(baseline.get('future_gap_count') or 0)}")
        if baseline.get("order_anomaly_count"):
            bits.append(f"异常单{int(baseline.get('order_anomaly_count') or 0)}")
        if bits:
            return "｜".join(bits)
        return text or self._build_ai_review_metric_text(item)

    def _build_ai_priority_rule_text(self, item: dict[str, Any]) -> str:
        priority = str(item.get("priority") or "P3")
        severity = item.get("severity_score")
        severity_text = f"{float(severity):g}分" if severity is not None else "待补充"
        if priority == "P1":
            return f"P1规则：严重度评分{severity_text}，达到>=5的最高优先级阈值。"
        if priority == "P2":
            return f"P2规则：严重度评分{severity_text}，达到3-4的常规优先级阈值。"
        return f"P3规则：严重度评分{severity_text}，低于P1/P2展示阈值。"

    def _build_ai_priority_reason_text(self, item: dict[str, Any]) -> str:
        priority = str(item.get("priority") or "P3")
        baseline = item.get("baseline", {}) if isinstance(item, dict) else {}
        parts: list[str] = []
        if item.get("severity_score") is not None:
            parts.append(f"严重度评分{float(item['severity_score']):g}分")
        if baseline.get("high_inventory_count"):
            parts.append(f"高库存组合{int(baseline.get('high_inventory_count') or 0)}个")
        if baseline.get("future_gap_count"):
            parts.append(f"需求缺口{int(baseline.get('future_gap_count') or 0)}个")
        if baseline.get("order_anomaly_count"):
            parts.append(f"异常订单{int(baseline.get('order_anomaly_count') or 0)}单")
        if baseline.get("stocktake_net_loss_qty") not in (None, 0):
            parts.append("存在盘点差异")
        if baseline.get("diagnosis_composite_score") is not None:
            parts.append(f"健康度综合得分{float(baseline.get('diagnosis_composite_score')):g}分")
        return f"{priority}判定：" + ("；".join(parts) if parts else "依据关键问题数量和严重度评分判定")

    def _build_purchase_report_empty_message(
        self,
        *,
        purchase_alerts: list[dict[str, Any]],
        purchase_joined_rows: list[dict[str, Any]],
    ) -> str:
        if purchase_alerts:
            return ""
        if purchase_joined_rows:
            return (
                f"本期已完成 a597 与 u114 的地区型号拼接，共得到{len(purchase_joined_rows)}条候选数据；"
                "但进一步套用“库存大于1万、当期期末库销大于2.5、近30天厂入量大于0”后暂无命中组合。"
            )
        return "按 a597 与 u114 联表规则，本期暂无同时满足“库存大于1万、当期期末库销大于2.5、近30天厂入量大于0”的地区型号组合。"

    def _strong_html(self, value: str) -> str:
        return f'<strong style="color:#111827;">{value}</strong>'

    def _format_structure_label_with_gap(self, row: dict[str, Any]) -> str:
        label = str(row.get("structure_label") or "待补充")
        gap_pp = row.get("structure_gap_pp")
        if gap_pp is None:
            return label
        return f"{label}（差异{float(gap_pp):.1f}个百分点）"

    def _build_ai_priority_standard(self) -> str:
        return (
            "第七模块优先级由规则字段生成并随行动项展示：P1为严重度评分≥5或健康度诊断触发最高优先级；"
            "<br>"
            "P2为严重度评分3-4或健康度诊断识别结构性问题；排序固定为P1优先、P2其次、同级按严重度降序。"
        )

    def _build_purchase_risk_rows(
        self,
        *,
        purchase_alerts: list[dict[str, Any]],
        inventory_green_max: float,
        inventory_yellow_max: float,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in purchase_alerts:
            inbound_ratio = item.get("inbound_ratio")
            ratio = item.get("ratio")
            future_ratio = item.get("future_ratio")
            if ratio is None or inbound_ratio is None:
                continue
            ratio_gap = item.get("opening_ratio")
            if ratio_gap is None:
                ratio_gap = float(ratio) - float(inbound_ratio)
            risk_rule = self._purchase_risk_rule_from_level(item.get("purchase_risk_level"), item.get("diagnosis"))
            if risk_rule is None:
                risk_rule = self._classify_purchase_risk_rule(
                    opening_ratio=float(ratio_gap),
                    inbound_ratio=float(inbound_ratio),
                    ending_ratio=float(ratio),
                    future_ratio=float(future_ratio) if future_ratio is not None else None,
                    inventory_green_max=inventory_green_max,
                    inventory_yellow_max=inventory_yellow_max,
                )

            if risk_rule is None:
                continue
            future_light = self._inventory_light_by_thresholds(
                future_ratio,
                inventory_green_max=inventory_green_max,
                inventory_yellow_max=inventory_yellow_max,
            )
            future_ratio_display = "待补充"
            if future_ratio is not None:
                future_ratio_display = self._fmt_decimal(future_ratio)
                if future_light in {"红灯", "黄灯"}:
                    future_ratio_display = f"{future_ratio_display}（{future_light}）"
            rows.append(
                {
                    **item,
                    "region_model": f"{item.get('region', '待补充')}-{item.get('model', '待补充')}",
                    "ratio_gap": ratio_gap,
                    "future_ratio_display": future_ratio_display,
                    "risk_level": risk_rule["risk_level"],
                    "handling_principle": risk_rule["handling_principle"],
                    "rule_name": risk_rule["rule_name"],
                }
            )
        return rows[:12]

    def _purchase_risk_rule_from_level(self, level: Any, diagnosis: Any = None) -> dict[str, str] | None:
        normalized = str(level or "").strip().upper()
        diagnosis_text = str(diagnosis or "")
        if normalized == "P1":
            return {
                "risk_level": "P1（高风险）",
                "handling_principle": "当前库销比处于高位且进销比偏高，暂停新增订购并优先消化库存",
                "rule_name": "P1：高库销&高进销，订购偏多风险",
            }
        if normalized == "P2":
            return {
                "risk_level": "P2（中风险）",
                "handling_principle": "当前库销比仍处高位但进销比不高，控制新增订购并跟进历史积压消化",
                "rule_name": "P2：高库销&低进销，持续积压风险",
            }
        if normalized == "P3":
            return {
                "risk_level": "P3（关注风险）",
                "handling_principle": "本期有厂入且期末进入黄灯，持续跟踪消化节奏",
                "rule_name": "P3：期末黄灯，关注跟踪",
            }
        if "高库销高进销" in diagnosis_text:
            return self._purchase_risk_rule_from_level("P1", diagnosis_text)
        if "高库销低进销" in diagnosis_text or "持续积压" in diagnosis_text:
            return self._purchase_risk_rule_from_level("P2", diagnosis_text)
        return None

    def _classify_purchase_risk_rule(
        self,
        *,
        opening_ratio: float,
        inbound_ratio: float,
        ending_ratio: float,
        future_ratio: float | None,
        inventory_green_max: float,
        inventory_yellow_max: float,
    ) -> dict[str, str] | None:
        if inbound_ratio <= 0:
            return None
        if future_ratio is not None and future_ratio <= inventory_green_max:
            return None

        opening_red = opening_ratio > inventory_yellow_max
        opening_yellow = inventory_green_max < opening_ratio <= inventory_yellow_max
        opening_green = opening_ratio <= inventory_green_max
        ending_red = ending_ratio > inventory_yellow_max
        ending_yellow = inventory_green_max < ending_ratio <= inventory_yellow_max

        if opening_red and (ending_red or ending_yellow):
            return {
                "risk_level": "P1（高风险）",
                "handling_principle": "期初库销已严重偏高，期末与预测仍在红黄区间，暂停新增订购并优先消化库存",
                "rule_name": "规则1（P1：期初红，期末红，预测红/黄）",
            }
        if opening_yellow and ending_red:
            return {
                "risk_level": "P1（高风险）",
                "handling_principle": "期初黄灯且期末转红，高库销纸袋停止订购并复核本期订购合理性",
                "rule_name": "规则2（P1：期初黄，期末红，预测红/黄）",
            }
        if opening_yellow and ending_yellow:
            return {
                "risk_level": "P2（中风险）",
                "handling_principle": "期初和期末均为黄灯，控制新增订购并跟进库存消化",
                "rule_name": "规则3（P2：期初黄，期末黄，预测红/黄）",
            }
        if opening_green and ending_red:
            return {
                "risk_level": "P2（中风险）",
                "handling_principle": "期初绿灯但期末转红，复核本期进货节奏并压降新增采购",
                "rule_name": "规则4（P2：期初绿，期末红，预测红/黄）",
            }
        if opening_green and ending_yellow:
            return {
                "risk_level": "P3（关注风险）",
                "handling_principle": "期初绿灯但期末转黄，需跟踪但优先级低于P1/P2",
                "rule_name": "规则5（P3：期初绿，期末黄，预测红/黄）",
            }
        return None

    def _filter_purchase_scenario_rows(
        self,
        purchase_alerts: list[dict[str, Any]],
        purchase_risk_rows: list[dict[str, Any]],
        *,
        scenario: str,
        fallback_level: str,
    ) -> list[dict[str, Any]]:
        scenario_rows = [
            item
            for item in purchase_alerts
            if item.get("inbound_scenario") == scenario or scenario in str(item.get("diagnosis") or "")
        ]
        if scenario_rows:
            return scenario_rows
        return [item for item in purchase_risk_rows if item.get("risk_level") == fallback_level]

    def _inventory_light_by_thresholds(
        self,
        ratio: float | None,
        *,
        inventory_green_max: float,
        inventory_yellow_max: float,
    ) -> str:
        if ratio is None:
            return "待补充"
        if float(ratio) <= inventory_green_max:
            return "绿灯"
        if float(ratio) <= inventory_yellow_max:
            return "黄灯"
        return "红灯"

    def _inventory_trend_phase_label(self, mom: float | None) -> str:
        if mom is None:
            return "去库存趋势待补充"
        if mom <= -0.05:
            return "去库存加快"
        if mom >= 0.05:
            return "去库存放缓"
        return "去库存平稳"

    def _fmt_percent(self, value: Any) -> str:
        if value is None:
            return "待补充"
        return f"{float(value) * 100:.2f}%"

    def _build_consumption_trend_summary(self, ratio_history: list[dict[str, Any]], report_month: str) -> str:
        if not ratio_history:
            return "财年纸袋配比趋势数据不足，暂无法判断波动区间。"

        series = [item for item in ratio_history if item.get("value") is not None]
        if not series:
            return "财年纸袋配比趋势数据不足，暂无法判断波动区间。"

        current = next((item for item in series if str(item.get("label", "")).startswith(report_month)), series[-1])
        peak = max(series, key=lambda item: item["value"])
        trough = min(series, key=lambda item: item["value"])
        return (
            f"财年内纸袋配比波动区间为{float(trough['value']):.3f}-{float(peak['value']):.3f}；"
            f"{current['label']}当前值为{float(current['value']):.3f}，"
            f"较高点{peak['label']} {'回落' if float(current['value']) <= float(peak['value']) else '抬升'}"
            f"{abs(float(current['value']) - float(peak['value'])):.3f}。"
        )

    def _constant_series(self, source_size: int, value: float, max_points: int | None = None) -> list[float]:
        pairs = [("", value) for _ in range(source_size)]
        if max_points:
            pairs = self._downsample_pairs(pairs, max_points)
        return [item[1] for item in pairs]

    def _status_badge(self, status: str | None) -> str:
        palette = {
            "绿灯": ("#E8F5E9", "#2E7D32", "#C8E6C9"),
            "黄灯": ("#FFF8E1", "#B26A00", "#FFE082"),
            "红灯": ("#FDECEA", "#C62828", "#F5C6CB"),
        }
        label = str(status or "待识别").strip() or "待识别"
        background, color, border = palette.get(label, ("#F3F4F6", "#374151", "#D1D5DB"))
        return (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            f'background:{background};color:{color};border:1px solid {border};font-weight:600;">{label}</span>'
        )

    def _risk_badge(self, diagnosis: str | None) -> str:
        label = str(diagnosis or "待识别").strip() or "待识别"
        if "高库销高进销" in label or "高库存高风险" in label:
            background, color, border = "#FDECEA", "#C62828", "#F5C6CB"
        elif "高库销低进销" in label or "持续积压" in label:
            background, color, border = "#FFF4E5", "#B45309", "#FBD38D"
        elif "待复核" in label:
            background, color, border = "#FFF8E1", "#B26A00", "#FFE082"
        else:
            background, color, border = "#F3F4F6", "#374151", "#D1D5DB"
        return (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            f'background:{background};color:{color};border:1px solid {border};font-weight:600;">{label}</span>'
        )

    def _build_regional_status_chart(self, rows: list[dict[str, Any]], axis_max: float) -> str:
        if not rows:
            return ""
        palette = {
            "绿灯": "#2E7D32",
            "黄灯": "#F9A825",
            "红灯": "#C62828",
        }
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:12px;padding:12px 14px;margin:8px 0 12px 0;">',
            '<div style="font-size:12px;color:#4B5563;margin-bottom:8px;">补充灯色视图：每条色条长度代表期末库销比，颜色对应红/黄/绿灯。</div>',
        ]
        for row in rows:
            ratio = float(row.get("ratio") or 0)
            width = min(100.0, (ratio / axis_max) * 100) if axis_max > 0 else 0.0
            color = palette.get(row.get("status"), "#6B7280")
            lines.append(
                "<div style=\"display:flex;align-items:center;gap:10px;margin:7px 0;\">"
                f"<div style=\"width:64px;flex:0 0 64px;font-size:12px;color:#111827;\">{row.get('region', '待补充')}</div>"
                "<div style=\"flex:1;height:14px;background:#F3F4F6;border-radius:999px;overflow:hidden;\">"
                f"<div style=\"width:{width:.1f}%;height:100%;background:{color};border-radius:999px;\"></div>"
                "</div>"
                f"<div style=\"width:44px;flex:0 0 44px;text-align:right;font-size:12px;color:#111827;\">{ratio:.2f}</div>"
                f"<div style=\"width:72px;flex:0 0 72px;text-align:right;\">{row.get('status_badge') or self._status_badge(row.get('status'))}</div>"
                "</div>"
            )
        lines.append("</div>")
        return "\n".join(lines)

    def _build_purchase_integrated_table(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:12px;overflow:hidden;margin:8px 0 12px 0;">',
            '<div style="padding:10px 14px;background:#F9FAFB;font-size:12px;color:#4B5563;">历史订购评价整合明细：按“原销售大区 + 滔搏纸袋分类”联表后的高风险组合。</div>',
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">',
            '<thead style="background:#F3F4F6;color:#111827;">',
            '<tr>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">滔搏纸袋分类</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">原销售大区</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计纸袋销售量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末业务库存量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末库销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计厂入量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">进销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">同期后30天纸袋销量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">测算未来30天纸袋销量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">风险等级</th>'
            '</tr>',
            '</thead>',
            '<tbody>',
        ]
        for index, row in enumerate(rows):
            background = "#FFFFFF" if index % 2 == 0 else "#FAFAFA"
            lines.append(
                f'<tr style="background:{background};">'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;">{row.get("model", "待补充")}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;">{row.get("region", "待补充")}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">{self._fmt_int(row.get("sales_qty"))}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">{self._fmt_int(row.get("inventory_qty"))}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">{self._fmt_decimal(row.get("ratio"))}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">{self._fmt_int(row.get("inbound_qty"))}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">{self._fmt_decimal(row.get("inbound_ratio"))}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">{self._fmt_int(row.get("same_period_sales_qty"))}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">{self._fmt_int(row.get("future_usage"))}</td>'
                '</tr>'
            )
        lines.extend(['</tbody>', '</table>', '</div>'])
        return "\n".join(lines)

    def _build_purchase_risk_table(self, rows: list[dict[str, Any]]) -> str:
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header("", "按大区与型号展示 a597 与 u114 关联后的关键字段。", tag=""),
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">',
            '<thead style="background:#F3F4F6;color:#111827;">',
            '<tr>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">滔搏纸袋分类</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">原销售大区</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计纸袋销售量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末业务库存量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末库销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计厂入量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">进销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">同期后30天纸袋销量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">测算未来30天纸袋销量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">风险等级</th>'
            '</tr>',
            '</thead>',
            '<tbody>',
        ]
        if rows:
            for index, row in enumerate(rows):
                background = "#FFFFFF" if index % 2 == 0 else "#FAFAFA"
                lines.append(
                    f'<tr style="background:{background};">'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;">{row.get("model", "待补充")}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;">{row.get("region", "待补充")}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("sales_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("inventory_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("ratio"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("inbound_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("inbound_ratio"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("same_period_sales_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("future_usage"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;"><strong style="color:#111827;">{row.get("risk_level", "待补充")}</strong></td>'
                    '</tr>'
                )
        else:
            lines.append(
                '<tr style="background:#FFFFFF;">'
                '<td style="padding:12px 8px;border-bottom:1px solid #E5E7EB;text-align:center;color:#64748B;" colspan="10">'
                '本期联表后暂无满足规则的地区型号组合'
                '</td>'
                '</tr>'
            )
        lines.extend(["</tbody>", "</table>", "</div>"])
        return "\n".join(lines)

    def _build_purchase_joined_table(self, rows: list[dict[str, Any]]) -> str:
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header("历史订购拼接后数据明细", "先展示 a597 与 u114 按大区+型号拼接后的原始明细，再据此生成风险判断。", tag="拼接明细"),
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">',
            '<thead style="background:#F3F4F6;color:#111827;">',
            '<tr>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">滔搏纸袋分类</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">原销售大区</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计纸袋销售量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末业务库存量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末库销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末近30天累计厂入量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">进销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">同期后30天纸袋销量</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">测算未来30天纸袋销量</th>'
            '</tr>',
            '</thead>',
            '<tbody>',
        ]
        if rows:
            for index, row in enumerate(rows):
                background = "#FFFFFF" if index % 2 == 0 else "#FAFAFA"
                lines.append(
                    f'<tr style="background:{background};">'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;">{row.get("model", "待补充")}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;">{row.get("region", "待补充")}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("sales_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("inventory_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("ratio"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("inbound_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("inbound_ratio"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("same_period_sales_qty"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("future_usage"))}</strong></td>'
                    '</tr>'
                )
        else:
            lines.append(
                '<tr style="background:#FFFFFF;">'
                '<td style="padding:12px 8px;border-bottom:1px solid #E5E7EB;text-align:center;color:#64748B;" colspan="9">'
                '本期暂无可拼接的大区型号数据'
                '</td>'
                '</tr>'
            )
        lines.extend(["</tbody>", "</table>", "</div>"])
        return "\n".join(lines)

    def _build_purchase_risk_summary_table(self, rows: list[dict[str, Any]]) -> str:
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">',
            '<thead style="background:#F8FAFC;color:#111827;">',
            '<tr>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">大区 - 型号</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期末库销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">进销比</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">期初库销估算值</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">次月期末库销测算</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">风险等级</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">对应规则</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">处理原则</th>'
            '</tr>',
            '</thead>',
            '<tbody>',
        ]
        if rows:
            for row in rows:
                risk_level = str(row.get("risk_level") or "")
                if risk_level == "P1（高风险）":
                    row_bg, text_color, border_color, status_bg = ("rgba(254, 242, 242, 1)", "#7F1D1D", "#FECACA", "#FEE2E2")
                elif risk_level.startswith("P2"):
                    row_bg, text_color, border_color, status_bg = ("rgba(254, 249, 195, 1)", "#713F12", "#FDE68A", "#FEF3C7")
                else:
                    row_bg, text_color, border_color, status_bg = ("rgba(240, 253, 244, 1)", "#14532D", "#BBF7D0", "#DCFCE7")
                lines.append(
                    f'<tr style="background:{row_bg};color:{text_color};">'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};font-weight:600;">{row.get("region_model", "待补充")}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("ratio"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("inbound_ratio"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("ratio_gap"))}</strong></td>'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:center;">{row.get("future_ratio_display", "待补充")}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};text-align:center;">'
                    f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:{status_bg};border:1px solid {border_color};font-weight:700;color:{text_color};">{risk_level or "待补充"}</span>'
                    '</td>'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};">{row.get("rule_name", "待补充")}</td>'
                    f'<td style="padding:8px;border-bottom:1px solid {border_color};">{row.get("handling_principle", "待补充")}</td>'
                    '</tr>'
                )
        else:
            lines.append(
                '<tr style="background:#FFFFFF;">'
                '<td style="padding:12px 8px;border-bottom:1px solid #E5E7EB;text-align:center;color:#64748B;" colspan="8">'
                '本期联表后暂无满足规则的地区型号组合'
                '</td>'
                '</tr>'
            )
        lines.extend(["</tbody>", "</table>", "</div>"])
        return "\n".join(lines)

    def _format_multiline_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text.replace("；", "<br>")

    def _format_numbered_multiline_text(self, value: str) -> str:
        text = str(value or "").strip().rstrip("。")
        if not text:
            return ""
        parts = [part.strip().rstrip("。") for part in text.split("；") if part.strip()]
        if not parts:
            return ""
        return "<br>".join(f"{index}. {part}" for index, part in enumerate(parts, start=1))

    def _build_inventory_matrix(
        self,
        rows: list[dict[str, Any]],
        models: list[str],
        value_key: str,
        total_key: str,
        title: str,
        subtitle: str | None,
        color_rgb: tuple[int, int, int],
        value_formatter: Any,
        total_formatter: Any,
    ) -> str:
        if not rows or not models:
            return ""

        numeric_values: list[float] = []
        for row in rows:
            value_map = row.get(value_key, {})
            if not isinstance(value_map, dict):
                continue
            for model in models:
                value = value_map.get(model)
                if value is not None:
                    numeric_values.append(float(value))
        max_value = max(numeric_values) if numeric_values else 0.0

        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header(title, subtitle, tag="结构矩阵"),
            '<table style="width:100%;border-collapse:separate;border-spacing:0;font-size:12px;">',
            '<thead style="background:#F3F4F6;color:#111827;">',
            '<tr>',
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;position:sticky;left:0;background:#F3F4F6;">原销售大区</th>',
        ]
        for model in models:
            lines.append(f'<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">{model}</th>')
        lines.append('<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">总计</th>')
        lines.extend(['</tr>', '</thead>', '<tbody>'])

        red, green, blue = color_rgb
        for row_index, row in enumerate(rows):
            background = "#FFFFFF" if row_index % 2 == 0 else "#FCFCFD"
            value_map = row.get(value_key, {}) if isinstance(row.get(value_key), dict) else {}
            lines.append(f'<tr style="background:{background};">')
            lines.append(
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;font-weight:600;position:sticky;left:0;background:{background};">{row.get("region", "待补充")}</td>'
            )
            for model in models:
                value = value_map.get(model)
                alpha = 0.08 if value in (None, 0) or max_value <= 0 else min(0.9, 0.12 + (float(value) / max_value) * 0.68)
                text_color = "#111827" if alpha < 0.45 else "#FFFFFF"
                cell_background = f"rgba({red}, {green}, {blue}, {alpha:.2f})"
                bar_width = 0.0 if value in (None, 0) or max_value <= 0 else (float(value) / max_value) * 100
                lines.append(
                    '<td style="padding:6px;border-bottom:1px solid #E5E7EB;vertical-align:middle;">'
                    f'<div style="border-radius:10px;background:{cell_background};color:{text_color};padding:6px 8px;min-width:84px;">'
                    f'<div style="font-weight:600;text-align:right;">{value_formatter(value)}</div>'
                    f'<div style="margin-top:4px;height:4px;background:rgba(255,255,255,0.35);border-radius:999px;overflow:hidden;">'
                    f'<div style="width:{bar_width:.1f}%;height:100%;background:rgba(255,255,255,0.92);"></div>'
                    '</div>'
                    '</div>'
                    '</td>'
                )
            total_value = row.get(total_key)
            lines.append(
                '<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;background:#F9FAFB;font-weight:700;">'
                f'{total_formatter(total_value)}'
                '</td>'
            )
            lines.append('</tr>')

        lines.extend(['</tbody>', '</table>', '</div>'])
        return "\n".join(lines)

    def _build_stocktake_metric_matrix(
        self,
        rows: list[dict[str, Any]],
        row_key: str,
        title: str,
        subtitle: str | None,
        metrics: list[dict[str, Any]],
        color_rgb: tuple[int, int, int],
    ) -> str:
        if not rows or not metrics:
            return ""

        numeric_values: list[float] = []
        values_by_metric: list[list[float | None]] = []
        for metric in metrics:
            getter = metric["value_getter"]
            metric_values = [getter(row) for row in rows]
            values_by_metric.append(metric_values)
            numeric_values.extend(abs(float(value)) for value in metric_values if value is not None)
        max_value = max(numeric_values) if numeric_values else 0.0
        red, green, blue = color_rgb

        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header(title, subtitle, tag="矩阵视图"),
            '<table style="width:100%;border-collapse:separate;border-spacing:0;font-size:12px;">',
            '<thead style="background:#F3F4F6;color:#111827;">',
            '<tr>',
            f'<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;position:sticky;left:0;background:#F3F4F6;">{"月份" if row_key == "label" else "大区"}</th>',
        ]
        for metric in metrics:
            lines.append(f'<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:center;">{metric["label"]}</th>')
        lines.extend(['</tr>', '</thead>', '<tbody>'])

        for row_index, row in enumerate(rows):
            background = "#FFFFFF" if row_index % 2 == 0 else "#FCFCFD"
            lines.append(f'<tr style="background:{background};">')
            lines.append(
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;font-weight:600;position:sticky;left:0;background:{background};">{row.get(row_key, "待补充")}</td>'
            )
            for metric in metrics:
                value = metric["value_getter"](row)
                magnitude = abs(float(value)) if value is not None else 0.0
                alpha = 0.08 if value in (None, 0) or max_value <= 0 else min(0.9, 0.12 + (magnitude / max_value) * 0.68)
                text_color = "#111827" if alpha < 0.45 else "#FFFFFF"
                cell_background = f"rgba({red}, {green}, {blue}, {alpha:.2f})"
                bar_width = 0.0 if value in (None, 0) or max_value <= 0 else (magnitude / max_value) * 100
                lines.append(
                    '<td style="padding:6px;border-bottom:1px solid #E5E7EB;vertical-align:middle;">'
                    f'<div style="border-radius:10px;background:{cell_background};color:{text_color};padding:6px 8px;min-width:88px;">'
                    f'<div style="font-weight:600;text-align:right;">{metric["formatter"](value)}</div>'
                    f'<div style="margin-top:4px;height:4px;background:rgba(255,255,255,0.35);border-radius:999px;overflow:hidden;">'
                    f'<div style="width:{bar_width:.1f}%;height:100%;background:rgba(255,255,255,0.92);"></div>'
                    '</div>'
                    '</div>'
                    '</td>'
                )
            lines.append('</tr>')
        lines.extend(['</tbody>', '</table>', '</div>'])
        return "\n".join(lines)

    def _build_stocktake_difference_cards(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        lines = [
            '<div class="risk-card-panel" style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header("盘差率大于 5% 大区风险卡片", "用于快速锁定高损失地区，并直接查看账面、实盘与损失测算。", tag="风险卡片"),
            '<div class="risk-card-grid" style="padding:12px;">',
        ]
        max_loss = max(abs(row.get("loss_amount") or 0) for row in rows) if rows else 0.0
        for index, row in enumerate(rows):
            if index % 3 == 0:
                lines.append(
                    '<div class="risk-card-row" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:10px;">'
                )
            loss_amount = abs(float(row.get("loss_amount") or 0.0))
            diff_qty = row.get("loss_qty")
            intensity = 0.15 if max_loss <= 0 else min(0.85, 0.18 + (loss_amount / max_loss) * 0.6)
            lines.append(
                f'<div class="risk-card" style="border-radius:14px;padding:12px;border:1px solid rgba(220,38,38,0.18);background:rgba(220,38,38,{intensity:.2f});">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">'
                f'<div style="font-weight:700;color:#111827;">{row.get("region", "待补充")}</div>'
                f'<div style="font-size:12px;color:#111827;">{row.get("label", "待补充")}</div>'
                '</div>'
                f'<div style="font-size:12px;color:#111827;line-height:1.7;">'
                f'账面库存：<strong>{self._fmt_int(row.get("book_inventory"))}</strong><br>'
                f'实盘数量：<strong>{self._fmt_int(row.get("actual_inventory"))}</strong><br>'
                f'合计盘盈亏数量：<strong>{self._fmt_int(diff_qty)}</strong><br>'
                f'盘差率大于5%损失计算：<strong>{self._fmt_decimal(row.get("loss_amount"))}</strong>'
                '</div>'
                '</div>'
            )
            if index % 3 == 2 or index == len(rows) - 1:
                lines.append('</div>')
        lines.extend(['</div>', '</div>'])
        return "\n".join(lines)

    def _build_order_control_summary_cards(
        self,
        total_orders: int,
        total_regions: int,
        max_ratio: float | None,
    ) -> str:
        cards = [
            ("异常订单数", str(total_orders), "#FFF4E5", "#B45309", "#FBD38D"),
            ("异常地区数", str(total_regions), "#FEF3C7", "#B45309", "#FCD34D"),
            ("最高异常配比", f"{max_ratio:.2f}" if max_ratio is not None else "无", "#FDECEA", "#C62828", "#F5C6CB"),
        ]
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header("配比控制概况", "用于快速查看异常订单数、异常地区数与最高异常配比。", tag="关键看板"),
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;padding:12px;">',
        ]
        for title, value, background, color, border in cards:
            lines.append(
                f'<div style="border:1px solid {border};border-radius:14px;padding:12px;background:{background};">'
                f'<div style="font-size:12px;color:{color};margin-bottom:6px;">{title}</div>'
                f'<div style="font-size:24px;font-weight:700;color:#111827;">{value}</div>'
                '</div>'
            )
        lines.extend(['</div>', '</div>'])
        return "\n".join(lines)

    def _build_order_anomaly_cards(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header("重点异常订单卡片", "卡片直接展示异常订单的门店、订单号与异常配比。", tag="异常卡片"),
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;padding:12px;">'
        ]
        for row in rows:
            ratio = row.get("ratio")
            severity = 0.0 if ratio is None else min(1.0, max(0.0, (float(ratio) - 1.0) / 1.5))
            background = f"rgba(245, 158, 11, {0.14 + severity * 0.28:.2f})"
            border = f"rgba(217, 119, 6, {0.22 + severity * 0.35:.2f})"
            lines.append(
                f'<div style="border:1px solid {border};border-radius:14px;padding:12px;background:{background};">'
                f'<div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:8px;">'
                f'<div style="font-weight:700;color:#111827;">{row.get("store") or "待补充门店"}</div>'
                f'<div style="font-size:12px;color:#92400E;">配比 {self._fmt_decimal(ratio)}</div>'
                '</div>'
                f'<div style="font-size:12px;color:#111827;line-height:1.7;">'
                f'地区：<strong>{row.get("region") or "待补充"}</strong><br>'
                f'订单号：<strong>{row.get("order_id") or "待补充"}</strong>'
                '</div>'
                '</div>'
            )
        lines.extend(['</div>', '</div>'])
        return "\n".join(lines)

    def _build_order_anomaly_region_table(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        lines = [
            '<div style="border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;margin:8px 0 12px 0;background:#FFFFFF;box-shadow:0 1px 2px rgba(15,23,42,0.04);">',
            self._build_panel_header("重点异常地区明细", "按异常订单数排序，仅展示Top10地区。", tag="异常地区"),
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">',
            '<thead style="background:#F8FAFC;color:#111827;">',
            '<tr>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">异常地区名称</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:left;">异常店铺编码</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">异常订单数</th>'
            '<th style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;">最高异常配比</th>'
            '</tr>',
            '</thead>',
            '<tbody>',
        ]
        for index, row in enumerate(rows[:10]):
            background = "#FFFFFF" if index % 2 == 0 else "#FAFAFA"
            store_codes = row.get("store_codes")
            if isinstance(store_codes, list):
                store_code_text = "、".join(str(code) for code in store_codes if code) or "待补充"
            else:
                store_code_text = str(row.get("store_code") or "待补充")
            lines.append(
                f'<tr style="background:{background};">'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;font-weight:600;">{row.get("region", "待补充")}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;">{store_code_text}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_int(row.get("count"))}</strong></td>'
                f'<td style="padding:8px;border-bottom:1px solid #E5E7EB;text-align:right;"><strong style="color:#111827;">{self._fmt_decimal(row.get("max_ratio"))}</strong></td>'
                '</tr>'
            )
        lines.extend(['</tbody>', '</table>', '</div>'])
        return "\n".join(lines)

    def _build_state_card(self, title: str, message: str, tone: str = "neutral") -> str:
        palette = {
            "success": ("#ECFDF5", "#047857", "#A7F3D0", "状态提示"),
            "warning": ("#FFF7ED", "#B45309", "#FDBA74", "状态提示"),
            "neutral": ("#F9FAFB", "#374151", "#D1D5DB", "状态提示"),
        }
        background, color, border, tag = palette.get(tone, palette["neutral"])
        return (
            f'<div style="border:1px solid {border};border-radius:14px;overflow:hidden;background:#FFFFFF;margin:8px 0 12px 0;box-shadow:0 1px 2px rgba(15,23,42,0.04);">'
            f'{self._build_panel_header(title, None, tag=tag)}'
            f'<div style="padding:14px;background:{background};font-size:14px;color:#111827;font-weight:600;line-height:1.7;">'
            f'<span style="color:{color};">{message}</span>'
            '</div>'
            '</div>'
        )

    def _fmt_int(self, value: Any) -> str:
        if value is None:
            return "待补充"
        return f"{int(round(float(value)))}"

    def _fmt_decimal(self, value: Any, digits: int = 2) -> str:
        if value is None:
            return "待补充"
        return f"{float(value):.{digits}f}"

    def _write_followup_document(
        self,
        report_dir: Path,
        context: TaskContext,
        template_context: dict[str, Any],
        report_path: Path,
    ) -> None:
        ai_insights = template_context.get("ai_insights", {})
        followup_items = ai_insights.get("regional_actions", []) if isinstance(ai_insights, dict) else []
        followup_items = [
            item
            for item in followup_items
            if isinstance(item, dict) and item.get("priority") == "P1"
        ]
        followup_payload = {
            "report_month": context.report_month,
            "run_id": context.run_id,
            "generated_at": context.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "report_path": str(report_path),
            "items": followup_items,
        }
        previous_payload = self._load_previous_followup_payload(report_dir, context.report_month, context)
        comparisons = self._compare_followup_items(followup_items, previous_payload.get("items", []) if previous_payload else [])

        lines = [
            f"# {self._followup_display_title(context.report_month)}",
            "",
            f"**统计周期：{month_label(context.report_month)}**  ",
            f"**生成时间：{context.generated_at.strftime('%Y-%m-%d %H:%M:%S')}**  ",
            f"**关联月报：{report_path.name}**",
            "",
            "## 一、区域问题拆解与行动点清单",
            "",
            "**执行要求：**问题、解决方向、行动清单、复盘指标必须一一对应；只跟进本表问题，不新增无依据事项；行动描述保持简洁、有力、可执行。",
            "",
            "| 问题ID | 区域 | 优先级 | 重点型号 | 关键依据 | 行动清单（型号/动作/数量） | 下月复盘指标 | 下月改进得分（0-100） |",
            "|---|---|---|---|---|---|---|---|",
        ]
        if followup_items:
            for item in followup_items:
                baseline = item.get("baseline", {})
                issue_key = self._sanitize_issue_key(item.get("issue_key", "待补充"))
                focus_models = item.get("focus_models", [])
                if isinstance(focus_models, list):
                    focus_model_text = "、".join(str(model) for model in focus_models if model) or "非型号问题"
                else:
                    focus_model_text = str(focus_models) if focus_models else "非型号问题"
                root_cause = self._sanitize_text(self._format_numbered_multiline_text(item.get("root_cause", "待补充")))
                business_plan = self._sanitize_text(item.get("business_plan", "待补充"))
                metric = (
                    f"高库存组合={baseline.get('high_inventory_count', 0)}；"
                    f"需求缺口={baseline.get('future_gap_count', 0)}；"
                    f"异常订单={baseline.get('order_anomaly_count', 0)}；"
                    f"净盘差={baseline.get('stocktake_net_loss_qty') if baseline.get('stocktake_net_loss_qty') is not None else '无'}"
                )
                lines.append(
                    f"| {issue_key} | {item.get('region', '待补充')} | {item.get('priority', 'P3')} | "
                    f"{focus_model_text} | {root_cause} | {business_plan} | {metric} | 待下月回填 |"
                )
        else:
            lines.append("| 无 | 无 | 无 | 无 | 本月未识别新增P1问题 | 持续监控 | 无 | 待下月回填 |")

        lines.extend(
            [
                "",
                "## 二、与上月问题对比",
                "",
                "规则说明：",
                "- `90-100`：核心指标显著改善（下降 >=30%），动作执行闭环完整。",
                "- `75-89`：核心指标改善（下降 10%-30%），动作执行较完整。",
                "- `60-74`：核心指标基本持平（变化在 ±10%），需加强执行。",
                "- `<60`：指标恶化（上升 >10%）或未按计划推进整改。",
                "",
                "| 问题ID | 上月严重度 | 本月严重度 | 参考评分 | 结论 |",
                "|---|---:|---:|---:|---|",
            ]
        )
        if comparisons:
            for item in comparisons:
                lines.append(
                    f"| {item['issue_key']} | {item['previous_severity']} | {item['current_severity']} | {item['score']} | {item['comment']} |"
                )
        else:
            lines.append("| 无可比对项 | - | - | - | 等待形成连续两个月数据后自动评分 |")

        followup_markdown = self._center_table_headers("\n".join(lines).strip() + "\n")
        followup_base_name = self._followup_base_name(context.report_month)
        followup_path = report_dir / f"{followup_base_name}_{context.run_id}.md"
        followup_json_path = report_dir / f"{followup_base_name}_{context.run_id}.json"
        followup_path.write_text(followup_markdown, encoding="utf-8")
        followup_json_path.write_text(json.dumps(followup_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("Issue follow-up document generated at %s", followup_path)

    def _load_previous_followup_payload(
        self,
        report_dir: Path,
        report_month: str,
        context: TaskContext | None = None,
    ) -> dict[str, Any] | None:
        previous_month = self._previous_month(report_month)
        previous_dir = report_dir.parent / previous_month
        if not previous_dir.exists():
            return None
        patterns = [
            f"{self._followup_base_name(previous_month)}_*.json",
            f"*_issue_followup_{previous_month}_*.json",
            f"paper_bag_issue_followup_{previous_month}_*.json",
        ]
        candidates: list[Path] = []
        for pattern in patterns:
            candidates.extend(previous_dir.glob(pattern))
        candidates = sorted(set(candidates))
        if not candidates:
            return None
        latest = candidates[-1]
        try:
            return json.loads(latest.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _report_prefix(self, context: TaskContext | None = None) -> str:
        if context and context.project_slug.strip():
            return context.project_slug.strip()
        return "paper_bag_monthly_report"

    def _report_base_name(self, report_month: str) -> str:
        return f"{report_month.replace('-', '')}-月度纸袋分析报告"

    def _report_display_title(self, report_month: str) -> str:
        return self._report_base_name(report_month)

    def _followup_base_name(self, report_month: str) -> str:
        return f"{self._report_base_name(report_month)}-followup"

    def _followup_display_title(self, report_month: str) -> str:
        return f"{self._report_display_title(report_month)}-问题跟进"

    def _compare_followup_items(self, current_items: list[dict[str, Any]], previous_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        previous_map = {
            item.get("issue_key"): item
            for item in previous_items
            if isinstance(item, dict) and item.get("issue_key")
        }
        comparisons: list[dict[str, Any]] = []
        for item in current_items:
            issue_key = item.get("issue_key")
            if not issue_key or issue_key not in previous_map:
                continue
            previous = previous_map[issue_key]
            previous_severity = int(previous.get("severity_score") or 0)
            current_severity = int(item.get("severity_score") or 0)
            if current_severity <= max(1, int(previous_severity * 0.7)):
                score = 90
                comment = "改善显著"
            elif current_severity < previous_severity:
                score = 80
                comment = "改善明显"
            elif current_severity == previous_severity:
                score = 70
                comment = "基本持平"
            else:
                score = 55
                comment = "风险上升"
            comparisons.append(
                {
                    "issue_key": issue_key,
                    "previous_severity": previous_severity,
                    "current_severity": current_severity,
                    "score": score,
                    "comment": comment,
                }
            )
        return comparisons

    def _build_inventory_management_conclusion(
        self,
        inventory_overview: dict[str, Any],
        report_month_label: str,
        report_month_end: str,
    ) -> str:
        ratio = inventory_overview.get("ratio")
        yoy = inventory_overview.get("yoy")
        mom = inventory_overview.get("mom")
        yoy_base_ratio = inventory_overview.get("yoy_base_ratio")
        mom_base_ratio = inventory_overview.get("mom_base_ratio")
        if ratio is None:
            return inventory_overview.get("summary_sentence", "公司级库销结论待补充。")

        sentences = [f"截至 {report_month_label}期末日（{report_month_end}），公司纸袋库销比为 **{ratio:.2f}**。"]
        if ratio > 2:
            sentences.append("当前整体库存压力仍未回到目标水平。")
        else:
            sentences.append("当前已基本回到目标区间。")

        if yoy is not None and yoy_base_ratio is not None:
            yoy_direction = "下降" if yoy < 0 else "上升" if yoy > 0 else "持平"
            sentences.append(f"同比去年同月期末的 **{yoy_base_ratio:.2f}** {yoy_direction} **{abs(yoy) * 100:.2f}%**。")
        if mom is not None and mom_base_ratio is not None:
            if mom < 0:
                sentences.append(f"较上月期末的 **{mom_base_ratio:.2f}** 继续回落，库存周转较上月改善。")
            elif mom > 0:
                sentences.append(f"较上月期末的 **{mom_base_ratio:.2f}** 再度抬升，去库存压力较上月加重。")
            else:
                sentences.append(f"较上月期末的 **{mom_base_ratio:.2f}** 基本持平。")
        return "".join(sentences)

    def _build_purchase_management_conclusion(
        self,
        purchase_alerts: list[dict[str, Any]],
        high_inbound_alerts: list[dict[str, Any]],
        low_inbound_alerts: list[dict[str, Any]],
    ) -> str:
        if not purchase_alerts:
            return "本期未识别出需要重点关注的高库销订购组合。"

        sentences: list[str] = []
        if high_inbound_alerts:
            sentences.append(f"{len(high_inbound_alerts)}个地区型号属于高库销&高进销，订购节奏偏快。")
        if low_inbound_alerts:
            sentences.append(f"{len(low_inbound_alerts)}个地区型号属于高库销&低进销，历史积压尚未消化，仍有继续补货现象。")
        if not sentences:
            sentences.append(f"共识别{len(purchase_alerts)}个高库销订购关注组合，需继续跟踪消化和订购节奏。")

        focus_rows = high_inbound_alerts[:2] if high_inbound_alerts else low_inbound_alerts[:2]
        if focus_rows:
            focus_text = "、".join(f"{item.get('region')}-{item.get('model')}" for item in focus_rows)
            sentences.append(f"重点组合为：{focus_text}。")

        return "".join(sentences)

    def _build_regional_management_conclusion(
        self,
        regional_status: dict[str, Any],
        regional_rows: list[dict[str, Any]],
    ) -> str:
        red_count = int(regional_status.get("red_count") or 0)
        yellow_count = int(regional_status.get("yellow_count") or 0)
        green_count = int(regional_status.get("green_count") or 0)
        total_count = len(regional_rows)
        flagged_rows = [row for row in regional_rows if row.get("status") in {"红灯", "黄灯"}]
        if total_count == 0:
            return regional_status.get("summary_sentence", "地区目标达成结论待补充。")
        if not flagged_rows:
            return f"{total_count}个地区已全部进入绿灯，公司库存压力已不再由地区尾部问题主导。"

        focus_rows = flagged_rows[:2]
        focus_text = "、".join(
            f"{row.get('region')}（库销比{float(row.get('ratio') or 0):.2f}）"
            for row in focus_rows
            if row.get("region") and row.get("ratio") is not None
        )
        if red_count:
            return (
                f"当前地区端的核心问题集中在{focus_text}等超标区域；"
                f"{red_count}个红灯、{yellow_count}个黄灯地区仍在拉高公司整体库销，其余{green_count}个地区已基本回到目标区间。"
            )
        return (
            f"地区端暂未出现红灯失控问题，主要压力集中在{focus_text}等黄灯区域；"
            f"{yellow_count}个尾部地区尚未回到目标区间，其余{green_count}个地区已基本达标。"
        )

    def _build_model_management_conclusion(self, model_inventory_analysis: list[dict[str, Any]]) -> str:
        if not model_inventory_analysis:
            return "当前缺少足够的分型号结构数据，暂无法判断是否存在规格错配或使用浪费。"

        waste_rows = [row for row in model_inventory_analysis if row.get("waste_risk")]
        mismatch_rows = [
            row
            for row in model_inventory_analysis
            if row.get("structure_label") in {"库存偏小码积压", "库存偏大码积压", "使用偏大尺码"}
        ]
        if waste_rows:
            focus = waste_rows[0]
            return (
                f"当前更值得优先关注的是{focus.get('region')}存在偏大尺码使用风险，"
                f"使用端以{focus.get('usage_top_model')}为主（{((focus.get('usage_top_share') or 0) * 100):.1f}%），"
                "需要先复核是否存在尺码错配或大袋小用，再回看订购是否同步放大了该问题。"
            )
        if mismatch_rows:
            focus = mismatch_rows[0]
            if focus.get("structure_label") == "库存偏小码积压":
                return (
                    f"当前规格问题的本质不是浪费，而是{focus.get('region')}库存结构与真实需求错位："
                    f"库存端以{focus.get('top_model')}为主，但使用端主要消化{focus.get('usage_top_model')}，"
                    "应先纠正订购和库存结构。"
                )
            if focus.get("structure_label") == "库存偏大码积压":
                return (
                    f"当前规格问题主要表现为{focus.get('region')}{focus.get('top_model')}库存积压，"
                    f"库存占比{((focus.get('top_share') or 0) * 100):.1f}%明显高于使用端对应消化水平，"
                    "说明订购结构偏大。"
                )
        return "当前未识别出需要单独展开的结构错配区域，后续持续跟踪单一型号集中趋势即可。"

    def _build_consumption_management_conclusion(
        self,
        *,
        consumption_exceptions: dict[str, Any],
        report_month_label: str,
        previous_month_label: str,
        fiscal_year_label: str,
        consumption_trend_summary: str,
    ) -> str:
        overall_ratio = consumption_exceptions.get("overall_ratio")
        previous_ratio = consumption_exceptions.get("previous_ratio")
        order_count = len(consumption_exceptions.get("order_anomalies", []))
        region_count = len(consumption_exceptions.get("regional_anomaly_rows", []))
        if overall_ratio is None:
            return consumption_exceptions.get("summary_sentence", "纸袋配比结论待补充。")

        sentences = [f"{fiscal_year_label}至{report_month_label}，纸袋整体配比为 **{overall_ratio:.3f}**。"]
        if overall_ratio <= 1:
            sentences.append("整体仍处制度控制线内，当前风险更多来自局部执行偏差与异常订单。")
        else:
            sentences.append("整体配比已高于制度控制要求，需同步压降整体用袋水平。")

        if previous_ratio is not None:
            if overall_ratio > previous_ratio:
                sentences.append(f"较{previous_month_label}的 **{previous_ratio:.3f}** 小幅上升。")
            elif overall_ratio < previous_ratio:
                sentences.append(f"较{previous_month_label}的 **{previous_ratio:.3f}** 有所回落。")
            else:
                sentences.append(f"较{previous_month_label}的 **{previous_ratio:.3f}** 基本持平。")

        if order_count:
            sentences.append(f"本期共识别{order_count}条异常订单，涉及{region_count}个地区，说明末端配比纪律仍需重点盯防。")
        else:
            sentences.append("本期未出现订单配比超1的异常，末端执行整体稳定。")

        return "".join(sentences)

    def _build_order_control_management_conclusion(
        self,
        *,
        consumption_exceptions: dict[str, Any],
        top_order_anomalies: list[dict[str, Any]],
        top_regional_anomalies: list[dict[str, Any]],
        order_anomaly_empty_is_normal: bool,
        order_anomaly_empty_reason: str,
    ) -> str:
        order_count = len(consumption_exceptions.get("order_anomalies", []))
        if order_count == 0:
            base = order_anomaly_empty_reason or "本期未识别订单维度纸袋配比大于1的异常。"
            if "本期未出现订单配比超1的异常" in base or "配比控制总体稳定" in base:
                return base
            if "正常现象" in base:
                return f"{base} 订单端配比控制总体稳定。"
            return "本期未识别订单维度纸袋配比超1的异常，订单端配比控制总体稳定。"

        top_order = top_order_anomalies[0] if top_order_anomalies else {}
        top_region = top_regional_anomalies[0] if top_regional_anomalies else {}
        order_desc = (
            f"最高异常订单出现在{top_order.get('region') or '待补充'}"
            f"{top_order.get('store') or ''}，配比达到{float(top_order.get('ratio') or 0):.2f}。"
            if top_order.get("ratio") is not None
            else ""
        )
        region_desc = (
            f"异常订单最集中的地区为{top_region.get('region')}，共{int(top_region.get('count') or 0)}条。"
            if top_region
            else ""
        )
        return (
            f"本期订单配比异常的核心问题已落到具体门店和订单，累计识别{order_count}条异常记录。"
            f"{order_desc}{region_desc}建议优先追溯异常订单的发袋场景、参数管理及入账控制。"
        )

    def _build_stocktake_management_conclusion(self, stocktake_risks: dict[str, Any]) -> str:
        focus_regions = stocktake_risks.get("focus_regions", [])
        monthly_loss = stocktake_risks.get("monthly_loss")
        previous_month_loss = stocktake_risks.get("previous_month_loss")
        if not focus_regions:
            if monthly_loss is not None:
                sentences = [
                    f"当前盘点未出现需要追损的重点大区，月度盘点损失指标为 **{monthly_loss:.2f}**。"
                ]
                if previous_month_loss is not None:
                    if monthly_loss > previous_month_loss:
                        sentences.append("虽未形成单一区域性风险，但全国层面零散损耗较上月有所扩大。")
                    elif monthly_loss < previous_month_loss:
                        sentences.append("整体损耗较上月已有所收敛，但仍需持续压降零散盘亏。")
                    else:
                        sentences.append("整体损耗与上月基本持平，仍需继续跟踪零散盘亏来源。")
                else:
                    sentences.append("说明风险更偏向零散门店与个别账实差异，仍需持续做好门店复盘和账实核对。")
                return "".join(sentences)
            return stocktake_risks.get("summary_sentence", "盘点控制结论待补充。")

        focus_text = "、".join(
            f"{item.get('region')}（损失{abs(float(item.get('loss_amount') or item.get('net_loss_qty') or 0)):.0f}）"
            for item in focus_regions[:3]
            if item.get("region")
        )
        sentences = [f"当前盘点风险的主要矛盾集中在{focus_text}等地区，需优先处理高损失门店与账实差异。"]
        if monthly_loss is not None and previous_month_loss is not None:
            if monthly_loss > previous_month_loss:
                sentences.append("与上月相比，盘点损失仍在扩大。")
            elif monthly_loss < previous_month_loss:
                sentences.append("与上月相比，盘点损失已有所收敛。")
            else:
                sentences.append("与上月相比，盘点损失基本持平。")
        sentences.append("建议先核实账实差异来源，再同步落实赔付与流程纠偏。")
        return "".join(sentences)

    def _build_diagnosis_management_conclusion(self, diagnosis: dict[str, Any]) -> str:
        if not diagnosis:
            return "本期纸袋使用合规率与库存健康度诊断数据未接入，暂无结论。"
        red = diagnosis.get("red_count", 0)
        yellow = diagnosis.get("yellow_count", 0)
        green = diagnosis.get("green_count", 0)
        total = diagnosis.get("total_regions", 0)
        parts = [f"本月{total}个大区参与纸袋健康度诊断，"]
        if red:
            details = diagnosis.get("red_light_details", [])
            regions = "、".join(d.get("region", "") for d in details[:3])
            parts.append(f"{red}个大区得分低于70分需整改（{regions}等），")
            parts.append("普遍存在门店用袋尺码占比偏离理论配比、仓库各尺码备货比例不合理的问题。")
        if yellow:
            parts.append(f"{yellow}个大区得分70-84分需关注。")
        if green:
            parts.append(f"{green}个大区得分85分以上运行正常。")
        return "".join(parts)

    def _previous_month(self, report_month: str) -> str:
        dt = datetime.strptime(report_month, "%Y-%m")
        if dt.month == 1:
            return f"{dt.year - 1}-12"
        return f"{dt.year}-{dt.month - 1:02d}"

    def _sanitize_issue_key(self, issue_key: str) -> str:
        text = self._sanitize_text(issue_key or "待补充")
        return text.replace("::", "-").replace(":", "-")

    def _sanitize_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "待补充"
        text = text.replace("|", "｜")
        while "。；" in text:
            text = text.replace("。；", "；")
        while "；；" in text:
            text = text.replace("；；", "；")
        return text
