import json
import re
from datetime import datetime
from pathlib import Path

from src.models.schemas import SectionAnalysis, TaskContext
from src.services.report_service import ReportService


class DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None


def test_purchase_risk_rows_follow_opening_inventory_matrix(tmp_path: Path) -> None:
    service = ReportService(tmp_path / "report_template.md.j2", DummyLogger())

    rows = service._build_purchase_risk_rows(
        purchase_alerts=[
            {
                "region": "川藏新",
                "model": "滔搏纸袋-XL",
                "ratio": 4.8,
                "inbound_ratio": 1.0,
                "future_ratio": 4.2,
            },
            {
                "region": "粤海",
                "model": "滔搏纸袋-L",
                "ratio": 3.2,
                "inbound_ratio": 2.0,
                "future_ratio": 3.0,
            },
            {
                "region": "湘桂",
                "model": "滔搏纸袋-M",
                "ratio": 3.2,
                "inbound_ratio": 0.4,
                "future_ratio": 3.0,
            },
        ],
        inventory_green_max=2.5,
        inventory_yellow_max=3.5,
    )

    assert [row["region_model"] for row in rows] == ["川藏新-滔搏纸袋-XL", "粤海-滔搏纸袋-L", "湘桂-滔搏纸袋-M"]
    assert rows[0]["risk_level"] == "P1（高风险）"
    assert rows[0]["handling_principle"] == "期初库销已严重偏高，期末与预测仍在红黄区间，暂停新增订购并优先消化库存"
    assert rows[1]["risk_level"] == "P3（关注风险）"
    assert rows[2]["risk_level"] == "P2（中风险）"


def test_purchase_risk_rows_display_history_evaluation_levels(tmp_path: Path) -> None:
    service = ReportService(tmp_path / "report_template.md.j2", DummyLogger())

    rows = service._build_purchase_risk_rows(
        purchase_alerts=[
            {
                "region": "华中二区",
                "model": "滔搏纸袋-XS",
                "ratio": 2.84,
                "inbound_ratio": 2.28,
                "opening_ratio": 0.56,
                "future_ratio": 1.38,
                "purchase_risk_level": "P1",
                "diagnosis": "高库销高进销-月度多订",
            },
            {
                "region": "华南一区",
                "model": "滔搏纸袋-L",
                "ratio": 2.94,
                "inbound_ratio": 0.35,
                "opening_ratio": 2.59,
                "future_ratio": 1.35,
                "purchase_risk_level": "P2",
                "diagnosis": "高库销低进销-持续积压",
            },
        ],
        inventory_green_max=2.5,
        inventory_yellow_max=3.5,
    )

    assert [row["region_model"] for row in rows] == ["华中二区-滔搏纸袋-XS", "华南一区-滔搏纸袋-L"]
    assert rows[0]["risk_level"] == "P1（高风险）"
    assert rows[0]["rule_name"] == "P1：高库销&高进销，订购偏多风险"
    assert rows[0]["future_ratio_display"] == "1.38"
    assert rows[1]["risk_level"] == "P2（中风险）"
    assert rows[1]["rule_name"] == "P2：高库销&低进销，持续积压风险"
    assert rows[1]["future_ratio_display"] == "1.35"


def test_order_anomaly_region_table_limits_to_top_10_and_shows_store_codes(tmp_path: Path) -> None:
    service = ReportService(tmp_path / "report_template.md.j2", DummyLogger())
    rows = [
        {
            "region": f"地区{i:02d}",
            "store_code": f"S{i:03d}",
            "count": 20 - i,
            "max_ratio": 1.0 + i / 10,
        }
        for i in range(12)
    ]

    html = service._build_order_anomaly_region_table(rows)

    assert "重点异常地区明细" in html
    assert "异常地区名称" in html
    assert "异常店铺编码" in html
    assert "异常订单数" in html
    assert "最高异常配比" in html
    assert "地区00" in html
    assert "地区09" in html
    assert "地区10" not in html
    assert "S000" in html


def test_report_service_renders_markdown(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n\n{{ sections[0].summary }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="abcd1234",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    report = service.render(
        context=context,
        analyses=[SectionAnalysis(section_key="inventory", title="库存", summary="摘要")],
        highlights=["高亮"],
        report_facts={
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {
                            "ratio": 2.0,
                            "status": "绿灯",
                            "yoy": None,
                            "mom": None,
                            "source_name": "总览卡",
                            "trend_series": [],
                        },
                        "regional_status": {
                            "red_count": 0,
                            "yellow_count": 1,
                            "green_count": 1,
                            "regional_rows": [{"region": "华东", "ratio": 2.8, "status": "黄灯"}],
                        },
                        "purchase_analysis": {
                            "history_evaluations": [
                                {
                                    "region": "粤海",
                                    "model": "滔搏纸袋-L",
                                    "sales_qty": 9301,
                                    "inventory_qty": 38396,
                                    "ratio": 4.13,
                                    "inbound_qty": 20000,
                                    "inbound_ratio": 2.15,
                                    "same_period_sales_qty": 5000,
                                    "future_usage": 6000,
                                    "diagnosis": "高库销高进销-月度多订",
                                    "decision_comment": "当前库销比高于2且进销比大于2，新增入库仍快于消化节奏，本月订购量判断为偏多，订购恰当性不足。",
                                    "future_ratio": 5.4,
                                }
                            ],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_is_normal": True,
                            "order_anomaly_empty_reason": "本期无异常订单属于正常现象",
                        },
                        "stocktake_risks": {
                            "monthly_loss": None,
                            "monthly_rows": [],
                            "regional_rows": [],
                            "focus_regions": [],
                            "focus_stores": [],
                        },
                    }
                },
            }
        },
        data_quality={"warnings": [], "empty_cards": []},
        report_dir=tmp_path / "reports",
    )

    assert report.output_path.exists()
    assert "202603-月度纸袋分析报告" in report.markdown
    assert report.title == "202603-月度纸袋分析报告"
    assert "摘要" in report.markdown


