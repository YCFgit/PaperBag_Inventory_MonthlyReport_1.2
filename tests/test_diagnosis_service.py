from src.services.diagnosis_service import DiagnosisService
from src.models.schemas import NormalizedDataset


def test_usage_diagnosis_uses_ratios_not_absolute_quantities() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华中一区",
            "period": "2026-05",
            "xs_theory_qty": 300,
            "s_theory_qty": 300,
            "m_theory_qty": 200,
            "l_theory_qty": 100,
            "xl_theory_qty": 100,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华中一区",
            "period": "2026-05",
            "xs_actual_qty": 900,
            "s_actual_qty": 900,
            "m_actual_qty": 600,
            "l_actual_qty": 300,
            "xl_actual_qty": 300,
            "total_actual_qty": 3000,
        }],
        stock_rows=[{
            "region": "华中一区",
            "period": "2026-05",
            "xs_stock_qty": 0,
            "s_stock_qty": 0,
            "m_stock_qty": 0,
            "l_stock_qty": 0,
            "xl_stock_qty": 1000,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
    )

    detail = diagnosis["red_light_details"][0]
    assert detail["usage_problems"] == []
    assert "大袋替小袋" not in "\n".join(item["root_cause"] for item in diagnosis["action_items"])


def test_usage_problem_rows_expose_theory_and_actual_ratios() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 700,
            "s_theory_qty": 100,
            "m_theory_qty": 100,
            "l_theory_qty": 50,
            "xl_theory_qty": 50,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 0,
            "s_actual_qty": 0,
            "m_actual_qty": 1000,
            "l_actual_qty": 0,
            "xl_actual_qty": 0,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 700,
            "s_stock_qty": 100,
            "m_stock_qty": 100,
            "l_stock_qty": 50,
            "xl_stock_qty": 50,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
    )

    detail = diagnosis["red_light_details"][0]
    m_problem = next(problem for problem in detail["usage_problems"] if problem["size"] == "M")

    assert m_problem["theory_ratio_pct"] == "10.0%"
    assert m_problem["actual_ratio_pct"] == "100.0%"
    assert m_problem["usage_gap_text"] == "+90.0个百分点"
    assert m_problem["expected_actual_qty"] == 100.0
    assert m_problem["actual_qty"] == 1000
    assert m_problem["deviation_rate_pct"] == "+900.0%"
    assert m_problem["adjusted_deviation_rate_pct"] == "890.0%"
    assert "大袋小用风险" in m_problem["direction"]


def test_problem_light_details_include_yellow_regions() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 500,
            "s_theory_qty": 500,
            "m_theory_qty": 0,
            "l_theory_qty": 0,
            "xl_theory_qty": 0,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 500,
            "s_actual_qty": 500,
            "m_actual_qty": 0,
            "l_actual_qty": 0,
            "xl_actual_qty": 0,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 1000,
            "s_stock_qty": 0,
            "m_stock_qty": 0,
            "l_stock_qty": 0,
            "xl_stock_qty": 0,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
    )

    assert diagnosis["red_count"] == 0
    assert diagnosis["yellow_count"] == 1
    detail = diagnosis["problem_light_details"][0]
    assert detail["status"] == "🟡 黄灯"
    assert detail["stock_problems"][0]["diff_pct"] == "+50.0%"
    assert detail["stock_problems"][0]["adjusted_diff_pct"] == "40.0%"
    assert detail["stock_problems"][1]["diff_pct"] == "-50.0%"
    assert [action["priority"] for action in detail["recommended_actions"]] == sorted(
        [action["priority"] for action in detail["recommended_actions"]],
        key={"高": 0, "中": 1, "低": 2}.get,
    )


def test_summary_sentence_omits_green_sentence_when_no_green_regions() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[
            {
                "region": "华东一区",
                "period": "2026-05",
                "xs_theory_qty": 500,
                "s_theory_qty": 500,
                "m_theory_qty": 0,
                "l_theory_qty": 0,
                "xl_theory_qty": 0,
                "total_theory_qty": 1000,
            }
        ],
        actual_rows=[
            {
                "region": "华东一区",
                "period": "2026-05",
                "xs_actual_qty": 500,
                "s_actual_qty": 500,
                "m_actual_qty": 0,
                "l_actual_qty": 0,
                "xl_actual_qty": 0,
                "total_actual_qty": 1000,
            }
        ],
        stock_rows=[
            {
                "region": "华东一区",
                "period": "2026-05",
                "xs_stock_qty": 1000,
                "s_stock_qty": 0,
                "m_stock_qty": 0,
                "l_stock_qty": 0,
                "xl_stock_qty": 0,
                "total_stock_qty": 1000,
            }
        ],
        report_month="2026-05",
    )

    assert diagnosis["green_count"] == 0
    assert "0个大区得分85分以上" not in diagnosis["summary_sentence"]


