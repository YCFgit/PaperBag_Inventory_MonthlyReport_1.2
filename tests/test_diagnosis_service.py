from src.services.diagnosis_service import DiagnosisService


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
    assert m_problem["adjusted_deviation_rate_pct"] == "885.0%"
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
    assert detail["stock_problems"][0]["adjusted_diff_pct"] == "45.0%"
    assert detail["stock_problems"][1]["diff_pct"] == "-50.0%"
    assert [action["priority"] for action in detail["recommended_actions"]] == sorted(
        [action["priority"] for action in detail["recommended_actions"]],
        key={"高": 0, "中": 1, "低": 2}.get,
    )


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
    assert row["inventory_health_score"] == 95.0


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