def test_report_service_uses_fixed_monthly_output_name(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n\n{{ sections[0].summary }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="slug1234",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
        project_name="Renamed Project",
        project_slug="renamed_project",
    )
    report = service.render(
        context=context,
        analyses=[SectionAnalysis(section_key="inventory", title="库存", summary="摘要")],
        highlights=["高亮"],
        report_facts={
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {
                            "ratio": 2.0,
                            "status": "绿灯",
                            "yoy": None,
                            "mom": None,
                            "source_name": "总览卡",
                            "trend_series": [],
                        },
                        "regional_status": {
                            "red_count": 0,
                            "yellow_count": 1,
                            "green_count": 1,
                            "regional_rows": [{"region": "华东", "ratio": 2.8, "status": "黄灯"}],
                        },
                        "purchase_analysis": {
                            "history_evaluations": [],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_is_normal": True,
                            "order_anomaly_empty_reason": "本期无异常订单属于正常现象",
                        },
                        "stocktake_risks": {
                            "monthly_loss": None,
                            "monthly_rows": [],
                            "regional_rows": [],
                            "focus_regions": [],
                            "focus_stores": [],
                        },
                    }
                },
            }
        },
        data_quality={"warnings": [], "empty_cards": []},
        report_dir=tmp_path / "reports",
    )

    assert report.output_path.name == "202603-月度纸袋分析报告.md"
    assert (tmp_path / "reports" / "2026-03" / "202603-月度纸袋分析报告-followup_slug1234.md").exists()