def test_diagnosis_action_items_include_followup_tracking_fields() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 700,
            "s_theory_qty": 100,
            "m_theory_qty": 100,
            "l_theory_qty": 50,
            "xl_theory_qty": 50,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 100,
            "s_actual_qty": 50,
            "m_actual_qty": 800,
            "l_actual_qty": 25,
            "xl_actual_qty": 25,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 0,
            "s_stock_qty": 100,
            "m_stock_qty": 800,
            "l_stock_qty": 50,
            "xl_stock_qty": 50,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
    )

    action = diagnosis["action_items"][0]
    assert action["issue_key"] == "华东一区-健康度诊断"
    assert action["severity_score"] > 0
    assert action["baseline"]["diagnosis_composite_score"] == diagnosis["diagnosis_ranking"][0]["composite_score"]


def test_v11_usage_tolerance_does_not_penalize_small_structure_gap() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 500,
            "s_theory_qty": 500,
            "m_theory_qty": 0,
            "l_theory_qty": 0,
            "xl_theory_qty": 0,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 550,
            "s_actual_qty": 450,
            "m_actual_qty": 0,
            "l_actual_qty": 0,
            "xl_actual_qty": 0,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 500,
            "s_stock_qty": 500,
            "m_stock_qty": 0,
            "l_stock_qty": 0,
            "xl_stock_qty": 0,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
    )

    row = diagnosis["diagnosis_ranking"][0]
    assert row["usage_compliance_score"] == 100.0
    assert row["inventory_health_score"] == 100.0
    assert row["status"] == "🟢 绿灯"


def test_v11_inventory_tolerance_only_penalizes_excess_gap() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 500,
            "s_theory_qty": 500,
            "m_theory_qty": 0,
            "l_theory_qty": 0,
            "xl_theory_qty": 0,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 500,
            "s_actual_qty": 500,
            "m_actual_qty": 0,
            "l_actual_qty": 0,
            "xl_actual_qty": 0,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 600,
            "s_stock_qty": 400,
            "m_stock_qty": 0,
            "l_stock_qty": 0,
            "xl_stock_qty": 0,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
    )

    row = diagnosis["diagnosis_ranking"][0]
    assert row["inventory_health_score"] == 100.0


def test_stock_diagnosis_dedupes_understock_when_depth_below_one_month() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华北二区",
            "period": "2026-05",
            "xs_theory_qty": 0,
            "s_theory_qty": 400,
            "m_theory_qty": 600,
            "l_theory_qty": 0,
            "xl_theory_qty": 0,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华北二区",
            "period": "2026-05",
            "xs_actual_qty": 0,
            "s_actual_qty": 20,
            "m_actual_qty": 980,
            "l_actual_qty": 0,
            "xl_actual_qty": 0,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华北二区",
            "period": "2026-05",
            "xs_stock_qty": 0,
            "s_stock_qty": 50,
            "m_stock_qty": 950,
            "l_stock_qty": 0,
            "xl_stock_qty": 0,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
    )

    detail = diagnosis["problem_light_details"][0]
    stock_labels = [item["label"] for item in detail["stock_diagnosis"]["findings"] if item.get("size_label") == "S"]

    assert stock_labels == ["库存无法支持合理使用"]
    assert detail["usage_diagnosis"]["summary"].count("1. S码") == 1


def test_usage_diagnosis_can_classify_bundle_issue() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 100,
            "s_theory_qty": 150,
            "m_theory_qty": 200,
            "l_theory_qty": 250,
            "xl_theory_qty": 300,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 500,
            "s_actual_qty": 550,
            "m_actual_qty": 250,
            "l_actual_qty": 100,
            "xl_actual_qty": 100,
            "total_actual_qty": 1500,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 450,
            "s_stock_qty": 500,
            "m_stock_qty": 250,
            "l_stock_qty": 100,
            "xl_stock_qty": 100,
            "total_stock_qty": 1400,
        }],
        report_month="2026-05",
    )

    detail = diagnosis["problem_light_details"][0]

    assert detail["usage_diagnosis"]["label"] == "合包问题"
    assert "合包执行不足" in detail["usage_diagnosis"]["summary"]


