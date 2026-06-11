from src.models.schemas import NormalizedDataset, ThresholdConfig
from src.services.metrics_service import MetricsService


def test_inventory_lights_and_future_demand_gaps() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="overall_inventory_ratio",
            card_id="1",
            card_name="总库销",
            section="inventory_diagnosis",
            rows=[{"库销比": 2.8, "同比": -0.5, "环比": 0.2}],
        ),
        NormalizedDataset(
            role="regional_inventory_ratio",
            card_id="2",
            card_name="地区库销",
            section="inventory_diagnosis",
            rows=[
                {"大区": "华东", "期末库销比": 2.4},
                {"大区": "华北", "期末库销比": 3.0},
                {"大区": "西北", "期末库销比": 3.8},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="3",
            card_name="订购辅助导出表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "华东", "滔搏纸袋分类": "滔搏纸袋-S", "筛选日期末库存": 80, "测算未来30天纸袋销量": 100},
                {"大区": "华北", "滔搏纸袋分类": "滔搏纸袋-M", "筛选日期末库存": 130, "测算未来30天纸袋销量": 100},
                {"大区": "西北", "滔搏纸袋分类": "滔搏纸袋-L", "筛选日期末库存": 180, "测算未来30天纸袋销量": 100},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    regional = facts["sections"]["inventory_diagnosis"]["facts"]["regional_status"]
    future_gaps = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["future_demand_gaps"]

    assert regional["green_count"] == 1
    assert regional["yellow_count"] == 1
    assert regional["red_count"] == 1
    assert len(future_gaps) == 2
    assert future_gaps[0]["level"] == "紧急"
    assert round(future_gaps[0]["suggested_order_qty"], 2) == 70
    assert future_gaps[1]["level"] == "重点关注"
    assert round(future_gaps[1]["suggested_order_qty"], 2) == 20


def test_history_purchase_join_uses_a597_and_forecast_thresholds() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_model_purchase_analysis",
            card_id="a597",
            card_name="库销比&进销比-by大区*(滔搏纸袋-分型号)",
            section="inventory_diagnosis",
            rows=[
                {
                    "原销售大区": "粤海",
                    "滔搏纸袋分类": "滔搏纸袋-L",
                    "期末业务库存量": 18000,
                    "期末库销比": 3.8,
                    "期末近30天累计厂入量": 8000,
                    "进销比": 2.0,
                    "期末近30天累计纸袋销售量": 42000,
                },
                {
                    "原销售大区": "东北",
                    "滔搏纸袋分类": "滔搏纸袋-XS",
                    "期末业务库存量": 9000,
                    "期末库销比": 4.2,
                    "期末近30天累计厂入量": 6000,
                    "进销比": 1.1,
                    "期末近30天累计纸袋销售量": 30000,
                },
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="2",
            card_name="订购辅助导出表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-L", "同期后30天纸袋销量": 5000, "测算未来30天纸袋销量": 4000, "次月期末库销测算": 3.5},
                {"大区": "东北", "滔搏纸袋分类": "滔搏纸袋-XS", "同期后30天纸袋销量": 7000, "测算未来30天纸袋销量": 6000, "次月期末库销测算": 2.4},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    history_rows = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["report_rows"]

    assert len(history_rows) == 1
    assert history_rows[0]["region"] == "粤海"
    assert history_rows[0]["model"] == "滔搏纸袋-L"
    assert history_rows[0]["sales_qty"] == 42000
    assert history_rows[0]["inventory_qty"] == 18000
    assert history_rows[0]["inbound_qty"] == 8000
    assert history_rows[0]["inbound_ratio"] == 2.0
    assert history_rows[0]["same_period_sales_qty"] == 5000
    assert history_rows[0]["future_usage"] == 4000
    assert round(history_rows[0]["future_ratio"], 2) == 3.5


def test_store_name_is_aggregated_from_order_anomalies() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="order_ratio_anomalies",
            card_id="1",
            card_name="订单异常",
            section="consumption_exceptions",
            rows=[
                {
                    "原销售大区": "华东",
                    "原销售店": "上海南京西路旗舰店",
                    "原销售店号": "SH001",
                    "纸袋配比": 1.3,
                    "纸袋耗用成本": 300.0,
                }
            ],
        ),
        NormalizedDataset(
            role="overall_consumption_summary",
            card_id="2",
            card_name="总配比",
            section="consumption_exceptions",
            rows=[{"纸袋配比": 0.8}],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    store_name = facts["sections"]["consumption_exceptions"]["facts"]["consumption_exceptions"]["store_rollups"][0]["store"]
    assert store_name == "上海南京西路旗舰店"


def test_inventory_overview_can_aggregate_from_filtered_regional_rows() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="1",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {"地区": "粤海", "期末业务库存量": 300.0, "期末近30天累计纸袋销售量": 100.0, "期末库销比": 3.0},
                {"地区": "东北", "期末业务库存量": 150.0, "期末近30天累计纸袋销售量": 50.0, "期末库销比": 3.0},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    inventory_ratio = facts["sections"]["inventory_diagnosis"]["facts"]["inventory_overview"]["ratio"]

    assert inventory_ratio == 3.0


def test_consumption_exceptions_regional_anomaly_rows_are_derived_from_order_details() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="order_ratio_anomalies",
            card_id="l6e08fdcc7fef45ccaa31d1b",
            card_name="订单异常明细",
            section="consumption_exceptions",
            rows=[
                {"日期 (月)": "2026-03", "原销售大区": "东北", "纸袋配比": 1.2},
                {"日期 (月)": "2026-03", "原销售大区": "东北", "纸袋配比": 1.1},
                {"日期 (月)": "2026-03", "原销售大区": "粤海", "纸袋配比": 1.3},
                {"日期 (月)": "2026-03", "原销售大区": "粤海", "纸袋配比": 0.9},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    regional_rows = facts["sections"]["consumption_exceptions"]["facts"]["consumption_exceptions"]["regional_anomaly_rows"]

    assert regional_rows[0]["region"] == "东北"
    assert regional_rows[0]["count"] == 2


def test_consumption_ratio_prefers_non_group_metric() -> None:
    service = MetricsService(
        ThresholdConfig(),
    )
    datasets = [
        NormalizedDataset(
            role="consumption_ratio_monthly",
            card_id="j21833508e589464c922d381",
            card_name="门店纸袋配比[总]-by月",
            section="consumption_exceptions",
            rows=[
                {"日期 (月)": "2026-03", "纸袋配比": 0.61, "纸袋配比-不含团购": 0.72},
                {"日期 (月)": "2026-02", "纸袋配比": 0.66, "纸袋配比-不含团购": 0.73},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    consumption = facts["sections"]["consumption_exceptions"]["facts"]["consumption_exceptions"]

    assert consumption["overall_ratio"] == 0.72
    assert consumption["ratio_history"][-1]["value"] == 0.72


def test_inventory_trend_uses_latest_row_for_overview_ratio() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="overall_inventory_trend",
            card_id="1",
            card_name="趋势卡",
            section="inventory_diagnosis",
            rows=[
                {"日期": "2026-02-28", "FY26-库销比": 1.2},
                {"日期": "2026-03-01", "FY26-库销比": 1.5, "FY25-库销比": 6.0},
                {"日期": "2026-03-31", "FY26-库销比": 2.8, "FY25-库销比": 5.6},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    overview = facts["sections"]["inventory_diagnosis"]["facts"]["inventory_overview"]

    assert overview["ratio"] == 2.8
    assert round(overview["yoy"], 4) == -0.5
    assert round(overview["mom"], 4) == round((2.8 - 1.2) / 1.2, 4)
    assert len(overview["trend_series"]) == 2
    assert overview["trend_series"][0]["label"] == "2026-03-01"


def test_inventory_trend_series_includes_inventory_qty_for_current_month() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="overall_inventory_trend",
            card_id="1",
            card_name="趋势卡",
            section="inventory_diagnosis",
            rows=[
                {"日期": "2026-02-28", "FY26-库销比": 1.2, "FY26-纸袋业务存量": 1200000},
                {"日期": "2026-03-01", "FY26-库销比": 1.5, "FY26-纸袋业务存量": 1500000, "FY25-库销比": 6.0},
                {"日期": "2026-03-31", "FY26-库销比": 2.8, "FY26-纸袋业务存量": 2800000, "FY25-库销比": 5.6},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    trend_series = facts["sections"]["inventory_diagnosis"]["facts"]["inventory_overview"]["trend_series"]

    assert len(trend_series) == 2
    assert trend_series[0]["inventory_qty"] == 1500000
    assert trend_series[1]["inventory_qty"] == 2800000


def test_inventory_overview_adds_plateau_summary_and_blocking_reasons() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="overall_inventory_trend",
            card_id="trend-1",
            card_name="公司趋势",
            section="inventory_diagnosis",
            rows=[
                {"日期": "2026-03-10", "FY26-库销比": 3.21, "FY26-纸袋业务存量": 3100000},
                {"日期": "2026-03-20", "FY26-库销比": 3.32, "FY26-纸袋业务存量": 3250000},
                {"日期": "2026-03-31", "FY26-库销比": 3.28, "FY26-纸袋业务存量": 3200000},
            ],
        ),
        NormalizedDataset(
            role="regional_inventory_ratio",
            card_id="region-1",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "期末库销比": 3.8},
                {"大区": "东北", "期末库销比": 3.1},
            ],
        ),
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="purchase-1",
            card_name="地区采购",
            section="inventory_diagnosis",
            rows=[
                {"地区": "粤海", "期末业务库存量": 500000, "期末近30天累计纸袋销售量": 100000, "期末库销比": 5.0, "期末近30天累计厂入量": 80000, "进销比": 2.5},
                {"地区": "东北", "期末业务库存量": 380000, "期末近30天累计纸袋销售量": 100000, "期末库销比": 3.8, "期末近30天累计厂入量": 30000, "进销比": 1.2},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="forecast-1",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-L", "筛选日期末库存": 25000, "库销比": 4.2, "测算未来30天纸袋销量": 5000},
                {"大区": "东北", "滔搏纸袋分类": "滔搏纸袋-S", "筛选日期末库存": 22000, "库销比": 3.9, "测算未来30天纸袋销量": 4000},
            ],
        ),
        NormalizedDataset(
            role="regional_model_purchase_analysis",
            card_id="model-1",
            card_name="型号结构",
            section="inventory_diagnosis",
            rows=[
                {"滔搏纸袋分类": "滔搏纸袋-XS", "原销售大区": "东北", "期末业务库存量": 24000, "期末近30天累计纸袋销售量": 3000, "期末库销比": 8.0, "期末近30天累计厂入量": 1000},
                {"滔搏纸袋分类": "滔搏纸袋-M", "原销售大区": "东北", "期末业务库存量": 11000, "期末近30天累计纸袋销售量": 15000, "期末库销比": 0.73, "期末近30天累计厂入量": 1000},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    overview = facts["sections"]["inventory_diagnosis"]["facts"]["inventory_overview"]
    regional_status = facts["sections"]["inventory_diagnosis"]["facts"]["regional_status"]

    assert "运行于3.21-3.32区间" in overview["plateau_summary_sentence"]
    assert "高位横盘" in overview["plateau_summary_sentence"]
    assert any("粤海（库销比3.80）" in reason and "东北（库销比3.10）" in reason for reason in overview["blocking_reasons"])
    assert any("粤海-滔搏纸袋-L" in reason and "高库销&高进销" in reason for reason in overview["blocking_reasons"])
    assert any("东北库存端以滔搏纸袋-XS为主" in reason for reason in overview["blocking_reasons"])
    assert regional_status["summary_sentence"] == "地区分层结果显示，红灯1个、黄灯1个。"


def test_purchase_analysis_outputs_quantified_future_demand_gaps() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="1",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {"地区": "东北", "期末业务库存量": 300000, "期末近30天累计纸袋销售量": 100000, "期末库销比": 3.0, "期末近30天累计厂入量": 50000},
                {"地区": "粤海", "期末业务库存量": 500000, "期末近30天累计纸袋销售量": 100000, "期末库销比": 5.0, "期末近30天累计厂入量": 80000},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="2",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-M", "筛选日期末库存": 20000, "库销比": 4.0, "测算未来30天纸袋销量": 4000},
                {"大区": "东北", "滔搏纸袋分类": "滔搏纸袋-M", "筛选日期末库存": 2000, "库销比": 0.4, "测算未来30天纸袋销量": 4000},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    purchase_analysis = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]
    future_gaps = purchase_analysis["future_demand_gaps"]

    assert "transfer_hints" not in purchase_analysis
    assert len(future_gaps) == 1
    assert future_gaps[0]["region"] == "东北"
    assert future_gaps[0]["model"] == "滔搏纸袋-M"
    assert round(future_gaps[0]["shortage_qty"], 2) == 2000
    assert round(future_gaps[0]["suggested_order_qty"], 2) == 4000


def test_history_purchase_join_uses_regional_model_dataset_fields() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="c526",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {"地区": "粤海", "期末业务库存量": 396284, "期末近30天累计纸袋销售量": 142320, "期末库销比": 2.78, "期末近30天累计厂入量": 44600, "进销比": 0.31},
            ],
        ),
        NormalizedDataset(
            role="regional_model_purchase_analysis",
            card_id="a597",
            card_name="分型号库销比",
            section="inventory_diagnosis",
            rows=[
                {"滔搏纸袋分类": "滔搏纸袋-L", "原销售大区": "粤海", "期末近30天累计纸袋销售量": 9301, "期末业务库存量": 38396, "期末库销比": 2.1281, "期末近30天累计厂入量": 20000, "进销比": 2.1503},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="u114",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-L", "筛选日期末库存": 38396, "库销比": 2.1281, "同期后30天纸袋销量": 5000, "测算未来30天纸袋销量": 6000, "次月期末库销测算": 5.3993},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    history_rows = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["history_evaluations"]
    report_rows = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["report_rows"]

    assert history_rows
    assert history_rows[0]["region"] == "粤海"
    assert history_rows[0]["model"] == "滔搏纸袋-L"
    assert history_rows[0]["sales_qty"] == 9301
    assert history_rows[0]["inventory_qty"] == 38396
    assert round(history_rows[0]["inbound_ratio"], 4) == 2.1503
    assert history_rows[0]["same_period_sales_qty"] == 5000
    assert history_rows[0]["future_usage"] == 6000
    assert history_rows[0]["diagnosis"] == "高库销高进销-月度多订"
    assert "订购恰当性不足" in history_rows[0]["decision_comment"]
    assert report_rows == []


def test_history_purchase_analysis_only_uses_joined_a597_and_u114_rows() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_model_purchase_analysis",
            card_id="a597",
            card_name="分型号库销比",
            section="inventory_diagnosis",
            rows=[
                {"滔搏纸袋分类": "滔搏纸袋-L", "原销售大区": "粤海", "期末近30天累计纸袋销售量": 9301, "期末业务库存量": 38396, "期末库销比": 4.1281, "期末近30天累计厂入量": 20000, "进销比": 2.1503},
                {"滔搏纸袋分类": "滔搏纸袋-S", "原销售大区": "粤海", "期末近30天累计纸袋销售量": 5000, "期末业务库存量": 12000, "期末库销比": 3.6, "期末近30天累计厂入量": 1000, "进销比": 0.2},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="u114",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-L", "同期后30天纸袋销量": 5000, "测算未来30天纸袋销量": 6000, "次月期末库销测算": 5.3993},
                {"大区": "东北", "滔搏纸袋分类": "滔搏纸袋-S", "同期后30天纸袋销量": 8000, "测算未来30天纸袋销量": 9000, "次月期末库销测算": 3.1},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    history_rows = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["report_rows"]

    assert len(history_rows) == 1
    assert history_rows[0]["region"] == "粤海"
    assert history_rows[0]["model"] == "滔搏纸袋-L"


def test_history_purchase_analysis_keeps_yellow_ending_ratio_for_matrix_review() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_model_purchase_analysis",
            card_id="a597",
            card_name="分型号库销比",
            section="inventory_diagnosis",
            rows=[
                {"滔搏纸袋分类": "滔搏纸袋-L", "原销售大区": "粤海", "期末近30天累计纸袋销售量": 9301, "期末业务库存量": 38396, "期末库销比": 3.2, "期末近30天累计厂入量": 20000, "进销比": 2.1503},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="u114",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-L", "同期后30天纸袋销量": 5000, "测算未来30天纸袋销量": 6000, "次月期末库销测算": 5.3993},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    report_rows = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["report_rows"]

    assert len(report_rows) == 1
    assert report_rows[0]["region"] == "粤海"
    assert report_rows[0]["model"] == "滔搏纸袋-L"


def test_history_purchase_analysis_marks_low_inbound_as_backlog_risk() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="c526",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {"地区": "粤海", "期末业务库存量": 396284, "期末近30天累计纸袋销售量": 100000, "期末库销比": 2.2, "期末近30天累计厂入量": 10000, "进销比": 0.8},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="u114",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-L", "筛选日期末库存": 38396, "库销比": 2.2, "同期后30天纸袋销量": 5000, "测算未来30天纸袋销量": 6000, "次月期末库销测算": 5.3993},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    purchase = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]
    history_rows = purchase["history_evaluations"]

    assert history_rows[0]["diagnosis"] == "高库销低进销-持续积压"
    assert "去库存为先" in history_rows[0]["decision_comment"]
    assert purchase["high_inventory_high_inbound_count"] == 0
    assert purchase["high_inventory_low_inbound_count"] == 1


def test_metrics_service_builds_paper_bag_specs_reference_context() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="paper_bag_specs_reference",
            card_id="specs",
            card_name="纸袋规格",
            section="inventory_diagnosis",
            rows=[
                {
                    "纸袋编码": "ZD2023XL",
                    "规格型号": "1号（特大号纸袋XL）",
                    "型号(mm)": "ZD2023XL(55X42+15)",
                    "使用场景": "棉羽；特殊鞋盒",
                    "使用频率": "冬季订购",
                    "纸袋型号": "滔搏纸袋-XL",
                }
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    reference = facts["reference_context"]["inventory_diagnosis"]["paper_bag_specs"][0]

    assert reference["paper_bag_model"] == "滔搏纸袋-XL"
    assert reference["usage_scenes"] == "棉羽；特殊鞋盒"


def test_ai_insights_are_quantified_by_model_and_quantity() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_inventory_ratio",
            card_id="u5ced9a38526c4daa8720dd3",
            card_name="大区库销比_不含团购",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "期末库销比": 3.6},
                {"大区": "东北", "期末库销比": 2.2},
            ],
        ),
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="1",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {"地区": "粤海", "期末业务库存量": 500000, "期末近30天累计纸袋销售量": 100000, "期末库销比": 5.0, "期末近30天累计厂入量": 80000},
                {"地区": "东北", "期末业务库存量": 300000, "期末近30天累计纸袋销售量": 100000, "期末库销比": 3.0, "期末近30天累计厂入量": 50000},
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="2",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "粤海", "滔搏纸袋分类": "滔搏纸袋-M", "筛选日期末库存": 20000, "库销比": 4.0, "测算未来30天纸袋销量": 4000},
                {"大区": "东北", "滔搏纸袋分类": "滔搏纸袋-S", "筛选日期末库存": 2000, "库销比": 0.2, "测算未来30天纸袋销量": 4000},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    actions = facts["ai_insights"]["regional_actions"]
    yuehai = next(item for item in actions if item["region"] == "粤海")

    assert yuehai["focus_models"] == ["滔搏纸袋-M"]
    assert "滔搏纸袋-M期末库存20000个" in yuehai["root_cause"]
    assert yuehai["business_plan"] == "1. 滔搏纸袋-M：库存积压，库销比4.00，立即停止订购。"
    assert yuehai["priority_rule"].startswith("P")
    assert "严重度评分" in yuehai["priority_reason"]
    assert "调拨" not in yuehai["business_plan"]
    assert all(item["priority"] in {"P1", "P2"} for item in actions)
    assert all(item["region"] != "东北" for item in actions)


def test_model_inventory_profile_builds_pivot_and_share_rows() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_model_purchase_analysis",
            card_id="a597",
            card_name="分型号库销比",
            section="inventory_diagnosis",
            rows=[
                {"滔搏纸袋分类": "滔搏纸袋-S", "原销售大区": "粤海", "期末业务库存量": 15000, "期末近30天累计纸袋销售量": 9000, "期末库销比": 3.8, "期末近30天累计厂入量": 2000},
                {"滔搏纸袋分类": "滔搏纸袋-M", "原销售大区": "粤海", "期末业务库存量": 30000, "期末近30天累计纸袋销售量": 3000, "期末库销比": 4.2, "期末近30天累计厂入量": 5000},
                {"滔搏纸袋分类": "滔搏纸袋-S", "原销售大区": "东北", "期末业务库存量": 20000, "期末近30天累计纸袋销售量": 4000, "期末库销比": 3.6, "期末近30天累计厂入量": 3000},
                {"滔搏纸袋分类": "滔搏纸袋-XL", "原销售大区": "东北", "期末业务库存量": 9000, "期末库销比": 4.0, "期末近30天累计厂入量": 1000},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    purchase = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]

    assert purchase["model_inventory_models"] == ["滔搏纸袋-S", "滔搏纸袋-M"]
    assert purchase["model_inventory_pivot"][0]["region"] == "粤海"
    assert purchase["model_inventory_pivot"][0]["total_inventory_qty"] == 45000
    assert purchase["model_inventory_share_rows"][0]["model_shares"]["滔搏纸袋-M"] == 30000 / 45000
    assert purchase["model_usage_pivot"][0]["total_sales_qty"] == 12000
    assert purchase["model_usage_share_rows"][0]["model_shares"]["滔搏纸袋-S"] == 9000 / 12000
    assert purchase["model_inventory_analysis"][0]["top_model"] == "滔搏纸袋-M"
    assert purchase["model_inventory_analysis"][0]["usage_top_model"] == "滔搏纸袋-S"
    assert purchase["model_inventory_analysis"][0]["structure_label"] == "库存偏大码积压"
    assert purchase["model_inventory_analysis"][0]["waste_risk"] is False


def test_model_inventory_suggestion_uses_only_displayed_main_models_for_concentration() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_model_purchase_analysis",
            card_id="a597",
            card_name="分型号库销比",
            section="inventory_diagnosis",
            rows=[
                {"滔搏纸袋分类": "滔搏纸袋-M", "原销售大区": "东北", "期末业务库存量": 64200, "期末近30天累计纸袋销售量": 85200, "期末库销比": 0.75, "期末近30天累计厂入量": 1000},
                {"滔搏纸袋分类": "滔搏纸袋-XS", "原销售大区": "东北", "期末业务库存量": 25000, "期末近30天累计纸袋销售量": 5000, "期末库销比": 5.0, "期末近30天累计厂入量": 1000},
                {"滔搏纸袋分类": "滔搏纸袋-S", "原销售大区": "东北", "期末业务库存量": 10800, "期末近30天累计纸袋销售量": 9800, "期末库销比": 1.1, "期末近30天累计厂入量": 1000},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    row = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["model_inventory_analysis"][0]

    assert row["top_model"] == "滔搏纸袋-M"
    assert row["usage_top_model"] == "滔搏纸袋-M"
    assert row["structure_label"] == "结构集中待跟踪"
    assert round(row["structure_gap_pp"], 1) == 21.0
    assert "滔搏纸袋-XS" not in row["suggestion"]
    assert "21.0个百分点" in row["suggestion"]


def test_ai_insights_action_list_supports_multiple_numbered_actions() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_inventory_ratio",
            card_id="u5ced9a38526c4daa8720dd3",
            card_name="大区库销比_不含团购",
            section="inventory_diagnosis",
            rows=[
                {"大区": "川藏新", "期末库销比": 3.8},
            ],
        ),
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="1",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {
                    "地区": "川藏新",
                    "期末业务库存量": 450000,
                    "期末近30天累计纸袋销售量": 100000,
                    "期末库销比": 4.5,
                    "期末近30天累计厂入量": 60000,
                }
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="2",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "川藏新", "滔搏纸袋分类": "滔搏纸袋-XL", "筛选日期末库存": 26000, "库销比": 4.2, "测算未来30天纸袋销量": 4000},
                {"大区": "川藏新", "滔搏纸袋分类": "滔搏纸袋-S", "筛选日期末库存": 1000, "库销比": 0.1, "测算未来30天纸袋销量": 4000},
            ],
        ),
        NormalizedDataset(
            role="order_ratio_anomalies",
            card_id="3",
            card_name="订单异常",
            section="consumption_exceptions",
            rows=[
                {"日期 (月)": "2026-03", "原销售大区": "川藏新", "纸袋配比": 1.4},
                {"日期 (月)": "2026-03", "原销售大区": "川藏新", "纸袋配比": 1.2},
            ],
        ),
        NormalizedDataset(
            role="stocktake_difference",
            card_id="4",
            card_name="盘差率大于5%大区维度",
            section="consumption_exceptions",
            rows=[
                {"盘点月": "2026-03", "大区": "川藏新", "合计盘盈亏数量": -2938, "盘差率大于5%损失计算": -4111},
            ],
        ),
        NormalizedDataset(
            role="stocktake_monthly",
            card_id="5",
            card_name="门店纸袋盘点-by月",
            section="consumption_exceptions",
            rows=[
                {"盘点日 (月)": "2026-03", "盘差数量": -2938, "盘盈数量": 0},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    chuanzangxin = next(item for item in facts["ai_insights"]["regional_actions"] if item["region"] == "川藏新")

    assert chuanzangxin["focus_models"] == ["滔搏纸袋-XL", "滔搏纸袋-S"]
    assert "1. 滔搏纸袋-XL：库存积压，库销比4.20，立即停止订购。" in chuanzangxin["business_plan"]
    assert "2. 滔搏纸袋-S：库存短缺，库销比0.10，尽快补货5000个。" in chuanzangxin["business_plan"]
    assert "3. 异常订单：2单高配比，立即复盘整改。" in chuanzangxin["business_plan"]
    assert "4. 盘点差异：净盘差2938个，立即复核追损4111元。" in chuanzangxin["business_plan"]
    assert "<br>" in chuanzangxin["business_plan"]
    assert chuanzangxin["baseline"]["action_count"] == 4


def test_ai_insights_business_plan_is_concise_corrective_notice() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_inventory_ratio",
            card_id="u5ced9a38526c4daa8720dd3",
            card_name="大区库销比_不含团购",
            section="inventory_diagnosis",
            rows=[
                {"大区": "川藏新", "期末库销比": 3.8},
            ],
        ),
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="1",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {
                    "地区": "川藏新",
                    "期末业务库存量": 450000,
                    "期末近30天累计纸袋销售量": 100000,
                    "期末库销比": 4.5,
                    "期末近30天累计厂入量": 60000,
                }
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="2",
            card_name="预测表",
            section="inventory_diagnosis",
            rows=[
                {"大区": "川藏新", "滔搏纸袋分类": "滔搏纸袋-XL", "筛选日期末库存": 26000, "库销比": 4.2, "测算未来30天纸袋销量": 4000},
                {"大区": "川藏新", "滔搏纸袋分类": "滔搏纸袋-S", "筛选日期末库存": 1000, "库销比": 0.1, "测算未来30天纸袋销量": 4000},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    chuanzangxin = next(item for item in facts["ai_insights"]["regional_actions"] if item["region"] == "川藏新")

    assert chuanzangxin["business_plan"].split("<br>") == [
        "1. 滔搏纸袋-XL：库存积压，库销比4.20，立即停止订购。",
        "2. 滔搏纸袋-S：库存短缺，库销比0.10，尽快补货5000个。",
    ]
    assert "川藏新：" not in chuanzangxin["business_plan"]
    assert "超储" not in chuanzangxin["business_plan"]
    assert "安全库存" not in chuanzangxin["business_plan"]


def test_stocktake_risks_choose_regional_source_closer_to_monthly_total() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="stocktake_monthly",
            card_id="qd0651b4b8bc944e88a6d1f0",
            card_name="门店纸袋盘点-by月",
            section="consumption_exceptions",
            rows=[
                {"盘点日 (月)": "2026-03", "盘差数量": -100, "盘盈数量": 0},
            ],
        ),
        NormalizedDataset(
            role="stocktake_region",
            card_id="cf574aff05e5a4e4a997ff52",
            card_name="门店纸袋盘点-by大区",
            section="consumption_exceptions",
            rows=[
                {"大区": "东北", "盘差数量": -600, "盘盈数量": 0},
                {"大区": "粤海", "盘差数量": -500, "盘盈数量": 0},
            ],
        ),
        NormalizedDataset(
            role="stocktake_difference",
            card_id="b0432cceaa1944241be3f0dc",
            card_name="盘差率大于5%大区维度",
            section="consumption_exceptions",
            rows=[
                {"盘点月": "2026-03", "大区": "东北", "合计盘盈亏数量": -60, "盘差率大于5%损失计算": -120},
                {"盘点月": "2026-03", "大区": "粤海", "合计盘盈亏数量": -40, "盘差率大于5%损失计算": -100},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    stocktake = facts["sections"]["consumption_exceptions"]["facts"]["stocktake_risks"]

    assert stocktake["monthly_loss"] == 100
    assert stocktake["regional_source"] == "门店纸袋盘点-by大区"
    assert sum(item["net_loss_qty"] for item in stocktake["regional_rows"]) == 1100
    assert sum(item["net_loss_qty"] for item in stocktake["difference_rows"]) == 100
    assert stocktake["focus_regions"] == []


def test_history_purchase_snapshot_uses_regional_sales_qty() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="regional_purchase_evaluation",
            card_id="1",
            card_name="大区库销比",
            section="inventory_diagnosis",
            rows=[
                {
                    "地区": "粤海",
                    "期末业务库存量": 418000,
                    "期末库销比": 3.8,
                    "期末近30天累计厂入量": 8000,
                    "期末近30天累计纸袋销售量": 42000,
                }
            ],
        ),
        NormalizedDataset(
            role="purchase_forecast_sheet",
            card_id="2",
            card_name="订购辅助导出表",
            section="inventory_diagnosis",
            rows=[
                {
                    "大区": "粤海",
                    "滔搏纸袋分类": "滔搏纸袋-L",
                    "筛选日期末库存": 18000,
                    "库销比": 4.5,
                    "测算未来30天纸袋销量": 4000,
                }
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    history_rows = facts["sections"]["inventory_diagnosis"]["facts"]["purchase_analysis"]["history_evaluations"]

    assert history_rows
    assert history_rows[0]["regional_sales_qty"] == 42000


def test_stocktake_focus_uses_qty_threshold_when_amount_missing() -> None:
    service = MetricsService(ThresholdConfig(regional_inventory_loss_qty_max=500))
    datasets = [
        NormalizedDataset(
            role="stocktake_monthly",
            card_id="qd0651b4b8bc944e88a6d1f0",
            card_name="门店纸袋盘点-by月",
            section="consumption_exceptions",
            rows=[
                {"盘点日 (月)": "2026-03", "盘差数量": -600, "盘盈数量": 0},
            ],
        ),
        NormalizedDataset(
            role="stocktake_region",
            card_id="cf574aff05e5a4e4a997ff52",
            card_name="门店纸袋盘点-by大区",
            section="consumption_exceptions",
            rows=[
                {"大区": "东北", "盘差数量": -600, "盘盈数量": 0},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    stocktake = facts["sections"]["consumption_exceptions"]["facts"]["stocktake_risks"]

    assert stocktake["focus_regions"]
    assert stocktake["focus_regions"][0]["region"] == "东北"


def test_stocktake_difference_rows_and_focus_regions_sort_by_absolute_loss_amount() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="stocktake_monthly",
            card_id="qd0651b4b8bc944e88a6d1f0",
            card_name="门店纸袋盘点-by月",
            section="consumption_exceptions",
            rows=[
                {"盘点日 (月)": "2026-03", "盘差数量": -5000, "盘盈数量": 0},
            ],
        ),
        NormalizedDataset(
            role="stocktake_difference",
            card_id="b0432cceaa1944241be3f0dc",
            card_name="盘差率大于5%大区维度",
            section="consumption_exceptions",
            rows=[
                {"盘点月": "2026-03", "大区": "鲁西苏", "合计盘盈亏数量": -945, "盘差率大于5%损失计算": -1040.36},
                {"盘点月": "2026-03", "大区": "川藏新", "合计盘盈亏数量": -2938, "盘差率大于5%损失计算": -4111.03},
                {"盘点月": "2026-03", "大区": "浙皖", "合计盘盈亏数量": -1114, "盘差率大于5%损失计算": -1367.04},
            ],
        ),
    ]

    facts = service.build_report_facts(datasets, "2026-03")
    stocktake = facts["sections"]["consumption_exceptions"]["facts"]["stocktake_risks"]

    assert stocktake["difference_rows"][0]["region"] == "川藏新"
    assert stocktake["focus_regions"][0]["region"] == "川藏新"


def test_stocktake_difference_chart_extracts_fiscal_quantity_and_amount_rows() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="stocktake_difference_chart",
            card_id="nb692ce19d26a49569de3ca8",
            card_name="门店纸袋盘点情况 总 #",
            section="consumption_exceptions",
            rows=[
                {"财年": "2323", "盘亏数量": 0, "盘亏金额": 0, "盘盈数量": 0, "盘盈金额": 0},
                {"财年": "2026", "盘亏数量": -28527, "盘亏金额": -31706.03, "盘盈数量": 19257, "盘盈金额": 22824.69},
                {"财年": "2025", "盘亏数量": -491173, "盘亏金额": -513949.12, "盘盈数量": 408990, "盘盈金额": 475231.44},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-04")
    stocktake = facts["sections"]["consumption_exceptions"]["facts"]["stocktake_risks"]

    assert [row["label"] for row in stocktake["difference_fiscal_rows"]] == ["FY25", "FY26"]
    assert stocktake["difference_fiscal_rows"][0]["total_qty"] == -82183
    assert round(stocktake["difference_fiscal_rows"][1]["total_amount"], 2) == -8881.34


def test_order_anomalies_filter_to_report_month() -> None:
    service = MetricsService(ThresholdConfig())
    datasets = [
        NormalizedDataset(
            role="order_ratio_anomalies",
            card_id="l6e08fdcc7fef45ccaa31d1b",
            card_name="店铺订单维度纸袋使用配比明细",
            section="consumption_exceptions",
            rows=[
                {"日期 (月)": "2025-04", "原销售大区": "鲁西苏", "原销售店号": "OLD01", "订单编号": "OLD", "纸袋配比": 99},
                {"日期 (月)": "2026-04", "原销售大区": "湘桂", "原销售店号": "NEW01", "订单编号": "NEW", "纸袋配比": 3.5},
            ],
        )
    ]

    facts = service.build_report_facts(datasets, "2026-04")
    consumption = facts["sections"]["consumption_exceptions"]["facts"]["consumption_exceptions"]

    assert [item["order_id"] for item in consumption["order_anomalies"]] == ["NEW"]
    assert consumption["regional_anomaly_rows"][0]["region"] == "湘桂"