def test_emphasize_text_bolds_labels_numbers_and_keywords(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    emphasized = service._emphasize_text("核心问题：仍有2个地区处于红灯；管理动作：优先处理P1风险。")

    assert "**核心问题：**" in emphasized
    assert "**2个地区**" in emphasized
    assert "**红灯**" in emphasized
    assert "**管理动作：**" in emphasized
    assert "**P1**" in emphasized


def test_emphasize_text_does_not_double_wrap_priority_labels(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    emphasized = service._emphasize_text("P1判定：健康度综合得分46.32分；触发问题6项。")

    assert "****" not in emphasized
    assert "**P1判定：**" in emphasized
    assert "**46.32分**" in emphasized
    assert "**6项**" in emphasized


def test_emphasize_text_keeps_signed_decimal_with_unit_intact(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    emphasized = service._emphasize_text("S码库存深度0.13月，库存偏差-36.6个百分点，需在后续订购中补齐。")

    assert "-36.<strong>" not in service._render_rich_text(emphasized)
    assert "**-36.6个百分点**" in emphasized
    assert "**0.13月**" in emphasized


def test_emphasize_text_keeps_month_and_percentage_point_units_intact(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    emphasized = service._emphasize_text("目标库存深度≥1个月；仅对超出 ±10个百分点宽容区间的部分计入错配度。")

    assert "≥**1个月**" in emphasized
    assert "**±10个百分点**" in emphasized


def test_normalize_ai_issue_type_label_deduplicates_repeated_problem_tags(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    normalized = service._normalize_ai_issue_type_label("大袋小用 + 库存结构不科学 / 库存结构不科学")

    assert normalized == "大袋小用 + 库存结构不科学"


def test_split_priority_action_groups_separates_inventory_usage_and_terminal(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    inventory_items, usage_items, terminal_items = service._split_priority_action_groups(
        [
            {
                "issue_type_label": "高库存去化",
                "action_details": [{"type": "overstock"}],
            },
            {
                "issue_type_label": "大袋小用 + 库存结构不科学",
                "action_details": [{"type": "diagnosis"}],
            },
            {
                "issue_type_label": "终端执行偏差",
                "action_details": [{"type": "order_anomaly"}],
            },
            {
                "issue_type_label": "盘点差异复核",
                "action_details": [{"type": "stocktake"}],
            },
        ],
        max_per_group=3,
    )

    assert [item["issue_type_label"] for item in inventory_items] == ["高库存去化"]
    assert [item["issue_type_label"] for item in usage_items] == ["大袋小用 + 库存结构不科学"]
    assert [item["issue_type_label"] for item in terminal_items] == ["终端执行偏差", "盘点差异复核"]


def test_build_priority_action_group_meta_contains_counts_and_display_hint(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    group = service._build_priority_action_group_meta(
        key="usage",
        label="纸袋使用合规类",
        tone="orange",
        description="聚焦大袋小用、尺码错配与纸袋使用合规动作。",
        preview_items=[
            {"priority": "P1", "issue_type_label": "大袋小用 + 库存结构不科学"},
            {"priority": "P1", "issue_type_label": "大袋小用 + 库存结构不科学"},
        ],
        all_items=[
            {"priority": "P1", "issue_type_label": "大袋小用 + 库存结构不科学"},
            {"priority": "P1", "issue_type_label": "大袋小用 + 库存结构不科学"},
            {"priority": "P2", "issue_type_label": "大袋小用 + 库存无法支持合理使用"},
        ],
        empty_message="本期暂无纸袋使用合规类重点动作。",
    )

    assert group["count_label"] == "3项重点动作"
    assert group["priority_mix"] == "P1 2项 / P2 1项"
    assert group["display_hint"] == "当前仅展示前2项，完整清单见第七部分。"
    assert group["issue_snapshot"] == "大袋小用、库存健康问题"


def test_build_priority_action_group_meta_uses_empty_count_label_when_no_items(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    group = service._build_priority_action_group_meta(
        key="terminal",
        label="终端异常 / 盘点类",
        tone="yellow",
        description="聚焦异常订单、门店执行偏差与盘点差异整改。",
        preview_items=[],
        all_items=[],
        empty_message="本期暂无终端异常 / 盘点类重点动作。",
    )

    assert group["count_label"] == "暂无重点动作"
    assert group["priority_mix"] == "本期无重点动作"


def test_diagnosis_management_conclusion_omits_green_sentence_when_no_green_regions(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    conclusion = service._build_diagnosis_management_conclusion(
        {
            "red_count": 4,
            "yellow_count": 5,
            "green_count": 0,
            "total_regions": 9,
            "red_light_details": [
                {"region": "华北二区"},
                {"region": "华中一区"},
                {"region": "华中二区"},
            ],
        }
    )

    assert "0个大区得分85分以上" not in conclusion
    assert "5个大区得分70-84分需关注。" in conclusion


def test_dedupe_delimited_text_removes_repeated_segments(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())

    normalized = service._dedupe_delimited_text("库存结构不科学；库存结构不科学；库存结构不科学")

    assert normalized == "库存结构不科学"


def test_project_report_template_uses_ai_monthly_regional_ratio_source_name() -> None:
    template_path = Path(__file__).resolve().parents[1] / "config" / "report_template.md.j2"
    template_text = template_path.read_text(encoding="utf-8")

    assert "## 一、核心结论（月度核心汇总）" in template_text
    assert "## 二、库销比总览（大区核心数据）" in template_text
    assert "## 三、历史订购评价（风险分级判定）" in template_text
    assert "## 四、库存结构与型号错配（重点关注）" in template_text
    assert "## 五、使用配比与盘点异常（合规管控）" in template_text
    assert "## 六、纸袋使用合规率与库存健康度诊断（AI驱动）" in template_text
    assert "小袋多用归因读取本地 SQL 导出 CSV" in template_text
    assert "usage_findings = detail.usage_diagnosis.findings" in template_text
    assert "额外成本合计" in template_text
    assert "## 七、AI 重点行动清单（可执行・分级）" in template_text
    assert "库存与趋势判断" in template_text
    assert "本月优先执行事项" in template_text
    assert "执行区域" in template_text
    assert "首要动作" in template_text
    assert "action_group_header(group)" in template_text
    assert "summary_card(group.label, group.count_label" in template_text
    assert "### P1 重点动作" in template_text
    assert "### P2 常规动作" in template_text
    assert "group.display_hint" in template_text
    assert "本月聚焦：" in template_text
    assert "下月复盘指标" in template_text
    assert "图表1-2：历史订购拼接后数据明细" not in template_text
    assert "## 一、纸袋库销诊断" not in template_text
    assert "## 二、销账异常" not in template_text
    assert "## 三、AI 洞察" not in template_text
    assert "来源口径" not in template_text
    assert "图表7-1：全国纸袋盘点月度矩阵" not in template_text
    assert "图表8-1：按大区纸袋盘点矩阵" not in template_text
    assert "图表1-8：按大区纸袋盘点分布" not in template_text
    assert "盘差率大于 5% 大区盘点分布" not in template_text
    assert "盘差率大于 5% 盘点财年数量统计" not in template_text
    assert "盘差率大于 5% 盘点财年金额统计" in template_text
    assert "P1/P2判定口径" in template_text
    assert "1. 结构相对均衡" not in template_text
    assert "1. 集中待跟踪" in template_text


def test_followup_document_uses_quantified_action_list_header(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n\n{{ sections[0].summary }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="efgh5678",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    service.render(
        context=context,
        analyses=[SectionAnalysis(section_key="inventory", title="库存", summary="摘要")],
        highlights=["高亮"],
        report_facts={
            "ai_insights": {
                "summary_sentence": "2026-03 AI洞察识别1个重点区域、2条可执行动作，其中P1优先级1个。",
                "regional_actions": [
                    {
                        "issue_key": "川藏新-型号库存动作",
                        "region": "川藏新",
                        "priority": "P1",
                        "severity_score": 6,
                        "focus_models": ["滔搏纸袋-XL", "滔搏纸袋-S"],
                        "root_cause": "滔搏纸袋-XL期末库存26000个，未来30天预计销量4000个，按次月期末库销比2.5测算超储12000个。",
                        "business_plan": "1. 滔搏纸袋-XL：库存积压，库销比4.20，立即停止订购。<br>2. 滔搏纸袋-S：库存短缺，库销比0.10，尽快补货5000个。",
                        "baseline": {
                            "high_inventory_count": 1,
                            "future_gap_count": 1,
                            "order_anomaly_count": 0,
                            "stocktake_net_loss_qty": None,
                        },
                    }
                ],
            },
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {
                            "ratio": 2.0,
                            "status": "绿灯",
                            "yoy": None,
                            "mom": None,
                            "source_name": "总览卡",
                            "trend_series": [],
                        },
                        "regional_status": {
                            "red_count": 0,
                            "yellow_count": 1,
                            "green_count": 1,
                            "regional_rows": [{"region": "华东", "ratio": 2.8, "status": "黄灯"}],
                        },
                        "purchase_analysis": {
                            "history_evaluations": [
                                {
                                    "region": "粤海",
                                    "model": "滔搏纸袋-L",
                                    "sales_qty": 9301,
                                    "inventory_qty": 38396,
                                    "ratio": 4.13,
                                    "inbound_qty": 20000,
                                    "inbound_ratio": 2.15,
                                    "same_period_sales_qty": 5000,
                                    "future_usage": 6000,
                                    "diagnosis": "高库销高进销-月度多订",
                                    "decision_comment": "当前库销比高于2且进销比大于2，新增入库仍快于消化节奏，本月订购量判断为偏多，订购恰当性不足。",
                                    "future_ratio": 5.4,
                                }
                            ],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_is_normal": True,
                            "order_anomaly_empty_reason": "本期无异常订单属于正常现象",
                        },
                        "stocktake_risks": {
                            "monthly_loss": None,
                            "monthly_rows": [],
                            "regional_rows": [],
                            "focus_regions": [],
                            "focus_stores": [],
                        },
                    }
                },
            },
        },
        data_quality={"warnings": [], "empty_cards": []},
        report_dir=tmp_path / "reports",
    )

    followup_path = tmp_path / "reports" / "2026-03" / "202603-月度纸袋分析报告-followup_efgh5678.md"
    followup_markdown = followup_path.read_text(encoding="utf-8")

    assert "# 202603-月度纸袋分析报告-问题跟进" in followup_markdown
    assert "行动清单（型号/动作/数量）" in followup_markdown
    assert "问题、解决方向、行动清单、复盘指标必须一一对应" in followup_markdown
    assert "只跟进本表问题，不新增无依据事项" in followup_markdown
    assert "1. 滔搏纸袋-XL：库存积压，库销比4.20，立即停止订购。" in followup_markdown
    assert "2. 滔搏纸袋-S：库存短缺，库销比0.10，尽快补货5000个。" in followup_markdown


def test_load_previous_followup_payload_supports_legacy_issue_followup_names(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")
    service = ReportService(template_path, DummyLogger())
    previous_dir = tmp_path / "reports" / "2026-02"
    previous_dir.mkdir(parents=True)
    legacy_payload = {"items": [{"issue_key": "legacy-1", "severity_score": 5}]}
    legacy_path = previous_dir / "renamed_project_issue_followup_2026-02_oldrun.json"
    legacy_path.write_text(json.dumps(legacy_payload, ensure_ascii=False), encoding="utf-8")

    payload = service._load_previous_followup_payload(
        report_dir=tmp_path / "reports" / "2026-03",
        report_month="2026-03",
    )

    assert payload == legacy_payload


def test_template_context_builds_combo_charts(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="ijkl9012",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    template_context = service._build_template_context(
        context=context,
        report_facts={
            "ai_insights": {
                "summary_sentence": "2026-03 AI洞察保留1个重点区域，其中P1优先级1个、P2优先级0个。",
                "regional_actions": [
                    {
                        "region": "粤海",
                        "priority": "P1",
                        "focus_models": ["滔搏纸袋-L"],
                        "root_cause": "滔搏纸袋-L期末库存38396个；未来30天预计销量6000个；地区整体库销比处于黄灯区间。",
                        "business_plan": "1. 滔搏纸袋-L：库存积压，库销比5.40，立即停止订购。",
                    }
                ],
            },
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {
                            "ratio": 2.8,
                            "status": "黄灯",
                            "yoy": None,
                            "mom": None,
                            "source_name": "总览卡",
                            "plateau_summary_sentence": "本月公司纸袋库销比在2026-03-01至2026-03-31间运行于1.50-2.80区间，最新值为2.80，较2026-03-01上升1.30；其中2026-03-01至2026-03-31连续2个监控时点在2.60-2.80区间窄幅波动，月末已进入高位横盘，说明前期去库存改善在放缓，尚未形成继续向目标值2回落的趋势。",
                            "blocking_reasons": ["地区侧仍有1个黄灯地区尚未回到目标区间，当前主要压力集中在华东（库销比2.80）。"],
                            "trend_series": [
                                {"label": "2026-03-01", "ratio": 1.5, "compare_ratio": 4.6, "inventory_qty": 1500000},
                                {"label": "2026-03-31", "ratio": 2.8, "compare_ratio": 5.6, "inventory_qty": 2800000},
                            ],
                        },
                        "regional_status": {
                            "red_count": 0,
                            "yellow_count": 1,
                            "green_count": 1,
                            "regional_rows": [{"region": "华东", "ratio": 2.8, "status": "黄灯", "sales_qty": 1000, "inventory_qty": 2800, "inbound_qty": 300, "inbound_ratio": 0.3}],
                        },
                        "purchase_analysis": {
                            "history_evaluations": [
                                {
                                    "region": "粤海",
                                    "model": "滔搏纸袋-L",
                                    "sales_qty": 9301,
                                    "inventory_qty": 38396,
                                    "ratio": 4.13,
                                    "inbound_qty": 20000,
                                    "inbound_ratio": 2.15,
                                    "same_period_sales_qty": 5000,
                                    "future_usage": 6000,
                                    "diagnosis": "高库销高进销-月度多订",
                                    "decision_comment": "当前库销比高于2且进销比大于2，新增入库仍快于消化节奏，本月订购量判断为偏多，订购恰当性不足。",
                                    "future_ratio": 5.4,
                                }
                            ],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "high_inventory_high_inbound_count": 1,
                            "high_inventory_low_inbound_count": 0,
                            "model_inventory_models": ["滔搏纸袋-S", "滔搏纸袋-M"],
                            "model_inventory_share_rows": [
                                {"region": "粤海", "model_shares": {"滔搏纸袋-S": 0.4, "滔搏纸袋-M": 0.6}, "total_inventory_qty": 45000},
                            ],
                            "model_usage_share_rows": [
                                {"region": "粤海", "model_shares": {"滔搏纸袋-S": 0.75, "滔搏纸袋-M": 0.25}, "total_sales_qty": 12000},
                            ],
                            "model_inventory_analysis": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [
                                {"label": "2025-03", "value": 0.72},
                                {"label": "2026-03", "value": 0.68},
                            ],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_is_normal": True,
                            "order_anomaly_empty_reason": "本期无异常订单属于正常现象",
                        },
                        "stocktake_risks": {
                            "monthly_loss": 100,
                            "monthly_rows": [
                                {"label": "2025-03", "loss_qty": -50, "gain_qty": 20, "net_loss_qty": 30, "total_qty": -30, "loss_amount": None},
                                {"label": "2026-03", "loss_qty": -100, "gain_qty": 40, "net_loss_qty": 60, "total_qty": -60, "loss_amount": None},
                            ],
                            "regional_rows": [
                                {"region": "粤海", "loss_qty": -120, "gain_qty": 40, "net_loss_qty": 80, "total_qty": -80, "loss_amount": None},
                            ],
                            "difference_rows": [
                                {"label": "2026-03", "region": "川藏新", "book_inventory": 3507, "actual_inventory": 569, "loss_qty": -2938, "loss_amount": -4111.03},
                            ],
                            "difference_chart_rows": [
                                {"label": "2026-03", "region": "川藏新", "loss_qty": -2938, "gain_qty": 0, "net_loss_qty": 2938, "total_qty": -2938, "loss_amount": -4111.03},
                            ],
                            "difference_fiscal_rows": [
                                {
                                    "label": "FY25",
                                    "loss_qty": -491173,
                                    "gain_qty": 408990,
                                    "total_qty": -82183,
                                    "loss_amount": -513949.12,
                                    "gain_amount": 475231.44,
                                    "total_amount": -38717.68,
                                },
                                {
                                    "label": "FY26",
                                    "loss_qty": -28527,
                                    "gain_qty": 19257,
                                    "total_qty": -9270,
                                    "loss_amount": -31706.03,
                                    "gain_amount": 22824.69,
                                    "total_amount": -8881.34,
                                },
                            ],
                            "focus_regions": [],
                            "focus_stores": [],
                        },
                    }
                },
            }
        },
        data_quality={"warnings": [], "empty_cards": []},
    )

    inventory_chart = template_context["charts"]["inventory_trend_labeled"]
    monthly_stocktake_chart = template_context["charts"]["stocktake_monthly_bar"]
    regional_stocktake_chart = template_context["charts"]["stocktake_region_bar"]
    difference_stocktake_chart = template_context["charts"]["stocktake_difference_bar"]
    difference_fiscal_amount_chart = template_context["charts"]["stocktake_difference_fiscal_amount_bar"]
    consumption_ratio_bar = template_context["charts"]["consumption_ratio_bar"]
    regional_light_chart = template_context["charts"]["regional_ratio_light_chart"]
    regional_status_table_html = template_context["regional_status_table_html"]
    model_inventory_share_matrix = template_context["charts"]["model_inventory_share_matrix"]
    model_usage_share_matrix = template_context["charts"]["model_usage_share_matrix"]
    purchase_risk_summary_table_html = template_context["purchase_risk_summary_table_html"]
    stocktake_monthly_matrix = template_context["charts"]["stocktake_monthly_matrix"]
    stocktake_region_matrix = template_context["charts"]["stocktake_region_matrix"]
    stocktake_difference_cards = template_context["charts"]["stocktake_difference_cards"]
    order_control_summary_cards = template_context["charts"]["order_control_summary_cards"]
    order_anomaly_cards = template_context["charts"]["order_anomaly_cards"]
    order_anomaly_status_card = template_context["charts"]["order_anomaly_status_card"]
    ai_display_actions = template_context["ai_display_actions"]

    assert "<svg" in inventory_chart
    assert "2026-03-01" not in inventory_chart
    assert "03-01" in inventory_chart
    assert "去年同期库销比" in inventory_chart
    assert re.search(r">[0-9.]+百万<", inventory_chart)
    assert "<svg" in monthly_stocktake_chart
    assert "盘差数量" in monthly_stocktake_chart
    assert "盘盈数量" in monthly_stocktake_chart
    assert ">-100<" in monthly_stocktake_chart
    assert ">40<" in monthly_stocktake_chart
    assert ">-60<" in monthly_stocktake_chart
    monthly_rect_xs = re.findall(r'<rect x="([0-9.]+)" y="[^"]+" width="18\.0"', monthly_stocktake_chart)
    assert monthly_rect_xs[0] == monthly_rect_xs[1]
    assert 'text-anchor="middle"' in monthly_stocktake_chart
    assert "<svg" in regional_stocktake_chart
    assert "盘差数量" in regional_stocktake_chart
    assert "盘盈数量" in regional_stocktake_chart
    assert ">-120<" in regional_stocktake_chart
    assert ">-80<" in regional_stocktake_chart
    regional_rect_xs = re.findall(r'<rect x="([0-9.]+)" y="[^"]+" width="18\.0"', regional_stocktake_chart)
    assert regional_rect_xs[0] == regional_rect_xs[1]
    assert 'text-anchor="middle"' in regional_stocktake_chart
    assert "<svg" in difference_stocktake_chart
    assert "盘差率大于5%大区盘点分布" in difference_stocktake_chart
    assert "川藏新" in difference_stocktake_chart
    assert "-0.29万" in difference_stocktake_chart
    assert "<svg" in difference_fiscal_amount_chart
    assert "盘点财年金额统计" in difference_fiscal_amount_chart
    assert "金额（百万）" in difference_fiscal_amount_chart
    assert "财年纸袋配比趋势" in consumption_ratio_bar
    assert 'class="chart-panel"' in consumption_ratio_bar
    assert regional_light_chart == ""
    assert 'rgba(254, 249, 195' in regional_status_table_html
    assert '<strong style="color:#111827;">2800</strong>' in regional_status_table_html
    assert "<table" in model_inventory_share_matrix
    assert "各大区纸袋型号库存占比矩阵" in model_inventory_share_matrix
    assert "<table" in model_usage_share_matrix
    assert "各大区纸袋使用量占比矩阵" in model_usage_share_matrix
    assert "<table" in purchase_risk_summary_table_html
    assert "高风险清单" not in purchase_risk_summary_table_html
    assert "期末库销比" in purchase_risk_summary_table_html
    assert "风险等级" in purchase_risk_summary_table_html
    assert "盘差率大于 5% 大区风险卡片" in stocktake_difference_cards
    assert 'class="risk-card-panel"' in stocktake_difference_cards
    assert 'class="risk-card-grid"' in stocktake_difference_cards
    assert 'class="risk-card-row"' in stocktake_difference_cards
    assert 'class="risk-card"' in stocktake_difference_cards
    assert "异常订单数" in order_control_summary_cards
    assert "最高异常配比" in order_control_summary_cards
    assert order_anomaly_cards == ""
    assert "本期无异常订单属于正常现象" in order_anomaly_status_card
    assert "2026-03当前值为0.680" in template_context["consumption_trend_summary"]
    assert "1. " in ai_display_actions[0]["root_cause_multiline"]
    assert "<br>" in ai_display_actions[0]["root_cause_multiline"]
    assert "P1判定" in ai_display_actions[0]["priority_reason"]
    assert "严重度评分" in ai_display_actions[0]["priority_rule"]
    assert "高库销&高进销" in template_context["purchase_management_conclusion"]
    assert "地区端暂未出现红灯失控问题" in template_context["regional_management_conclusion"]
    assert "当前缺少足够的分型号结构数据" in template_context["model_management_conclusion"]
    assert "整体仍处制度控制线内" in template_context["consumption_management_conclusion"]
    assert "订单端配比控制总体稳定" in template_context["order_control_management_conclusion"]
    assert "当前盘点未出现需要追损的重点大区" in template_context["stocktake_management_conclusion"]
    assert "订单" not in template_context["core_summary"]["problem_text"]


def test_core_summary_aggregates_global_issues_and_actions(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="core5678",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    template_context = service._build_template_context(
        context=context,
        report_facts={
            "ai_insights": {
                "summary_sentence": "2026-03 AI洞察保留2个重点区域，其中P1优先级1个、P2优先级1个。",
                "regional_actions": [
                    {
                        "region": "川藏新",
                        "priority": "P1",
                        "focus_models": ["滔搏纸袋-XL"],
                        "root_cause": "滔搏纸袋-XL期末库存26000个；未来30天预计销量4000个；盘点损失金额4111元。",
                        "business_plan": "1. 滔搏纸袋-XL：暂停新增订购。<br>2. 盘点差异：复核净盘差2938个。",
                    }
                ],
            },
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {
                            "ratio": 3.2,
                            "status": "黄灯",
                            "yoy": -0.2,
                            "mom": 0.1,
                            "yoy_base_ratio": 4.0,
                            "mom_base_ratio": 2.9,
                            "source_name": "总览卡",
                            "trend_series": [],
                        },
                        "regional_status": {
                            "red_count": 1,
                            "yellow_count": 1,
                            "green_count": 0,
                            "regional_rows": [
                                {"region": "川藏新", "ratio": 3.8, "status": "红灯", "sales_qty": 1000, "inventory_qty": 3800, "inbound_qty": 2000, "inbound_ratio": 2.1},
                                {"region": "湘桂", "ratio": 3.0, "status": "黄灯", "sales_qty": 1000, "inventory_qty": 3000, "inbound_qty": 300, "inbound_ratio": 0.3},
                            ],
                        },
                        "purchase_analysis": {
                            "history_evaluations": [
                                {
                                    "region": "川藏新",
                                    "model": "滔搏纸袋-XL",
                                    "sales_qty": 9301,
                                    "inventory_qty": 38396,
                                    "ratio": 4.13,
                                    "inbound_qty": 20000,
                                    "inbound_ratio": 2.15,
                                    "same_period_sales_qty": 5000,
                                    "future_usage": 6000,
                                    "diagnosis": "高库销高进销-月度多订",
                                    "decision_comment": "当前库销比高于2且进销比大于2，新增入库仍快于消化节奏。",
                                    "future_ratio": 5.4,
                                }
                            ],
                            "future_demand_gaps": [
                                {"region": "川藏新", "model": "滔搏纸袋-S", "suggested_order_qty": 5000, "shortage_qty": 3000, "future_ratio": 0.1, "level": "紧急"},
                            ],
                            "model_focus": [],
                            "high_inventory_high_inbound_count": 1,
                            "high_inventory_low_inbound_count": 0,
                            "model_inventory_models": [],
                            "model_inventory_share_rows": [],
                            "model_usage_share_rows": [],
                            "model_inventory_analysis": [
                                {
                                    "region": "川藏新",
                                    "top_model": "滔搏纸袋-XL",
                                    "top_share": 0.6,
                                    "usage_top_model": "滔搏纸袋-S",
                                    "usage_top_share": 0.5,
                                    "structure_label": "库存偏大码积压",
                                    "suggestion": "优先消化大码库存",
                                }
                            ],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [{"ratio": 1.3}],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [{"region": "川藏新", "count": 2, "max_ratio": 1.4}],
                            "order_anomaly_empty_is_normal": False,
                            "order_anomaly_empty_reason": "",
                        },
                        "stocktake_risks": {
                            "monthly_loss": 100,
                            "previous_month_loss": 80,
                            "monthly_rows": [],
                            "regional_rows": [],
                            "difference_rows": [],
                            "focus_regions": [{"region": "川藏新", "net_loss_qty": 2938, "loss_amount": -4111}],
                            "focus_stores": [],
                        },
                    }
                },
            },
        },
        data_quality={"warnings": [], "empty_cards": []},
    )

    assert "订单异常" in template_context["core_summary"]["problem_text"]
    assert "盘点损失" in template_context["core_summary"]["problem_text"]
    assert "异常订单复盘纠偏" in template_context["core_summary"]["action_text"]
    assert "高风险型号停订去化" in template_context["core_summary"]["action_text"]


def test_model_inventory_problem_analysis_filters_balanced_rows(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="model3456",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    template_context = service._build_template_context(
        context=context,
        report_facts={
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {"ratio": 2.0, "status": "绿灯", "yoy": None, "mom": None, "source_name": "总览卡", "trend_series": []},
                        "regional_status": {"red_count": 0, "yellow_count": 0, "green_count": 1, "regional_rows": []},
                        "purchase_analysis": {
                            "report_rows": [],
                            "history_evaluations": [],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "high_inventory_high_inbound_count": 0,
                            "high_inventory_low_inbound_count": 0,
                            "model_inventory_models": [],
                            "model_inventory_share_rows": [],
                            "model_usage_share_rows": [],
                            "model_inventory_analysis": [
                                {
                                    "region": "湘桂",
                                    "top_model": "滔搏纸袋-M",
                                    "top_share": 0.42,
                                    "usage_top_model": "滔搏纸袋-M",
                                    "usage_top_share": 0.40,
                                    "structure_label": "结构相对均衡",
                                    "suggestion": "保持现有结构",
                                },
                                {
                                    "region": "川藏新",
                                    "top_model": "滔搏纸袋-XL",
                                    "top_share": 0.60,
                                    "usage_top_model": "滔搏纸袋-S",
                                    "usage_top_share": 0.50,
                                    "structure_label": "库存偏大码积压",
                                    "suggestion": "优先消化大码库存",
                                },
                            ],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_is_normal": True,
                            "order_anomaly_empty_reason": "",
                        },
                        "stocktake_risks": {
                            "monthly_loss": 0,
                            "previous_month_loss": 0,
                            "monthly_rows": [],
                            "regional_rows": [],
                            "difference_rows": [],
                            "focus_regions": [],
                            "focus_stores": [],
                        },
                    }
                },
            },
            "ai_insights": {"summary_sentence": "", "regional_actions": []},
        },
        data_quality={"warnings": [], "empty_cards": []},
    )

    assert [row["region"] for row in template_context["model_inventory_problem_analysis"]] == ["川藏新"]


def test_signed_stocktake_chart_uses_compact_chinese_quantity_labels(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    chart = service._build_svg_signed_bar_line_chart(
        title="测试盘点图",
        labels=["粤海"],
        loss_values=[-262633],
        gain_values=[134648],
        line_values=[-127985],
        max_value=315160,
        y_axis_label="数量",
    )

    assert "26.3万" in chart
    assert "13.5万" in chart
    assert "-12.8万" in chart
    assert "31.5万" in chart


def test_signed_stocktake_chart_deduplicates_same_compact_labels(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    chart = service._build_svg_signed_bar_line_chart(
        title="测试盘点图",
        labels=["粤海"],
        loss_values=[-5598],
        gain_values=[None],
        line_values=[-5601],
        max_value=10000,
        y_axis_label="数量",
    )

    assert chart.count("-0.56万") == 1


def test_signed_stocktake_chart_uses_halo_labels_and_guides(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    chart = service._build_svg_signed_bar_line_chart(
        title="测试盘点图",
        labels=["2026-03", "2026-04"],
        loss_values=[-17539, -11433],
        gain_values=[11547, 9048],
        line_values=[-5992, -2385],
        max_value=20000,
        y_axis_label="数量",
    )

    assert "paint-order:stroke" in chart
    assert chart.count('stroke="#E5E7EB"') >= 2
    assert 'font-size="10"' in chart
    assert 'font-weight="800"' in chart
    assert 'stroke-width:2.5px' in chart


def test_signed_stocktake_chart_keeps_loss_label_when_values_do_not_overlap(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    chart = service._build_svg_signed_bar_line_chart(
        title="测试盘点图",
        labels=["2026-03"],
        loss_values=[-11000],
        gain_values=[12000],
        line_values=[1000],
        max_value=20000,
        y_axis_label="数量",
    )

    assert "1.2万" in chart
    assert "-1.1万" in chart
    circle_match = re.search(r'<circle cx="([0-9.]+)" cy="([0-9.]+)" r="4" fill="#0F172A"', chart)
    text_match = re.search(r'>0.1万</text>', chart)
    assert circle_match is not None
    assert text_match is not None
    text_prefix = chart[: text_match.start()]
    y_match = re.findall(r'y="([0-9.]+)" text-anchor="middle" fill="#0F172A"', text_prefix)
    assert y_match
    assert float(y_match[-1]) > float(circle_match.group(2))


def test_signed_stocktake_chart_hides_only_overlapping_label(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    chart = service._build_svg_signed_bar_line_chart(
        title="测试盘点图",
        labels=["2026-03"],
        loss_values=[-11000],
        gain_values=[12000],
        line_values=[-14000],
        max_value=20000,
        y_axis_label="数量",
    )

    assert "1.2万" in chart
    assert "-1.1万" in chart
    assert "-1.4万" not in chart


def test_signed_stocktake_chart_restores_loss_label_when_not_conflicting(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    chart = service._build_svg_signed_bar_line_chart(
        title="测试盘点图",
        labels=["2026-03"],
        loss_values=[-11000],
        gain_values=[12000],
        line_values=[-18000],
        max_value=20000,
        y_axis_label="数量",
    )

    assert "1.2万" in chart
    assert "-1.1万" in chart
    assert "-1.8万" in chart


def test_signed_stocktake_chart_keeps_total_label_close_to_marker(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    chart = service._build_svg_signed_bar_line_chart(
        title="测试盘点图",
        labels=["2026-03"],
        loss_values=[-17539],
        gain_values=[11547],
        line_values=[-5992],
        max_value=20000,
        y_axis_label="数量",
    )

    circle_match = re.search(r'<circle cx="([0-9.]+)" cy="([0-9.]+)" r="4" fill="#0F172A"', chart)
    text_match = re.search(r'y="([0-9.]+)" text-anchor="middle" fill="#0F172A" font-size="11" font-weight="800" .*?>-0.6万</text>', chart)
    assert circle_match is not None
    assert text_match is not None
    assert float(text_match.group(1)) - float(circle_match.group(2)) < 24


def test_purchase_risk_rows_follow_rule_matrix(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="risk9012",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    template_context = service._build_template_context(
        context=context,
        report_facts={
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {"ratio": 2.8, "status": "黄灯", "yoy": None, "mom": None, "source_name": "总览卡", "trend_series": []},
                        "regional_status": {"red_count": 0, "yellow_count": 0, "green_count": 0, "regional_rows": []},
                        "purchase_analysis": {
                            "report_rows": [
                                {"region": "京津晋", "model": "滔搏纸袋-XL", "ratio": 4.9, "inbound_ratio": 1.0, "future_ratio": 3.2, "sales_qty": 5000, "inventory_qty": 25000, "inbound_qty": 1000, "same_period_sales_qty": 1600, "future_usage": 1000},
                                {"region": "京津晋", "model": "滔搏纸袋-L", "ratio": 3.79, "inbound_ratio": 2.85, "future_ratio": 3.51, "sales_qty": 5333, "inventory_qty": 20214, "inbound_qty": 15200, "same_period_sales_qty": 6498, "future_usage": 4040},
                                {"region": "西北", "model": "滔搏纸袋-L", "ratio": 4.0, "inbound_ratio": 1.2, "future_ratio": 2.9, "sales_qty": 6000, "inventory_qty": 24000, "inbound_qty": 3000, "same_period_sales_qty": 7000, "future_usage": 4200},
                                {"region": "湘桂", "model": "滔搏纸袋-M", "ratio": 3.2, "inbound_ratio": 0.4, "future_ratio": 2.6, "sales_qty": 8000, "inventory_qty": 22000, "inbound_qty": 4000, "same_period_sales_qty": 9000, "future_usage": 5000},
                                {"region": "粤海", "model": "滔搏纸袋-S", "ratio": 3.2, "inbound_ratio": 2.0, "future_ratio": 2.6, "sales_qty": 10000, "inventory_qty": 18000, "inbound_qty": 8000, "same_period_sales_qty": 12000, "future_usage": 7000},
                            ],
                            "history_evaluations": [],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "high_inventory_high_inbound_count": 0,
                            "high_inventory_low_inbound_count": 0,
                            "model_inventory_models": [],
                            "model_inventory_share_rows": [],
                            "model_usage_share_rows": [],
                            "model_inventory_analysis": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_is_normal": True,
                            "order_anomaly_empty_reason": "",
                        },
                        "stocktake_risks": {"monthly_loss": None, "monthly_rows": [], "regional_rows": [], "focus_regions": [], "focus_stores": []},
                    }
                },
            }
        },
        data_quality={"warnings": [], "empty_cards": []},
    )

    rows = template_context["purchase_risk_rows"]
    purchase_risk_summary_table_html = template_context["purchase_risk_summary_table_html"]

    assert template_context["purchase_future_ratio_explainer"] == (
        "次月期末库销测算 = (筛选日期末库存 - 测算未来30天纸袋销量) / 测算未来30天纸袋销量"
    )
    assert [row["rule_name"] for row in rows] == [
        "规则1（P1：期初红，期末红，预测红/黄）",
        "规则4（P2：期初绿，期末红，预测红/黄）",
        "规则2（P1：期初黄，期末红，预测红/黄）",
        "规则3（P2：期初黄，期末黄，预测红/黄）",
        "规则5（P3：期初绿，期末黄，预测红/黄）",
    ]
    assert 'rgba(254, 242, 242, 1)' in purchase_risk_summary_table_html
    assert 'rgba(254, 249, 195, 1)' in purchase_risk_summary_table_html
    assert "京津晋-滔搏纸袋-XL" in purchase_risk_summary_table_html
    assert "京津晋-滔搏纸袋-L" in purchase_risk_summary_table_html
    assert "粤海-滔搏纸袋-S" in purchase_risk_summary_table_html
    assert "期初库销" in purchase_risk_summary_table_html


def test_purchase_management_conclusion_omits_zero_count_scenario(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="mnop3456",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    template_context = service._build_template_context(
        context=context,
        report_facts={
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {"ratio": 2.8, "status": "黄灯", "yoy": None, "mom": None, "source_name": "总览卡", "trend_series": []},
                        "regional_status": {"red_count": 0, "yellow_count": 1, "green_count": 1, "regional_rows": []},
                        "purchase_analysis": {
                            "history_evaluations": [
                                {
                                    "region": "京津晋",
                                    "model": "滔搏纸袋-L",
                                    "diagnosis": "高库销低进销-持续积压",
                                    "inbound_scenario": "高库销低进销",
                                }
                            ],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "model_inventory_models": [],
                            "model_inventory_share_rows": [],
                            "model_usage_share_rows": [],
                            "model_inventory_analysis": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                        },
                        "stocktake_risks": {
                            "monthly_loss": None,
                            "monthly_rows": [],
                            "regional_rows": [],
                            "focus_regions": [],
                            "focus_stores": [],
                        },
                    }
                },
            }
        },
        data_quality={"warnings": [], "empty_cards": []},
    )

    conclusion = template_context["purchase_management_conclusion"]
    assert "高库销&高进销" not in conclusion
    assert "高库销&低进销" in conclusion
    assert "历史积压尚未消化" in conclusion


def test_order_control_management_conclusion_avoids_duplicate_empty_state_wording(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="qrst6789",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    template_context = service._build_template_context(
        context=context,
        report_facts={
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {"ratio": 2.8, "status": "黄灯", "yoy": None, "mom": None, "source_name": "总览卡", "trend_series": []},
                        "regional_status": {"red_count": 0, "yellow_count": 0, "green_count": 1, "regional_rows": [{"region": "华东", "ratio": 1.8, "status": "绿灯"}]},
                        "purchase_analysis": {
                            "history_evaluations": [],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "model_inventory_models": [],
                            "model_inventory_share_rows": [],
                            "model_usage_share_rows": [],
                            "model_inventory_analysis": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_reason": "本期未识别订单维度纸袋配比大于1的异常。",
                        },
                        "stocktake_risks": {
                            "monthly_loss": None,
                            "monthly_rows": [],
                            "regional_rows": [],
                            "focus_regions": [],
                            "focus_stores": [],
                        },
                    }
                },
            }
        },
        data_quality={"warnings": [], "empty_cards": []},
    )

    assert template_context["order_control_management_conclusion"] == "本期未识别订单维度纸袋配比超1的异常，订单端配比控制总体稳定。"


def test_project_template_renders_purchase_summary_instead_of_detail_table(tmp_path: Path) -> None:
    template_path = Path(__file__).resolve().parents[1] / "config" / "report_template.md.j2"
    service = ReportService(template_path, DummyLogger())
    context = TaskContext(
        run_id="purchase5678",
        report_month="2026-03",
        generated_at=datetime(2026, 4, 1, 9, 0, 0),
        project_root=tmp_path,
    )
    template = service.env.get_template(template_path.name)
    template_context = service._build_template_context(
        context=context,
        report_facts={
            "sections": {
                "inventory_diagnosis": {
                    "facts": {
                        "inventory_overview": {"ratio": 2.0, "status": "绿灯", "yoy": None, "mom": None, "source_name": "总览卡", "trend_series": []},
                        "regional_status": {"red_count": 0, "yellow_count": 0, "green_count": 1, "regional_rows": []},
                        "purchase_analysis": {
                            "history_evaluations": [
                                {
                                    "region": "粤海",
                                    "model": "滔搏纸袋-L",
                                    "sales_qty": 9301,
                                    "inventory_qty": 38396,
                                    "ratio": 4.13,
                                    "inbound_qty": 20000,
                                    "inbound_ratio": 2.15,
                                    "same_period_sales_qty": 5000,
                                    "future_usage": 6000,
                                    "decision_comment": "当前库销比高于2且进销比大于2。",
                                    "future_ratio": 5.4,
                                },
                                {
                                    "region": "湘桂",
                                    "model": "滔搏纸袋-M",
                                    "sales_qty": 5000,
                                    "inventory_qty": 16000,
                                    "ratio": 3.2,
                                    "inbound_qty": 10000,
                                    "inbound_ratio": 2.0,
                                    "same_period_sales_qty": 4000,
                                    "future_usage": 4500,
                                    "future_ratio": 3.0,
                                },
                            ],
                            "future_demand_gaps": [],
                            "model_focus": [],
                            "high_inventory_high_inbound_count": 1,
                            "high_inventory_low_inbound_count": 0,
                            "model_inventory_models": [],
                            "model_inventory_share_rows": [],
                            "model_usage_share_rows": [],
                            "model_inventory_analysis": [],
                            "forecast_source": {"source_type": "missing", "label": "待补充"},
                        },
                    }
                },
                "consumption_exceptions": {
                    "facts": {
                        "consumption_exceptions": {
                            "overall_ratio": 0.8,
                            "ratio_history": [],
                            "order_anomalies": [],
                            "store_rollups": [],
                            "store_anomalies": [],
                            "regional_anomaly_rows": [],
                            "order_anomaly_empty_is_normal": True,
                            "order_anomaly_empty_reason": "",
                        },
                        "stocktake_risks": {"monthly_loss": 0, "previous_month_loss": 0, "monthly_rows": [], "regional_rows": [], "difference_rows": [], "focus_regions": [], "focus_stores": []},
                    }
                },
            },
            "ai_insights": {"summary_sentence": "", "regional_actions": []},
        },
        data_quality={"warnings": [], "empty_cards": []},
    )
    markdown = template.render(
        **template_context,
        highlights=["高亮"],
        sections=[SectionAnalysis(section_key="inventory", title="库存", summary="摘要")],
    )

    assert "**图表1-2：历史订购评价明细**" in markdown
    assert "风险等级" in markdown
    assert "对应规则" in markdown
    assert "同期后30天纸袋销量" not in markdown
    assert "滔搏纸袋分类" not in markdown
    assert "原销售大区" not in markdown
    assert "湘桂-滔搏纸袋-M" not in markdown
    assert "P3（关注风险）" not in markdown
    assert "高风险清单" not in markdown


def test_render_rich_text_converts_markdown_bold_and_code(tmp_path: Path) -> None:
    template_path = tmp_path / "report_template.md.j2"
    template_path.write_text("# {{ title }}\n", encoding="utf-8")

    service = ReportService(template_path, DummyLogger())

    rendered = service._render_rich_text("公司纸袋库销比为 **2.81**，重点型号为 `XL`。")

    assert "<strong>2.81</strong>" in rendered
    assert "<code>XL</code>" in rendered
    assert "**2.81**" not in rendered