def test_load_small_bag_input_rows_normalizes_counts_and_ratios(tmp_path) -> None:
    service = DiagnosisService()
    service.INPUT_DATA_DIR = tmp_path

    (tmp_path / "2026-05小袋多用总览.csv").write_text(
        "region,period,total_order_cnt,small_bag_order_cnt,small_bag_order_ratio,small_bag_extra_bag_qty,small_bag_extra_cost,add_order_cnt,replace_order_cnt,pure_order_cnt,add_order_ratio_in_small_bag,replace_order_ratio_in_small_bag,pure_order_ratio_in_small_bag,add_extra_bag_qty,replace_extra_bag_qty,pure_extra_bag_qty,add_extra_cost,replace_extra_cost,pure_extra_cost\n"
        "华东一区,2026-05,1000,180,0.18,240,2100.50,80,60,40,0.4444,0.3333,0.2222,100,80,60,800.1,700.2,600.2\n",
        encoding="utf-8",
    )
    (tmp_path / "2026-05小袋多用尺码归因明细.csv").write_text(
        "region,period,small_bag_type,delta_role,bag_size,order_cnt,delta_qty,qty_ratio_in_type\n"
        "华东一区,2026-05,加袋型,increase,S,50,60,0.6\n",
        encoding="utf-8",
    )
    (tmp_path / "2026-05小袋多用组合替代模式.csv").write_text(
        "region,period,replaced_from,replaced_to,combo_order_cnt,combo_extra_cost,combo_order_ratio_in_region\n"
        "华东一区,2026-05,XLx1,Mx1+Lx1,30,100.5,0.5\n",
        encoding="utf-8",
    )

    rows = service.load_small_bag_input_rows("2026-05")

    assert rows is not None
    assert rows["summary"][0]["total_order_cnt"] == 1000
    assert rows["summary"][0]["small_bag_order_ratio"] == 0.18
    assert rows["summary"][0]["small_bag_extra_cost"] == 2100.5
    assert rows["size_breakdown"][0]["order_cnt"] == 50
    assert rows["size_breakdown"][0]["qty_ratio_in_type"] == 0.6
    assert rows["combo_pattern"][0]["combo_order_cnt"] == 30
    assert rows["combo_pattern"][0]["combo_order_ratio_in_region"] == 0.5


def test_usage_diagnosis_uses_small_bag_csv_findings_when_triggered() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 200,
            "s_theory_qty": 200,
            "m_theory_qty": 200,
            "l_theory_qty": 200,
            "xl_theory_qty": 200,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 200,
            "s_actual_qty": 200,
            "m_actual_qty": 200,
            "l_actual_qty": 200,
            "xl_actual_qty": 200,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 1000,
            "s_stock_qty": 0,
            "m_stock_qty": 0,
            "l_stock_qty": 0,
            "xl_stock_qty": 0,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
        small_bag_summary_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "total_order_cnt": 1000,
            "small_bag_order_cnt": 180,
            "small_bag_order_ratio": 0.18,
            "small_bag_extra_bag_qty": 260,
            "small_bag_extra_cost": 2100.0,
            "add_order_cnt": 81,
            "replace_order_cnt": 72,
            "pure_order_cnt": 27,
            "add_order_ratio_in_small_bag": 0.45,
            "replace_order_ratio_in_small_bag": 0.40,
            "pure_order_ratio_in_small_bag": 0.15,
            "add_extra_bag_qty": 120,
            "replace_extra_bag_qty": 100,
            "pure_extra_bag_qty": 40,
            "add_extra_cost": 700.0,
            "replace_extra_cost": 900.0,
            "pure_extra_cost": 500.0,
        }],
        small_bag_size_rows=[
            {
                "region": "华东一区",
                "period": "2026-05",
                "small_bag_type": "加袋型",
                "delta_role": "increase",
                "bag_size": "S",
                "order_cnt": 70,
                "delta_qty": 600,
                "qty_ratio_in_type": 0.60,
            },
            {
                "region": "华东一区",
                "period": "2026-05",
                "small_bag_type": "纯粹多袋型",
                "delta_role": "increase",
                "bag_size": "XS",
                "order_cnt": 30,
                "delta_qty": 320,
                "qty_ratio_in_type": 0.80,
            },
        ],
        small_bag_combo_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "replaced_from": "XLx1",
            "replaced_to": "Mx1+Lx1",
            "combo_order_cnt": 40,
            "combo_extra_cost": 100.0,
            "combo_order_ratio_in_region": 0.40,
        }],
    )

    detail = diagnosis["problem_light_details"][0]
    usage = detail["usage_diagnosis"]

    assert usage["label"] == "未合并装袋（小袋多用）"
    assert usage["severity"] == "🟡"
    assert "小袋多用订单占比18.0%" in usage["summary"]
    assert "加袋型（占小袋多用订单的45.0%）：主要表现为额外多加S码600个" in usage["summary"]
    assert "组合替代型（占小袋多用订单的40.0%）：主要表现为XL码被M码+L码替代" in usage["summary"]
    assert "纯粹多袋型（占小袋多用订单的15.0%）：主要表现为XS码多用320个" in usage["summary"]
    assert usage["extra_cost"] == 2100.0


def test_usage_diagnosis_combines_large_bag_and_small_bag_findings() -> None:
    service = DiagnosisService()

    diagnosis = service.build_diagnosis(
        theory_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_theory_qty": 700,
            "s_theory_qty": 100,
            "m_theory_qty": 100,
            "l_theory_qty": 50,
            "xl_theory_qty": 50,
            "total_theory_qty": 1000,
        }],
        actual_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_actual_qty": 100,
            "s_actual_qty": 50,
            "m_actual_qty": 800,
            "l_actual_qty": 25,
            "xl_actual_qty": 25,
            "total_actual_qty": 1000,
        }],
        stock_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "xs_stock_qty": 700,
            "s_stock_qty": 100,
            "m_stock_qty": 100,
            "l_stock_qty": 50,
            "xl_stock_qty": 50,
            "total_stock_qty": 1000,
        }],
        report_month="2026-05",
        small_bag_summary_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "total_order_cnt": 1000,
            "small_bag_order_cnt": 220,
            "small_bag_order_ratio": 0.22,
            "small_bag_extra_bag_qty": 300,
            "small_bag_extra_cost": 1200.0,
            "add_order_cnt": 80,
            "replace_order_cnt": 100,
            "pure_order_cnt": 40,
            "add_order_ratio_in_small_bag": 0.36,
            "replace_order_ratio_in_small_bag": 0.45,
            "pure_order_ratio_in_small_bag": 0.18,
            "add_extra_bag_qty": 100,
            "replace_extra_bag_qty": 140,
            "pure_extra_bag_qty": 60,
            "add_extra_cost": 300.0,
            "replace_extra_cost": 700.0,
            "pure_extra_cost": 200.0,
        }],
        small_bag_size_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "small_bag_type": "加袋型",
            "delta_role": "increase",
            "bag_size": "S",
            "order_cnt": 40,
            "delta_qty": 120,
            "qty_ratio_in_type": 0.50,
        }],
        small_bag_combo_rows=[{
            "region": "华东一区",
            "period": "2026-05",
            "replaced_from": "XLx1",
            "replaced_to": "Mx2",
            "combo_order_cnt": 50,
            "combo_extra_cost": 200.0,
            "combo_order_ratio_in_region": 0.50,
        }],
    )

    usage = diagnosis["red_light_details"][0]["usage_diagnosis"]

    assert usage["label"] == "大袋小用 + 未合并装袋（小袋多用）"
    assert len(usage["findings"]) == 2
    assert usage["severity"] == "🔴"
    assert usage["extra_cost"] > 1200.0


def test_input_csv_reader_supports_gbk_region_names(tmp_path) -> None:
    path = tmp_path / "2026-05理论需求量.csv"
    path.write_text(
        '"region","period","xs_theory_qty","total_theory_qty"\n"华东二区","2026-05","10","10"\n',
        encoding="gbk",
    )

    rows = DiagnosisService._read_csv_rows(path)

    assert rows[0]["region"] == "华东二区"
    assert rows[0]["xs_theory_qty"] == 10


def test_build_actual_and_stock_rows_from_model_card_pivots_a597_rows() -> None:
    service = DiagnosisService()

    actual_rows, stock_rows = service.build_actual_and_stock_rows_from_model_card(
        rows=[
            {"滔搏纸袋分类": "总计", "原销售大区": "总计", "期末近30天累计纸袋销售量": 999, "期末业务库存量": 999},
            {"滔搏纸袋分类": "滔搏纸袋-L", "原销售大区": "小计", "期末近30天累计纸袋销售量": 999, "期末业务库存量": 999},
            {"滔搏纸袋分类": "滔搏纸袋-L", "原销售大区": "华东二区", "期末近30天累计纸袋销售量": 22589, "期末业务库存量": 42752},
            {"滔搏纸袋分类": "", "原销售大区": "华南一区", "期末近30天累计纸袋销售量": 10, "期末业务库存量": 20},
            {"滔搏纸袋分类": "ZD2023XS", "原销售大区": "华东二区", "期末近30天累计纸袋销售量": 100, "期末业务库存量": 200},
            {"滔搏纸袋分类": "其他", "原销售大区": "华东二区", "期末近30天累计纸袋销售量": 50, "期末业务库存量": 60},
        ],
        report_month="2026-05",
    )

    actual_by_region = {row["region"]: row for row in actual_rows}
    stock_by_region = {row["region"]: row for row in stock_rows}

    assert actual_by_region["华东二区"]["l_actual_qty"] == 22589
    assert actual_by_region["华东二区"]["xs_actual_qty"] == 100
    assert actual_by_region["华东二区"]["total_actual_qty"] == 22689
    assert stock_by_region["华东二区"]["l_stock_qty"] == 42752
    assert stock_by_region["华东二区"]["xs_stock_qty"] == 200
    assert stock_by_region["华东二区"]["total_stock_qty"] == 42952
    assert actual_by_region["华南一区"]["l_actual_qty"] == 10
    assert "小计" not in actual_by_region


def test_extract_model_card_rows_prefers_raw_payload_over_replaced_rows() -> None:
    service = DiagnosisService()
    dataset = NormalizedDataset(
        role="regional_model_purchase_analysis",
        card_id="a597c4441b7414c93a7c502d",
        card_name="分型号库存",
        section="inventory_diagnosis",
        rows=[{"滔搏纸袋分类": "滔搏纸袋-XS", "原销售大区": "华北二区", "期末近30天累计纸袋销售量": 79366}],
        summary={},
        raw_payload={
            "pages": [
                {
                    "data": {
                        "rowList": [
                            {
                                "滔搏纸袋分类": "滔搏纸袋-XS",
                                "原销售大区": "华北二区",
                                "期末近30天累计纸袋销售量": 79367,
                                "期末业务库存量": 134534,
                            }
                        ]
                    }
                }
            ]
        },
    )

    rows = service.extract_model_card_rows(dataset)

    assert rows == [{
        "滔搏纸袋分类": "滔搏纸袋-XS",
        "原销售大区": "华北二区",
        "期末近30天累计纸袋销售量": 79367,
        "期末业务库存量": 134534,
    }]


def test_diagnosis_only_keeps_current_nine_regions() -> None:
    service = DiagnosisService()
    base_theory = {
        "period": "2026-05",
        "xs_theory_qty": 100,
        "s_theory_qty": 0,
        "m_theory_qty": 0,
        "l_theory_qty": 0,
        "xl_theory_qty": 0,
        "total_theory_qty": 100,
    }
    base_actual = {
        "period": "2026-05",
        "xs_actual_qty": 100,
        "s_actual_qty": 0,
        "m_actual_qty": 0,
        "l_actual_qty": 0,
        "xl_actual_qty": 0,
        "total_actual_qty": 100,
    }
    base_stock = {
        "period": "2026-05",
        "xs_stock_qty": 100,
        "s_stock_qty": 0,
        "m_stock_qty": 0,
        "l_stock_qty": 0,
        "xl_stock_qty": 0,
        "total_stock_qty": 100,
    }

    diagnosis = service.build_diagnosis(
        theory_rows=[{**base_theory, "region": "华东一区"}, {**base_theory, "region": "港澳"}],
        actual_rows=[{**base_actual, "region": "华东一区"}, {**base_actual, "region": "港澳"}],
        stock_rows=[{**base_stock, "region": "华东一区"}, {**base_stock, "region": "港澳"}],
        report_month="2026-05",
    )

    assert diagnosis["total_regions"] == 1
    assert diagnosis["diagnosis_ranking"][0]["region"] == "华东一区"


def test_diagnosis_actual_sql_uses_orig_fields_from_optimization_table() -> None:
    sql = DiagnosisService().load_and_render_sql("diagnosis_actual_consumption.sql", "2026-05")

    assert "paimon.dwd_pub.t18_top_paper_bag_opt_price" in sql
    assert "SUM(COALESCE(t.orig_xs, 0))" in sql
    assert "SUM(COALESCE(t.orig_s, 0))" in sql
    assert "SUM(COALESCE(t.orig_m, 0))" in sql
    assert "SUM(COALESCE(t.orig_l, 0))" in sql
    assert "SUM(COALESCE(t.orig_xl, 0))" in sql
    assert "paper_bag_size_map" not in sql
    assert "pro_code" not in sql


def test_diagnosis_inventory_sql_uses_zd010_and_zd2023_size_map() -> None:
    sql = DiagnosisService().load_and_render_sql("diagnosis_inventory.sql", "2026-05")

    assert "WITH paper_bag_size_map AS" in sql
    assert "SELECT 'xs' AS bag_size" in sql
    assert "'ZD010XS' AS pro_code" in sql
    assert "SELECT 'xs', 'ZD2023XS'" in sql
    assert "SELECT 's', 'ZD010S'" in sql
    assert "SELECT 's', 'ZD2023S'" in sql
    assert "SELECT 'm', 'ZD010M'" in sql
    assert "SELECT 'm', 'ZD2023M'" in sql
    assert "SELECT 'l', 'ZD010L'" in sql
    assert "SELECT 'l', 'ZD2023L'" in sql
    assert "SELECT 'xl', 'ZD010XL'" in sql
    assert "SELECT 'xl', 'ZD2023XL'" in sql
    assert "INNER JOIN paper_bag_size_map m" in sql
    assert "ON i.pro_code = m.pro_code" in sql
    assert "ELSE '其他'" not in sql
    assert "MN2024XS" not in sql
    assert "ZD011" not in sql


def test_small_bag_overuse_summary_sql_uses_v13_classification_rules() -> None:
    sql = DiagnosisService().load_and_render_sql("diagnosis_small_bag_overuse_summary.sql", "2026-05")

    assert "delta_total > 0 AND has_decrease = 1 AND has_increase = 1 THEN '组合替代型'" in sql
    assert "delta_total > 0 AND has_decrease = 0 AND has_new_added_size = 1 THEN '加袋型'" in sql
    assert "delta_total > 0 THEN '纯粹多袋型'" in sql
    assert "GREATEST(COALESCE(t.cost, 0) - COALESCE(t.opt_cost, 0), 0) AS extra_cost" in sql
    assert "small_bag_order_ratio" in sql
    assert "2026-05" in sql


def test_small_bag_overuse_size_breakdown_sql_outputs_increase_and_decrease_roles() -> None:
    sql = DiagnosisService().load_and_render_sql("diagnosis_small_bag_overuse_size_breakdown.sql", "2026-05")

    assert "'increase' AS delta_role" in sql
    assert "'decrease' AS delta_role" in sql
    assert "qty_ratio_in_type" in sql
    assert "ORDER BY region, period, small_bag_type, delta_role, delta_qty DESC" in sql


def test_small_bag_overuse_combo_pattern_sql_builds_replacement_signatures() -> None:
    sql = DiagnosisService().load_and_render_sql("diagnosis_small_bag_overuse_combo_pattern.sql", "2026-05")

    assert "CONCAT_WS('+', SORT_ARRAY(COLLECT_LIST(CONCAT(bag_size, 'x', CAST(raw_delta AS STRING))))) AS replaced_to" in sql
    assert "CONCAT_WS('+', SORT_ARRAY(COLLECT_LIST(CONCAT(bag_size, 'x', CAST(-raw_delta AS STRING))))) AS replaced_from" in sql
    assert "combo_order_ratio_in_region" in sql
