from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from src.models.schemas import NormalizedDataset, ThresholdConfig


class MetricsService:
    DEFAULT_FIELD_ALIASES = {
        "region_keys": ["大区", "原销售大区", "地区", "区域", "管理大区", "区域名称", "战区"],
        "region_values": ["东北", "云贵渝", "京津晋", "冀蒙", "川藏新", "总公司", "总部", "河南", "浙皖", "港澳", "湘桂", "粤海", "西北", "鄂赣闽", "鲁东沪", "鲁西苏"],
        "store_keys": ["原销售店", "销售店", "店铺名称", "门店名称", "店铺", "门店", "店号"],
        "model_keys": ["型号", "规格", "货号", "纸袋型号", "尺码", "滔搏纸袋分类", "包装规格"],
        "non_group_ratio_keys": ["纸袋配比-不含团购", "不含团购纸袋配比", "不含团购配比"],
        "ratio_keys": ["库销比", "期末库销比", "纸袋配比", "配比", "库存销售比"],
        "yoy_keys": ["同比", "同比变化", "同比值", "去年同期变化"],
        "mom_keys": ["环比", "环比变化", "环比值", "较上月变化"],
        "amount_keys": ["金额", "盘亏金额", "盘亏损失金额", "损失金额", "纸袋耗用成本", "费用", "成本"],
        "count_keys": [
            "数量",
            "库存",
            "销量",
            "订单量",
            "盘亏数量",
            "使用量",
            "近30天纸袋销量",
            "同期后30天纸袋销量",
            "测算未来30天纸袋销量",
        ],
        "inventory_keys": ["库存量", "纸袋业务库存量", "期末业务库存量", "业务库存量", "期末库存", "筛选日期末库存", "纸袋业务存量", "业务存量", "库存"],
        "sales_keys": ["销售量", "近30天纸袋销量", "30天累计纸袋销售量", "期末近30天累计纸袋销售量", "近30天累计销量"],
        "inbound_keys": ["厂入量", "采购量", "入量", "近30天累计厂入量", "期末近30天累计厂入量"],
        "inbound_ratio_keys": ["进销比"],
        "future_ratio_keys": ["次月期末库销测算", "次月期末库销比", "库存/同期后30天纸袋销量", "预测库销比"],
        "future_sales_keys": ["测算未来30天纸袋销量", "未来30天纸袋销量", "次月预估用量", "预估未来30天纸袋销量", "同期后30天纸袋销量"],
        "period_keys": ["日期 (月)", "盘点日 (月)", "日期", "月份", "月", "统计月份", "区间", "期间"],
    }

    def __init__(self, thresholds: ThresholdConfig, field_aliases: dict[str, Any] | None = None) -> None:
        self.thresholds = thresholds
        aliases = field_aliases or {}
        self.region_keys = aliases.get("region_keys", self.DEFAULT_FIELD_ALIASES["region_keys"])
        self.region_values = aliases.get("region_values", self.DEFAULT_FIELD_ALIASES["region_values"])
        self.store_keys = aliases.get("store_keys", self.DEFAULT_FIELD_ALIASES["store_keys"])
        self.model_keys = aliases.get("model_keys", self.DEFAULT_FIELD_ALIASES["model_keys"])
        self.non_group_ratio_keys = aliases.get("non_group_ratio_keys", self.DEFAULT_FIELD_ALIASES["non_group_ratio_keys"])
        self.ratio_keys = aliases.get("ratio_keys", self.DEFAULT_FIELD_ALIASES["ratio_keys"])
        self.yoy_keys = aliases.get("yoy_keys", self.DEFAULT_FIELD_ALIASES["yoy_keys"])
        self.mom_keys = aliases.get("mom_keys", self.DEFAULT_FIELD_ALIASES["mom_keys"])
        self.amount_keys = aliases.get("amount_keys", self.DEFAULT_FIELD_ALIASES["amount_keys"])
        self.count_keys = aliases.get("count_keys", self.DEFAULT_FIELD_ALIASES["count_keys"])
        self.inventory_keys = aliases.get("inventory_keys", self.DEFAULT_FIELD_ALIASES["inventory_keys"])
        self.sales_keys = aliases.get("sales_keys", self.DEFAULT_FIELD_ALIASES["sales_keys"])
        self.inbound_keys = aliases.get("inbound_keys", self.DEFAULT_FIELD_ALIASES["inbound_keys"])
        self.inbound_ratio_keys = aliases.get("inbound_ratio_keys", self.DEFAULT_FIELD_ALIASES["inbound_ratio_keys"])
        self.future_ratio_keys = aliases.get("future_ratio_keys", self.DEFAULT_FIELD_ALIASES["future_ratio_keys"])
        self.future_sales_keys = aliases.get("future_sales_keys", self.DEFAULT_FIELD_ALIASES["future_sales_keys"])
        self.period_keys = aliases.get("period_keys", self.DEFAULT_FIELD_ALIASES["period_keys"])

    def build_report_facts(self, datasets: list[NormalizedDataset], report_month: str) -> dict[str, Any]:
        by_role = {dataset.role: dataset for dataset in datasets}
        data_quality = self._build_data_quality(datasets)

        inventory_overview = self._build_inventory_overview(by_role, report_month)
        regional_status = self._build_regional_status(by_role)
        purchase_analysis = self._build_purchase_analysis(by_role)
        inventory_overview = self._enrich_inventory_overview(
            inventory_overview=inventory_overview,
            regional_status=regional_status,
            purchase_analysis=purchase_analysis,
        )
        consumption_exceptions = self._build_consumption_exceptions(by_role, report_month)
        stocktake_risks = self._build_stocktake_risks(by_role, report_month)
        ai_insights = self._build_ai_insights(
            report_month=report_month,
            regional_status=regional_status,
            purchase_analysis=purchase_analysis,
            consumption_exceptions=consumption_exceptions,
            stocktake_risks=stocktake_risks,
        )

        highlights = [
            inventory_overview["summary_sentence"],
            regional_status["summary_sentence"],
            purchase_analysis["summary_sentence"],
            consumption_exceptions["summary_sentence"],
            stocktake_risks["summary_sentence"],
            ai_insights["summary_sentence"],
        ]
        highlights.extend(data_quality["warnings"])

        return {
            "report_month": report_month,
            "thresholds": {
                "inventory_green_max": self.thresholds.inventory_green_max,
                "inventory_yellow_max": self.thresholds.inventory_yellow_max,
                "order_anomaly_ratio_min": self.thresholds.order_anomaly_ratio_min,
            },
            "highlights": [item for item in highlights if item],
            "data_quality": data_quality,
            "ai_insights": ai_insights,
            "reference_context": self._build_reference_context(datasets),
            "sections": {
                "inventory_diagnosis": {
                    "title": "纸袋库销诊断",
                    "facts": {
                        "inventory_overview": inventory_overview,
                        "regional_status": regional_status,
                        "purchase_analysis": purchase_analysis,
                    },
                },
                "consumption_exceptions": {
                    "title": "销账异常",
                    "facts": {
                        "consumption_exceptions": consumption_exceptions,
                        "stocktake_risks": stocktake_risks,
                    },
                },
            },
        }

    def _build_data_quality(self, datasets: list[NormalizedDataset]) -> dict[str, Any]:
        statuses = []
        empty_cards = []
        error_cards = []
        warnings = []

        for dataset in datasets:
            application_errors = dataset.summary.get("application_errors", [])
            allow_empty_result = dataset.summary.get("allow_empty_result", False)
            fallback_info = dataset.summary.get("fallback_info")
            is_empty = not dataset.rows and not application_errors and not allow_empty_result
            status_value = (
                "fallback"
                if application_errors and fallback_info
                else "error"
                if application_errors
                else "empty_allowed"
                if not dataset.rows and allow_empty_result
                else "empty"
                if is_empty
                else "ready"
            )
            status = {
                "role": dataset.role,
                "card_id": dataset.card_id,
                "card_name": dataset.card_name,
                "section": dataset.section,
                "row_count": len(dataset.rows),
                "status": status_value,
                "application_errors": application_errors,
                "empty_reason": dataset.summary.get("empty_reason", ""),
                "fallback_info": fallback_info,
            }
            statuses.append(status)
            if is_empty:
                empty_cards.append(status)
            if application_errors and not fallback_info:
                error_cards.append(status)

        if empty_cards:
            warnings.append(f"本期有 {len(empty_cards)} 个数据源返回空数据，部分结论已按可用字段兜底生成。")
        fallback_cards = [item for item in statuses if item["status"] == "fallback"]
        if fallback_cards:
            warnings.append(
                "以下数据源接口异常，但已自动切换为本地卡片集合兜底："
                + "；".join(
                    f"{item['card_name']}({item['card_id']})"
                    for item in fallback_cards[:6]
                )
            )
        if error_cards:
            warnings.append(
                "以下数据源返回了观远应用层错误，且暂无可用兜底："
                + "；".join(
                    f"{item['card_name']}({item['card_id']}) code={item['application_errors'][0]['code']}"
                    for item in error_cards[:4]
                )
            )

        workbook_dataset = next((dataset for dataset in datasets if dataset.role == "purchase_forecast_sheet"), None)
        if workbook_dataset and workbook_dataset.raw_payload.get("workbook_path"):
            warnings.append(f"订购预测已补充读取本地导出表：{workbook_dataset.raw_payload['workbook_path']}")
        expected_empty_cards = [item for item in statuses if item["status"] == "empty_allowed"]
        if expected_empty_cards:
            warnings.append(
                "以下数据源本期为空但属于正常现象："
                + "；".join(
                    f"{item['card_name']}（{item['empty_reason'] or '允许空结果'}）"
                    for item in expected_empty_cards[:4]
                )
            )

        return {
            "dataset_statuses": statuses,
            "empty_cards": empty_cards,
            "error_cards": error_cards,
            "fallback_cards": fallback_cards,
            "warnings": warnings,
        }

    def _build_inventory_overview(self, by_role: dict[str, NormalizedDataset], report_month: str) -> dict[str, Any]:
        dataset = by_role.get("overall_inventory_ratio") or by_role.get("overall_inventory_trend")
        regional_dataset = by_role.get("regional_purchase_evaluation") or by_role.get("regional_inventory_ratio")
        ratio = self._extract_overall_inventory_ratio(dataset, regional_dataset)
        yoy = self._extract_period_delta(dataset, "同比", report_month)
        mom = self._extract_period_delta(dataset, "环比", report_month)
        trend_series = self._extract_trend_series(dataset, report_month)
        yoy_base_ratio = self._derive_compare_base(ratio, yoy)
        mom_base_ratio = self._derive_compare_base(ratio, mom)
        month_start = trend_series[0] if trend_series else None
        month_peak = max(trend_series, key=lambda item: item["ratio"]) if trend_series else None
        status = self._inventory_light(ratio)
        source_name = (
            dataset.card_name
            if dataset and dataset.rows
            else regional_dataset.card_name
            if regional_dataset and regional_dataset.rows
            else "待补充"
        )

        if ratio is None:
            summary_sentence = "公司级库销总览尚未稳定返回，当前先按地区总计口径兜底。"
        elif trend_series and not any(
            self._find_text_value(row, ["区间", "期间"]) in ("本期", "当前", "当期", "同期", "上期")
            for row in (dataset.rows if dataset else [])
        ):
            latest_label = trend_series[-1]["label"]
            summary_sentence = (
                f"{latest_label}公司纸袋库销比为{self._fmt(ratio)}，判定为{status}；"
                f"趋势序列已回收{len(trend_series)}个时点。"
            )
        else:
            summary_sentence = f"公司纸袋库销比为{self._fmt(ratio)}，当前判定为{status}。"

        return {
            "ratio": ratio,
            "yoy": yoy,
            "mom": mom,
            "yoy_base_ratio": yoy_base_ratio,
            "mom_base_ratio": mom_base_ratio,
            "month_start_ratio": month_start["ratio"] if month_start else None,
            "month_start_label": month_start["label"] if month_start else None,
            "month_peak_ratio": month_peak["ratio"] if month_peak else None,
            "month_peak_label": month_peak["label"] if month_peak else None,
            "status": status,
            "source_name": source_name,
            "trend_series": trend_series,
            "summary_sentence": summary_sentence,
        }

    def _build_reference_context(self, datasets: list[NormalizedDataset]) -> dict[str, Any]:
        specs_dataset = next((dataset for dataset in datasets if dataset.role == "paper_bag_specs_reference"), None)
        if specs_dataset is None or not specs_dataset.rows:
            return {}

        specs_rows = []
        for row in specs_dataset.rows:
            specs_rows.append(
                {
                    "paper_bag_model": row.get("纸袋型号") or row.get("规格型号"),
                    "paper_bag_code": row.get("纸袋编码"),
                    "display_name": row.get("规格型号"),
                    "size_mm": row.get("型号(mm)"),
                    "usage_scenes": row.get("使用场景"),
                    "usage_frequency": row.get("使用频率"),
                }
            )

        return {
            "inventory_diagnosis": {
                "paper_bag_specs": specs_rows,
                "paper_bag_specs_note": (
                    "规格参考用于辅助判断XS/S/M/L/XL的合理使用场景。"
                    "若使用端主要集中在较小型号，不应直接判断为浪费；"
                    "只有在明显偏大型号替代较小型号使用时，才优先判断为使用浪费。"
                ),
            }
        }

    def _extract_overall_inventory_ratio(
        self,
        overall_dataset: NormalizedDataset | None,
        regional_dataset: NormalizedDataset | None,
    ) -> float | None:
        if overall_dataset:
            has_interval_rows = any(
                self._find_text_value(row, ["区间", "期间"]) is not None
                for row in overall_dataset.rows
            )
            trend_series = self._extract_trend_series(overall_dataset)
            if trend_series and not has_interval_rows:
                return trend_series[-1]["ratio"]

            for row in overall_dataset.rows:
                ratio = self._derive_ratio(row)
                interval = self._find_text_value(row, ["区间", "期间"])
                if ratio is not None and interval in ("本期", "当前", "当期"):
                    return ratio

            for row in overall_dataset.rows:
                ratio = self._derive_ratio(row)
                interval = self._find_text_value(row, ["区间", "期间"])
                if ratio is not None and interval is None:
                    return ratio

            if trend_series:
                return trend_series[-1]["ratio"]

            for row in overall_dataset.rows:
                ratio = self._derive_ratio(row)
                if ratio is not None:
                    return ratio

        if regional_dataset:
            total_row = next(
                (
                    row
                    for row in regional_dataset.rows
                    if (region := self._find_text_value(row, self.region_keys)) is not None and self._is_total_region(region)
                ),
                None,
            )
            if total_row:
                ratio = self._derive_ratio(total_row)
                if ratio is not None:
                    return ratio
            aggregated_ratio = self._aggregate_regional_ratio(regional_dataset.rows)
            if aggregated_ratio is not None:
                return aggregated_ratio

        return None

    def _extract_period_delta(self, dataset: NormalizedDataset | None, mode: str, report_month: str | None = None) -> float | None:
        if not dataset:
            return None

        direct_value = self._first_numeric_value(dataset.rows, self.yoy_keys if mode == "同比" else self.mom_keys)
        if direct_value is not None:
            return direct_value

        current_row = next(
            (
                row
                for row in dataset.rows
                if self._find_text_value(row, ["区间", "期间"]) in ("本期", "当前", "当期")
            ),
            None,
        )
        compare_row = next(
            (
                row
                for row in dataset.rows
                if self._find_text_value(row, ["区间", "期间"]) in ("同期", "上期")
            ),
            None,
        )
        if current_row and compare_row:
            current_ratio = self._derive_ratio(current_row)
            compare_ratio = self._derive_ratio(compare_row)
            if current_ratio is not None and compare_ratio not in (None, 0):
                return (current_ratio - compare_ratio) / compare_ratio

        if dataset.role == "overall_inventory_trend":
            return self._extract_trend_period_delta(dataset.rows, mode, report_month)

        series = self._extract_trend_series(dataset, report_month)
        if len(series) >= 2 and series[-2]["ratio"] not in (None, 0):
            return (series[-1]["ratio"] - series[-2]["ratio"]) / series[-2]["ratio"]
        return None

    def _extract_trend_series(self, dataset: NormalizedDataset | None, report_month: str | None = None) -> list[dict[str, Any]]:
        if dataset is None:
            return []

        series: list[dict[str, Any]] = []
        seen_labels: set[str] = set()
        for row in dataset.rows:
            fiscal_year, ratio, compare_ratio = self._extract_fiscal_metric_pair(row, "库销比")
            if ratio is None:
                ratio = self._derive_ratio(row)
            label = self._extract_period_label(row)
            if ratio is None or label is None or label in seen_labels:
                continue
            seen_labels.add(label)
            inventory_qty = None
            if fiscal_year is not None:
                inventory_qty = self._extract_fiscal_metric_value(row, "纸袋业务存量", fiscal_year)
            if inventory_qty is None:
                inventory_qty = self._find_numeric_value(row, ["纸袋业务存量", "业务存量"] + self.inventory_keys)
            series.append(
                {
                    "label": label,
                    "ratio": ratio,
                    "inventory_qty": inventory_qty,
                    "compare_ratio": compare_ratio,
                }
            )
        series.sort(key=lambda item: self._period_sort_key(item["label"]))
        if report_month and dataset.role == "overall_inventory_trend":
            filtered = [item for item in series if item["label"].startswith(report_month)]
            return filtered or series
        return series

    def _extract_trend_period_delta(
        self,
        rows: list[dict[str, Any]],
        mode: str,
        report_month: str | None,
    ) -> float | None:
        if not rows or not report_month:
            return None

        labeled_rows: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            label = self._extract_period_label(row)
            if label is None:
                continue
            labeled_rows.append((label, row))

        labeled_rows.sort(key=lambda item: self._period_sort_key(item[0]))
        current_rows = [(label, row) for label, row in labeled_rows if label.startswith(report_month)]
        if not current_rows:
            return None

        _current_label, current_row = current_rows[-1]
        _fiscal_year, current_ratio, compare_ratio = self._extract_fiscal_metric_pair(current_row, "库销比")
        if current_ratio is None:
            current_ratio = self._derive_ratio(current_row)
        if current_ratio in (None, 0):
            return None

        if mode == "同比":
            if compare_ratio in (None, 0):
                return None
            return (current_ratio - compare_ratio) / compare_ratio

        previous_rows = [
            (label, row)
            for label, row in labeled_rows
            if not label.startswith(report_month)
        ]
        if not previous_rows:
            return None
        previous_rows.sort(key=lambda item: self._period_sort_key(item[0]))
        _previous_label, previous_row = previous_rows[-1]
        _previous_fiscal_year, compare_ratio, _previous_compare_ratio = self._extract_fiscal_metric_pair(previous_row, "库销比")
        if compare_ratio is None:
            compare_ratio = self._derive_ratio(previous_row)
        if compare_ratio in (None, 0):
            return None
        return (current_ratio - compare_ratio) / compare_ratio

    def _extract_fiscal_metric_pair(
        self,
        row: dict[str, Any],
        metric_suffix: str,
    ) -> tuple[int | None, float | None, float | None]:
        metric_map = self._extract_fiscal_metric_map(row, metric_suffix)
        if not metric_map:
            return None, None, None

        current_year = max(metric_map)
        current_value = metric_map.get(current_year)
        compare_candidates = [year for year in metric_map if year < current_year]
        compare_value = metric_map.get(max(compare_candidates)) if compare_candidates else None
        return current_year, current_value, compare_value

    def _extract_fiscal_metric_value(
        self,
        row: dict[str, Any],
        metric_suffix: str,
        fiscal_year: int,
    ) -> float | None:
        return self._extract_fiscal_metric_map(row, metric_suffix).get(fiscal_year)

    def _extract_fiscal_metric_map(self, row: dict[str, Any], metric_suffix: str) -> dict[int, float]:
        metric_map: dict[int, float] = {}
        pattern = re.compile(r"FY(\d{2,4})")
        for candidate_key, value in row.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            key = str(candidate_key).strip()
            if metric_suffix not in key:
                continue
            match = pattern.search(key)
            if match is None:
                continue
            fiscal_year = int(match.group(1)[-2:])
            metric_map[fiscal_year] = float(value)
        return metric_map

    def _build_regional_status(self, by_role: dict[str, NormalizedDataset]) -> dict[str, Any]:
        dataset = by_role.get("regional_inventory_ratio")
        regional_rows: list[dict[str, Any]] = []

        if dataset:
            for row in dataset.rows:
                region = self._find_text_value(row, self.region_keys)
                ratio = self._derive_ratio(row)
                if region is None or ratio is None or self._is_total_region(region):
                    continue

                regional_rows.append(
                    {
                        "region": region,
                        "ratio": ratio,
                        "inventory_qty": self._find_numeric_value(row, self.inventory_keys),
                        "sales_qty": self._find_numeric_value(row, self.sales_keys),
                        "inbound_qty": self._find_numeric_value(row, self.inbound_keys),
                        "inbound_ratio": self._find_numeric_value(row, self.inbound_ratio_keys),
                        "status": self._inventory_light(ratio),
                    }
                )

        regional_rows.sort(key=lambda item: item["ratio"], reverse=True)
        red_count = sum(1 for item in regional_rows if item["status"] == "红灯")
        yellow_count = sum(1 for item in regional_rows if item["status"] == "黄灯")
        green_count = sum(1 for item in regional_rows if item["status"] == "绿灯")

        summary_sentence = self._build_regional_status_summary(
            red_count=red_count,
            yellow_count=yellow_count,
            green_count=green_count,
            total_count=len(regional_rows),
        )
        return {
            "regional_rows": regional_rows,
            "red_count": red_count,
            "yellow_count": yellow_count,
            "green_count": green_count,
            "summary_sentence": summary_sentence,
        }

    def _build_purchase_analysis(self, by_role: dict[str, NormalizedDataset]) -> dict[str, Any]:
        regional_dataset = by_role.get("regional_purchase_evaluation") or by_role.get("regional_inventory_ratio")
        regional_model_dataset = by_role.get("regional_model_purchase_analysis") or by_role.get("regional_purchase_evaluation")
        forecast_dataset = (
            by_role.get("purchase_forecast_sheet")
            or by_role.get("purchase_forecast_api")
            or by_role.get("purchase_forecast")
        )
        regional_model_rows = self._extract_regional_model_rows(regional_model_dataset)
        forecast_rows = self._extract_forecast_rows(forecast_dataset)

        purchase_joined_rows, strict_report_rows = self._build_purchase_report_rows(regional_model_rows, forecast_rows)

        region_evaluation_map: dict[str, dict[str, Any]] = {}
        if regional_dataset:
            for row in regional_dataset.rows:
                region = self._find_text_value(row, self.region_keys)
                ratio = self._derive_ratio(row)
                inventory_qty = self._find_numeric_value(row, self.inventory_keys)
                inbound_qty = self._find_numeric_value(row, self.inbound_keys)
                sales_qty = self._find_numeric_value(row, self.sales_keys)
                if not region or self._is_total_region(region):
                    continue
                region_evaluation_map[region] = {
                    "region": region,
                    "ratio": ratio,
                    "inventory_qty": inventory_qty,
                    "inbound_qty": inbound_qty,
                    "sales_qty": sales_qty,
                    "inbound_ratio": self._find_numeric_value(row, self.inbound_ratio_keys),
                    "raw": row,
                }

        regional_model_map = {
            (row["region"], row["model"]): row
            for row in regional_model_rows
        }

        history_evaluations: list[dict[str, Any]] = []
        for forecast_row in forecast_rows:
            region = forecast_row["region"]
            model = forecast_row["model"]
            model_snapshot = regional_model_map.get((region, model))
            region_snapshot = region_evaluation_map.get(region)
            if model_snapshot is None and region_snapshot is not None:
                model_snapshot = {
                    "region": region,
                    "model": model,
                    "sales_qty": region_snapshot.get("sales_qty"),
                    "inventory_qty": forecast_row.get("current_inventory"),
                    "ratio": forecast_row.get("current_ratio") or region_snapshot.get("ratio"),
                    "inbound_qty": region_snapshot.get("inbound_qty"),
                    "inbound_ratio": region_snapshot.get("inbound_ratio"),
                    "raw": region_snapshot.get("raw", {}),
                }
            if model_snapshot is None:
                continue

            current_inventory = model_snapshot.get("inventory_qty") or forecast_row["current_inventory"]
            current_ratio = model_snapshot.get("ratio") or forecast_row["current_ratio"]
            future_ratio = forecast_row["future_ratio"]
            future_usage = forecast_row["future_usage"]
            inbound_qty = model_snapshot.get("inbound_qty")
            if inbound_qty is None and region_snapshot is not None:
                inbound_qty = region_snapshot["inbound_qty"]
            inbound_ratio = model_snapshot.get("inbound_ratio")
            if inbound_ratio is None and region_snapshot is not None:
                inbound_ratio = region_snapshot.get("inbound_ratio")
            has_inventory_pressure = (
                current_ratio > self.thresholds.inventory_green_max
                or future_ratio >= self.thresholds.purchase_excess_max
            )
            if (
                current_inventory is None
                or current_ratio is None
                or future_ratio is None
                or future_usage is None
                or current_inventory <= self.thresholds.purchase_inventory_min
                or not has_inventory_pressure
                or (inbound_qty or 0) <= self.thresholds.purchase_inbound_min
            ):
                continue

            risk_score = (
                min(future_ratio, 20.0) * 0.5
                + min(current_ratio, 10.0) * 0.3
                + min(current_inventory / 10000, 10.0) * 0.2
            )
            opening_ratio = current_ratio - inbound_ratio if inbound_ratio is not None else None
            if inbound_ratio is not None and inbound_ratio >= 2:
                purchase_risk_level = "P1"
            elif inbound_ratio is not None and inbound_ratio <= 1:
                purchase_risk_level = "P2"
            else:
                purchase_risk_level = self._classify_purchase_history_risk_level(
                    opening_ratio=opening_ratio,
                    ending_ratio=current_ratio,
                    inbound_ratio=inbound_ratio,
                )
            if purchase_risk_level == "P1":
                diagnosis = "高库销高进销-月度多订"
                decision_comment = "当前库销比处于高位且进销比偏高，新增入库仍快于消化节奏，本月订购量判断为偏多，订购恰当性不足。"
                inbound_scenario = "高库销高进销"
                risk_score += 2.0
            elif purchase_risk_level == "P2":
                diagnosis = "高库销低进销-持续积压"
                decision_comment = "当前库销比仍处高位但进销比不高，说明历史积压尚未消化，后续应去库存为先并控制新增订购。"
                inbound_scenario = "高库销低进销"
                risk_score += 1.0
            elif purchase_risk_level == "P3":
                diagnosis = "P3关注-期末库存转黄"
                decision_comment = "本期有厂入且期末进入黄灯，需跟踪消化节奏，优先级低于P1/P2。"
                inbound_scenario = "关注跟踪"
                risk_score += 0.4
            elif future_ratio >= 6:
                diagnosis = "高库存高风险"
                decision_comment = "预测口径下次月库存仍显著偏高，需复核本月订购合理性。"
                inbound_scenario = "高库销待复核"
            elif future_ratio >= self.thresholds.purchase_excess_max:
                diagnosis = "库存偏高待复核"
                decision_comment = "当前库存已偏高，需结合地区厂入节奏继续复核订购策略。"
                inbound_scenario = "高库销待复核"
            else:
                diagnosis = "库存偏高待复核"
                decision_comment = "当前库存偏高，建议持续跟踪未来30天消化节奏。"
                inbound_scenario = "高库销待复核"

            target_inventory_qty = future_usage * (1 + self.thresholds.purchase_future_ratio_min)
            excess_inventory_qty = max(current_inventory - target_inventory_qty, 0.0)
            history_evaluations.append(
                {
                    "region": region,
                    "model": model,
                    "ratio": current_ratio,
                    "future_ratio": future_ratio,
                    "future_usage": future_usage,
                    "same_period_sales_qty": forecast_row.get("same_period_sales_qty"),
                    "opening_ratio": opening_ratio,
                    "purchase_risk_level": purchase_risk_level,
                    "sales_qty": model_snapshot.get("sales_qty") or (region_snapshot["sales_qty"] if region_snapshot else None),
                    "regional_sales_qty": region_snapshot["sales_qty"] if region_snapshot else model_snapshot.get("sales_qty"),
                    "inventory_qty": current_inventory,
                    "inbound_qty": inbound_qty,
                    "inbound_ratio": inbound_ratio,
                    "regional_ratio": region_snapshot["ratio"] if region_snapshot else current_ratio,
                    "risk_score": risk_score,
                    "diagnosis": diagnosis,
                    "decision_comment": decision_comment,
                    "inbound_scenario": inbound_scenario,
                    "regional_inventory_qty": region_snapshot["inventory_qty"] if region_snapshot else current_inventory,
                    "target_inventory_qty": target_inventory_qty,
                    "excess_inventory_qty": excess_inventory_qty,
                    "status": "订购偏多风险",
                    "raw": {
                        "regional_model": model_snapshot.get("raw", {}),
                        "forecast": forecast_row.get("raw", {}),
                        "regional": region_snapshot.get("raw", {}) if region_snapshot else {},
                    },
                }
            )

        history_evaluations.sort(
            key=lambda item: (
                self._purchase_history_priority(item.get("purchase_risk_level")),
                item["risk_score"],
                item["future_ratio"],
                item["ratio"],
            ),
            reverse=True,
        )
        future_demand_gaps = self._build_future_demand_gaps(forecast_rows)
        model_focus = self._summarize_model_focus(history_evaluations, future_demand_gaps)
        model_inventory_profile = self._build_model_inventory_profile(regional_model_rows)
        high_inventory_high_inbound_count = sum(
            1 for item in history_evaluations if item.get("purchase_risk_level") == "P1"
        )
        high_inventory_low_inbound_count = sum(
            1 for item in history_evaluations if item.get("purchase_risk_level") == "P2"
        )
        model_structure_mismatch_count = sum(
            1
            for item in model_inventory_profile["analysis_rows"]
            if item.get("structure_label") in {"库存偏小码积压", "库存偏大码积压", "使用偏大尺码"}
        )

        if history_evaluations or future_demand_gaps:
            summary_sentence = (
                f"历史订购评价识别出{len(history_evaluations)}个高库销订购关注组合，"
                f"其中P1高风险{high_inventory_high_inbound_count}个、"
                f"P2中风险{high_inventory_low_inbound_count}个；"
                f"{len(future_demand_gaps)}个地区型号存在次月需求缺口。"
            )
        elif forecast_dataset is not None and not forecast_dataset.rows:
            summary_sentence = "订购预测数据源当前为空，暂无法完成未来30天需求与历史订购联动评价。"
        else:
            summary_sentence = "订购评价模块已切换到“地区库存+未来30天预测”联动逻辑。"

        return {
            "history_evaluations": history_evaluations[:20],
            "joined_rows": purchase_joined_rows[:30],
            "report_rows": strict_report_rows[:20],
            "future_demand_gaps": future_demand_gaps[:30],
            "model_focus": model_focus,
            "model_inventory_models": model_inventory_profile["models"],
            "model_inventory_pivot": model_inventory_profile["pivot_rows"],
            "model_inventory_share_rows": model_inventory_profile["share_rows"],
            "model_usage_pivot": model_inventory_profile["usage_pivot_rows"],
            "model_usage_share_rows": model_inventory_profile["usage_share_rows"],
            "model_inventory_analysis": model_inventory_profile["analysis_rows"],
            "high_inventory_high_inbound_count": high_inventory_high_inbound_count,
            "high_inventory_low_inbound_count": high_inventory_low_inbound_count,
            "model_structure_mismatch_count": model_structure_mismatch_count,
            "forecast_source": self._describe_dataset_source(forecast_dataset),
            "summary_sentence": summary_sentence,
        }

    def _extract_regional_model_rows(self, dataset: NormalizedDataset | None) -> list[dict[str, Any]]:
        if dataset is None:
            return []

        rows: list[dict[str, Any]] = []
        for row in dataset.rows:
            region = self._find_text_value(row, self.region_keys)
            model = self._find_text_value(row, self.model_keys)
            if (
                not region
                or not model
                or self._is_total_region(region)
                or self._is_total_model(model)
            ):
                continue
            rows.append(
                {
                    "region": region,
                    "model": model,
                    "sales_qty": self._find_numeric_value(row, self.sales_keys),
                    "inventory_qty": self._find_numeric_value(row, self.inventory_keys),
                    "ratio": self._derive_ratio(row),
                    "inbound_qty": self._find_numeric_value(row, self.inbound_keys),
                    "inbound_ratio": self._find_numeric_value(row, self.inbound_ratio_keys),
                    "raw": row,
                }
            )

        rows.sort(
            key=lambda item: (
                item["region"],
                self._model_sort_key(item["model"]),
                -(item.get("inventory_qty") or 0),
            )
        )
        return rows

    def _build_purchase_report_rows(
        self,
        regional_model_rows: list[dict[str, Any]],
        forecast_rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        forecast_map = {
            (row.get("region"), row.get("model")): row
            for row in forecast_rows
            if row.get("region") and row.get("model")
        }
        joined_rows: list[dict[str, Any]] = []
        filtered_rows: list[dict[str, Any]] = []
        for row in regional_model_rows:
            key = (row.get("region"), row.get("model"))
            forecast_row = forecast_map.get(key)
            if forecast_row is None:
                continue
            inventory_qty = row.get("inventory_qty")
            ratio = row.get("ratio")
            inbound_qty = row.get("inbound_qty")
            future_ratio = forecast_row.get("future_ratio")
            joined_row = {
                "region": row.get("region"),
                "model": row.get("model"),
                "sales_qty": row.get("sales_qty"),
                "inventory_qty": inventory_qty,
                "ratio": ratio,
                "inbound_qty": inbound_qty,
                "inbound_ratio": row.get("inbound_ratio"),
                "same_period_sales_qty": forecast_row.get("same_period_sales_qty"),
                "future_usage": forecast_row.get("future_usage"),
                "future_ratio": future_ratio,
                "raw": {
                    "regional_model": row.get("raw", {}),
                    "forecast": forecast_row.get("raw", {}),
                },
            }
            joined_rows.append(joined_row)
            if (
                inventory_qty is None
                or ratio is None
                or inbound_qty is None
                or row.get("inbound_ratio") is None
                or future_ratio is None
                or inventory_qty <= self.thresholds.purchase_inventory_min
                or ratio <= self.thresholds.inventory_green_max
                or inbound_qty <= 0
            ):
                continue
            filtered_rows.append(joined_row)
        joined_rows.sort(
            key=lambda item: (
                item.get("region") or "",
                item.get("model") or "",
            ),
        )
        filtered_rows.sort(
            key=lambda item: (
                item.get("future_ratio") or 0,
                item.get("ratio") or 0,
                item.get("inventory_qty") or 0,
            ),
            reverse=True,
        )
        return joined_rows, filtered_rows

    def _build_model_inventory_profile(self, regional_model_rows: list[dict[str, Any]]) -> dict[str, Any]:
        filtered_rows = [
            row
            for row in regional_model_rows
            if row.get("inventory_qty") is not None and row["inventory_qty"] > self.thresholds.purchase_inventory_min
        ]
        if not filtered_rows:
            return {
                "models": [],
                "pivot_rows": [],
                "share_rows": [],
                "usage_pivot_rows": [],
                "usage_share_rows": [],
                "analysis_rows": [],
            }

        model_set = {row["model"] for row in filtered_rows}
        models = sorted(model_set, key=self._model_sort_key)
        region_map: dict[str, dict[str, Any]] = {}
        for row in filtered_rows:
            entry = region_map.setdefault(
                row["region"],
                {
                    "region": row["region"],
                    "model_quantities": {model: 0.0 for model in models},
                    "model_sales_qty": {model: 0.0 for model in models},
                    "total_inventory_qty": 0.0,
                    "total_sales_qty": 0.0,
                },
            )
            inventory_qty = float(row.get("inventory_qty") or 0.0)
            sales_qty = float(row.get("sales_qty") or 0.0)
            entry["model_quantities"][row["model"]] = entry["model_quantities"].get(row["model"], 0.0) + inventory_qty
            entry["model_sales_qty"][row["model"]] = entry["model_sales_qty"].get(row["model"], 0.0) + sales_qty
            entry["total_inventory_qty"] += inventory_qty
            entry["total_sales_qty"] += sales_qty

        pivot_rows: list[dict[str, Any]] = []
        share_rows: list[dict[str, Any]] = []
        usage_pivot_rows: list[dict[str, Any]] = []
        usage_share_rows: list[dict[str, Any]] = []
        analysis_rows: list[dict[str, Any]] = []
        for entry in sorted(region_map.values(), key=lambda item: item["total_inventory_qty"], reverse=True):
            total_inventory_qty = entry["total_inventory_qty"]
            total_sales_qty = entry["total_sales_qty"]
            model_shares = {
                model: (qty / total_inventory_qty if total_inventory_qty > 0 else None)
                for model, qty in entry["model_quantities"].items()
            }
            usage_shares = {
                model: (qty / total_sales_qty if total_sales_qty > 0 else None)
                for model, qty in entry["model_sales_qty"].items()
            }
            sorted_shares = sorted(
                (
                    (model, share)
                    for model, share in model_shares.items()
                    if share is not None
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            sorted_usage_shares = sorted(
                (
                    (model, share)
                    for model, share in usage_shares.items()
                    if share is not None
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            top_model = sorted_shares[0][0] if sorted_shares else None
            top_share = sorted_shares[0][1] if sorted_shares else None
            secondary_model = sorted_shares[1][0] if len(sorted_shares) > 1 else None
            usage_top_model = sorted_usage_shares[0][0] if sorted_usage_shares else None
            usage_top_share = sorted_usage_shares[0][1] if sorted_usage_shares else None
            large_models = {"滔搏纸袋-L", "滔搏纸袋-XL"}
            usage_large_share = sum(usage_shares.get(model) or 0 for model in models if model in large_models)
            inventory_large_share = sum(model_shares.get(model) or 0 for model in models if model in large_models)
            inventory_top_usage_share = usage_shares.get(top_model) if top_model else None
            usage_top_inventory_share = model_shares.get(usage_top_model) if usage_top_model else None
            share_gap = (
                abs((top_share or 0) - (usage_top_share or 0))
                if top_share is not None and usage_top_share is not None
                else None
            )
            if top_model and usage_top_model and top_model != usage_top_model:
                mismatch_gaps = [
                    (usage_top_share or 0) - (usage_top_inventory_share or 0),
                    (top_share or 0) - (inventory_top_usage_share or 0),
                ]
                structure_gap = max((gap for gap in mismatch_gaps if gap > 0), default=share_gap)
            else:
                structure_gap = share_gap
            structure_gap_pp = structure_gap * 100 if structure_gap is not None else None
            if top_share is None or usage_top_share is None:
                structure_label = "结构待补充"
                waste_risk = False
                structure_comment = "库存结构待补充。"
                suggestion = "继续跟踪各型号库存结构。"
            elif usage_top_model in large_models and usage_top_share >= 0.35 and usage_large_share >= inventory_large_share + 0.10:
                structure_label = "使用偏大尺码"
                waste_risk = True
                structure_comment = (
                    f"使用端{usage_top_model}占比{usage_top_share:.1%}，偏大尺码用量偏高；"
                    f"大尺码使用占比{usage_large_share:.1%}高于库存端{inventory_large_share:.1%}。"
                )
                suggestion = (
                    f"围绕使用主力{usage_top_model}与库存主力{top_model}复核订购结构，"
                    f"两端主力占比差异{structure_gap_pp:.1f}个百分点；如需关注其他型号，需在补充说明中单独列明依据。"
                )
            elif (
                top_model
                and usage_top_model
                and top_model != usage_top_model
                and (
                    (usage_top_share or 0) - (usage_top_inventory_share or 0) >= 0.15
                    or (top_share or 0) - (inventory_top_usage_share or 0) >= 0.15
                )
            ):
                waste_risk = False
                if self._model_rank(top_model) < self._model_rank(usage_top_model):
                    structure_label = "库存偏小码积压"
                    structure_comment = (
                        f"使用端{usage_top_model}占比{usage_top_share:.1%}，但库存端{top_model}占比{top_share:.1%}，"
                        "库存结构偏小码，与实际使用需求存在错配。"
                    )
                    suggestion = (
                        f"减少{top_model}等偏小尺码订购，优先补齐或转配{usage_top_model}需求；"
                        f"两端主力占比差异{structure_gap_pp:.1f}个百分点，小纸袋使用更多不视为浪费，应优先纠正库存结构。"
                    )
                else:
                    structure_label = "库存偏大码积压"
                    structure_comment = (
                        f"库存端{top_model}占比{top_share:.1%}，明显高于使用端{inventory_top_usage_share or 0:.1%}；"
                        f"当前使用端以{usage_top_model}为主，占比{usage_top_share:.1%}。"
                    )
                    suggestion = (
                        f"优先消化{top_model}库存并回看{usage_top_model}需求结构，"
                        f"两端主力占比差异{structure_gap_pp:.1f}个百分点，避免偏大尺码继续积压。"
                    )
            elif top_model == usage_top_model and top_share >= 0.55 and share_gap is not None and share_gap <= 0.12:
                structure_label = "结构集中但基本匹配"
                waste_risk = False
                structure_comment = (
                    f"库存端与使用端均以{top_model}为主，库存占比{top_share:.1%}、"
                    f"使用占比{usage_top_share:.1%}，结构虽集中但与实际需求基本一致。"
                )
                suggestion = (
                    f"库存主力与使用主力均为{top_model}，两端主力占比差异{structure_gap_pp:.1f}个百分点；"
                    f"围绕{top_model}复核订购集中度并持续跟踪。"
                )
            elif top_share >= 0.45:
                structure_label = "结构集中待跟踪"
                waste_risk = False
                structure_comment = (
                    f"库存端{top_model}占比{top_share:.1%}，库存以单一型号为主；"
                    f"使用端{usage_top_model}占比{usage_top_share:.1%}。"
                )
                if top_model == usage_top_model:
                    suggestion = (
                        f"库存主力与使用主力均为{top_model}，两端主力占比差异{structure_gap_pp:.1f}个百分点；"
                        f"围绕{top_model}复核订购集中度并持续跟踪。"
                    )
                else:
                    suggestion = (
                        f"围绕库存主力{top_model}与使用主力{usage_top_model}复核订购结构，"
                        f"两端主力占比差异{structure_gap_pp:.1f}个百分点；如需关注其他型号，需在补充说明中单独列明依据。"
                    )
            else:
                structure_label = "结构相对均衡"
                waste_risk = False
                structure_comment = (
                    f"使用端{usage_top_model}占比{usage_top_share:.1%}，库存端{top_model}占比{top_share:.1%}，"
                    "库存与使用结构目前基本匹配。"
                )
                suggestion = "保持现有结构，同时持续跟踪大尺码型号的使用占比，防止订购与使用逐步偏移。"

            pivot_rows.append(
                {
                    "region": entry["region"],
                    "model_quantities": entry["model_quantities"],
                    "total_inventory_qty": total_inventory_qty,
                }
            )
            share_rows.append(
                {
                    "region": entry["region"],
                    "model_shares": model_shares,
                    "total_inventory_qty": total_inventory_qty,
                }
            )
            usage_pivot_rows.append(
                {
                    "region": entry["region"],
                    "model_sales_qty": entry["model_sales_qty"],
                    "total_sales_qty": total_sales_qty,
                }
            )
            usage_share_rows.append(
                {
                    "region": entry["region"],
                    "model_shares": usage_shares,
                    "total_sales_qty": total_sales_qty,
                }
            )
            analysis_rows.append(
                {
                    "region": entry["region"],
                    "top_model": top_model,
                    "top_share": top_share,
                    "secondary_model": secondary_model,
                    "usage_top_model": usage_top_model,
                    "usage_top_share": usage_top_share,
                    "usage_large_share": usage_large_share,
                    "inventory_large_share": inventory_large_share,
                    "inventory_top_usage_share": inventory_top_usage_share,
                    "usage_top_inventory_share": usage_top_inventory_share,
                    "structure_label": structure_label,
                    "structure_gap_pp": structure_gap_pp,
                    "waste_risk": waste_risk,
                    "structure_comment": structure_comment,
                    "suggestion": suggestion,
                }
            )

        return {
            "models": models,
            "pivot_rows": pivot_rows,
            "share_rows": share_rows,
            "usage_pivot_rows": usage_pivot_rows,
            "usage_share_rows": usage_share_rows,
            "analysis_rows": analysis_rows,
        }

    def _enrich_inventory_overview(
        self,
        inventory_overview: dict[str, Any],
        regional_status: dict[str, Any],
        purchase_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        trend_summary = self._summarize_inventory_plateau(inventory_overview.get("trend_series", []))
        blocking_reasons: list[str] = []

        regional_rows = regional_status.get("regional_rows", [])
        region_reason = self._build_regional_blocking_reason(regional_rows)
        if region_reason:
            blocking_reasons.append(region_reason)

        history_evaluations = purchase_analysis.get("history_evaluations", [])
        high_inbound_reason = self._build_purchase_blocking_reason(history_evaluations, "P1")
        if high_inbound_reason:
            blocking_reasons.append(high_inbound_reason)
        low_inbound_reason = self._build_purchase_blocking_reason(history_evaluations, "P2")
        if low_inbound_reason:
            blocking_reasons.append(low_inbound_reason)

        structure_reason = self._build_structure_blocking_reason(
            purchase_analysis.get("model_inventory_analysis", [])
        )
        if structure_reason:
            blocking_reasons.append(structure_reason)

        if not blocking_reasons:
            blocking_reasons.append("当前未识别到单一主导制约项，后续仍需持续校正地区去化节奏、订购动作与型号结构。")

        return {
            **inventory_overview,
            "plateau_summary": trend_summary,
            "plateau_summary_sentence": trend_summary.get("sentence", inventory_overview.get("summary_sentence", "")),
            "blocking_reasons": blocking_reasons,
        }

    def _summarize_inventory_plateau(self, trend_series: list[dict[str, Any]]) -> dict[str, Any]:
        valid_rows = [item for item in trend_series if item.get("ratio") is not None]
        if not valid_rows:
            return {
                "anchor_ratio": None,
                "streak_count": 0,
                "start_label": None,
                "end_label": None,
                "range_min": None,
                "range_max": None,
                "sentence": "趋势数据不足，暂无法判断公司纸袋库销比的阶段性变化特征。",
            }

        first = valid_rows[0]
        latest = valid_rows[-1]
        anchor_ratio = round(float(latest["ratio"]), 1)
        tolerance = max(0.15, min(0.30, max(anchor_ratio, 1.0) * 0.08))
        streak_rows: list[dict[str, Any]] = []
        for item in reversed(valid_rows):
            ratio = item.get("ratio")
            if ratio is None or abs(float(ratio) - anchor_ratio) > tolerance:
                break
            streak_rows.append(item)
        streak_rows.reverse()

        range_values = [float(item["ratio"]) for item in streak_rows if item.get("ratio") is not None]
        overall_range_values = [float(item["ratio"]) for item in valid_rows]
        start_label = streak_rows[0]["label"] if streak_rows else latest["label"]
        end_label = streak_rows[-1]["label"] if streak_rows else latest["label"]
        streak_count = len(streak_rows) if streak_rows else 1
        unit_label = self._trend_streak_unit_label([str(item.get("label", "")) for item in streak_rows or [latest]])
        first_ratio = float(first["ratio"])
        latest_ratio = float(latest["ratio"])
        delta = latest_ratio - first_ratio

        if abs(delta) < 0.05:
            delta_phrase = f"较{first['label']}基本持平"
        elif delta < 0:
            delta_phrase = f"较{first['label']}回落{abs(delta):.2f}"
        else:
            delta_phrase = f"较{first['label']}上升{abs(delta):.2f}"

        if streak_count >= 2 and range_values:
            if latest_ratio > 2:
                tail_sentence = (
                    f"其中{start_label}至{end_label}连续{streak_count}{unit_label}在"
                    f"{min(range_values):.2f}-{max(range_values):.2f}区间窄幅波动，月末已进入高位横盘，"
                    "说明前期去库存改善在放缓，尚未形成继续向目标值2回落的趋势。"
                )
            else:
                tail_sentence = (
                    f"其中{start_label}至{end_label}连续{streak_count}{unit_label}稳定在"
                    f"{min(range_values):.2f}-{max(range_values):.2f}区间，库存周转已基本回到目标附近。"
                )
            sentence = (
                f"本月公司纸袋库销比在{first['label']}至{latest['label']}间运行于"
                f"{min(overall_range_values):.2f}-{max(overall_range_values):.2f}区间，最新值为{latest_ratio:.2f}，"
                f"{delta_phrase}；{tail_sentence}"
            )
        elif latest_ratio > 2:
            sentence = (
                f"最新公司纸袋库销比为{latest_ratio:.2f}，{delta_phrase}，当前仍高于目标值2，库存周转压力仍需继续消化。"
            )
        else:
            sentence = f"最新公司纸袋库销比为{latest_ratio:.2f}，{delta_phrase}，当前已基本回到目标区间。"

        return {
            "anchor_ratio": anchor_ratio,
            "tolerance": tolerance,
            "streak_count": streak_count,
            "start_label": start_label,
            "end_label": end_label,
            "range_min": min(range_values) if range_values else None,
            "range_max": max(range_values) if range_values else None,
            "sentence": sentence,
        }

    def _trend_streak_unit_label(self, labels: list[str]) -> str:
        normalized = [str(label).strip() for label in labels if str(label).strip()]
        if normalized and all(len(label.replace("/", "-")) == 7 for label in normalized):
            return "个月"
        if normalized and all(len(label.replace("/", "-")) == 10 for label in normalized):
            return "个监控时点"
        return "个时点"

    def _build_regional_status_summary(
        self,
        *,
        red_count: int,
        yellow_count: int,
        green_count: int,
        total_count: int,
    ) -> str:
        if total_count == 0:
            return "地区库销明细尚未形成稳定结果。"
        if red_count == 0 and yellow_count == 0:
            return f"地区分层结果显示，{total_count}个地区已全部进入绿灯。"
        if red_count == 0:
            if green_count:
                return f"地区分层结果显示，{yellow_count}个地区处于黄灯，其余{green_count}个地区已进入绿灯。"
            return f"地区分层结果显示，{yellow_count}个地区处于黄灯。"
        if yellow_count == 0:
            if green_count:
                return f"地区分层结果显示，{red_count}个地区仍处红灯，其余{green_count}个地区已进入绿灯。"
            return f"地区分层结果显示，{red_count}个地区仍处红灯。"
        if green_count:
            return f"地区分层结果显示，红灯{red_count}个、黄灯{yellow_count}个，其余{green_count}个地区已进入绿灯。"
        return f"地区分层结果显示，红灯{red_count}个、黄灯{yellow_count}个。"

    def _build_regional_blocking_reason(self, regional_rows: list[dict[str, Any]]) -> str:
        flagged_rows = [row for row in regional_rows if row.get("status") in {"红灯", "黄灯"}]
        if not flagged_rows:
            return ""

        red_rows = [row for row in flagged_rows if row.get("status") == "红灯"]
        yellow_rows = [row for row in flagged_rows if row.get("status") == "黄灯"]
        focus_rows = flagged_rows[:2]
        focus_text = "、".join(
            f"{row.get('region')}（库销比{self._fmt(row.get('ratio'))}）"
            for row in focus_rows
            if row.get("region") and row.get("ratio") is not None
        )

        if red_rows and yellow_rows:
            reason = (
                f"地区侧仍有{len(red_rows)}个红灯地区、{len(yellow_rows)}个黄灯地区未回到目标区间，"
                f"当前主要压力集中在{focus_text}。"
            )
        elif red_rows:
            reason = f"地区侧仍有{len(red_rows)}个红灯地区未出清，当前主要压力集中在{focus_text}。"
        else:
            reason = f"地区侧仍有{len(yellow_rows)}个黄灯地区尚未回到目标区间，当前主要压力集中在{focus_text}。"

        if len(flagged_rows) > len(focus_rows):
            reason += f" 其余{len(flagged_rows) - len(focus_rows)}个尾部地区也在拖累整体去化。"
        return reason

    def _build_purchase_blocking_reason(
        self,
        history_evaluations: list[dict[str, Any]],
        risk_level: str,
    ) -> str:
        matched_rows = [row for row in history_evaluations if row.get("purchase_risk_level") == risk_level]
        if not matched_rows:
            return ""

        focus_rows = matched_rows[:2]
        examples = "、".join(
            (
                f"{row.get('region')}-{row.get('model')}（库销比{self._fmt(row.get('ratio'))}"
                f"、进销比{self._fmt(row.get('inbound_ratio')) if row.get('inbound_ratio') is not None else '待补充'}"
                f"、次月测算{self._fmt(row.get('future_ratio'))}）"
            )
            for row in focus_rows
            if row.get("region") and row.get("model")
        )
        if risk_level == "P1":
            return (
                f"{len(matched_rows)}个地区型号属于P1高风险（高库销&高进销），说明高库销纸袋仍有新增订购或库存压力未降，"
                f"重点为{examples}。"
            )
        return (
            f"{len(matched_rows)}个地区型号属于P2中风险（高库销&低进销），说明历史积压尚未消化但本期仍有订购，"
            f"重点为{examples}。"
        )

    def _build_structure_blocking_reason(self, analysis_rows: list[dict[str, Any]]) -> str:
        mismatch_rows = [
            row
            for row in analysis_rows
            if row.get("structure_label") in {"库存偏小码积压", "库存偏大码积压", "使用偏大尺码"}
        ]
        if not mismatch_rows:
            return ""

        focus_rows = mismatch_rows[:2]
        details: list[str] = []
        for row in focus_rows:
            region = row.get("region")
            label = row.get("structure_label")
            if not region or not label:
                continue
            if label == "库存偏小码积压":
                details.append(
                    f"{region}库存端以{row.get('top_model')}为主（{(row.get('top_share') or 0) * 100:.1f}%），"
                    f"但使用端主要消化{row.get('usage_top_model')}（{(row.get('usage_top_share') or 0) * 100:.1f}%）"
                )
            elif label == "库存偏大码积压":
                details.append(
                    f"{region}{row.get('top_model')}库存占比{(row.get('top_share') or 0) * 100:.1f}%，"
                    f"明显高于实际使用主力{row.get('usage_top_model')}"
                )
            else:
                details.append(
                    f"{region}使用端偏向{row.get('usage_top_model')}，偏大尺码使用占比达到{(row.get('usage_top_share') or 0) * 100:.1f}%"
                )
        if not details:
            return ""
        return f"库存结构错配也在拖累去化，重点表现为{'；'.join(details)}。"

    def _extract_forecast_rows(self, dataset: NormalizedDataset | None) -> list[dict[str, Any]]:
        if dataset is None:
            return []

        items: list[dict[str, Any]] = []
        current_region: str | None = None

        for row in dataset.rows:
            region = self._find_text_value(row, self.region_keys)
            if region and not self._is_total_region(region):
                current_region = region
            elif current_region:
                region = current_region

            model = self._find_text_value(row, self.model_keys)
            if (
                not region
                or not model
                or self._is_total_region(region)
                or self._is_total_model(model)
            ):
                continue

            current_inventory = self._find_numeric_value(row, self.inventory_keys)
            current_ratio = self._derive_ratio(row)
            future_usage = self._find_numeric_value(row, self.future_sales_keys)
            future_ratio = self._find_numeric_value(row, self.future_ratio_keys)

            if future_ratio is None and current_inventory is not None and future_usage not in (None, 0):
                future_ratio = (current_inventory - future_usage) / future_usage

            items.append(
                {
                    "region": region,
                    "model": model,
                    "current_inventory": current_inventory,
                    "current_ratio": current_ratio,
                    "same_period_sales_qty": self._find_numeric_value(row, ["同期后30天纸袋销量"]),
                    "future_usage": future_usage,
                    "future_ratio": future_ratio,
                    "level": self._purchase_level(future_ratio),
                    "raw": row,
                }
            )

        items.sort(key=lambda item: item["future_ratio"] if item["future_ratio"] is not None else float("inf"))
        return items

    def _build_future_demand_gaps(self, forecast_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        safety_target_ratio = 0.5
        for row in forecast_rows:
            current_inventory = row.get("current_inventory")
            future_usage = row.get("future_usage")
            future_ratio = row.get("future_ratio")
            level = row.get("level")
            if (
                current_inventory is None
                or future_usage is None
                or future_ratio is None
                or level not in {"紧急", "重点关注"}
            ):
                continue

            shortage_qty = max(future_usage - current_inventory, 0.0)
            suggested_order_qty = max(future_usage * (1 + safety_target_ratio) - current_inventory, 0.0)
            if suggested_order_qty <= 0:
                continue

            gaps.append(
                {
                    "region": row.get("region"),
                    "model": row.get("model"),
                    "current_inventory": current_inventory,
                    "current_ratio": row.get("current_ratio"),
                    "future_usage": future_usage,
                    "future_ratio": future_ratio,
                    "level": level,
                    "shortage_qty": shortage_qty,
                    "suggested_order_qty": suggested_order_qty,
                    "safety_target_ratio": safety_target_ratio,
                    "raw": row.get("raw", {}),
                }
            )

        return sorted(
            gaps,
            key=lambda item: (
                self._purchase_level_priority(item.get("level", "待识别")),
                -(item.get("suggested_order_qty") or 0),
                item.get("region") or "",
                item.get("model") or "",
            ),
        )

    def _build_consumption_exceptions(self, by_role: dict[str, NormalizedDataset], report_month: str) -> dict[str, Any]:
        overall_summary = by_role.get("overall_consumption_summary") or by_role.get("overall_consumption_ratio")
        monthly_dataset = by_role.get("consumption_ratio_monthly") or overall_summary
        order_anomalies = by_role.get("order_ratio_anomalies")
        order_allow_empty = bool(order_anomalies and order_anomalies.summary.get("allow_empty_result"))
        order_empty_reason = order_anomalies.summary.get("empty_reason", "") if order_anomalies else ""

        ratio = self._extract_consumption_ratio(overall_summary, monthly_dataset, report_month)
        overview_metrics = self._extract_consumption_overview_metrics(overall_summary, report_month)
        ratio_history = self._extract_consumption_ratio_history(monthly_dataset, overall_summary)
        ratio_history = self._filter_series_to_fiscal_window(ratio_history, report_month)
        previous_ratio = ratio_history[-2]["value"] if len(ratio_history) >= 2 else None
        order_items = self._extract_order_anomalies(order_anomalies, report_month)
        if order_allow_empty and not order_items:
            order_empty_reason = self._build_current_month_empty_order_reason(report_month, order_empty_reason)
        store_rollups = self._aggregate_store_anomalies(order_items, None)
        regional_anomaly_rows = self._aggregate_regional_order_anomalies(order_items, report_month)

        if ratio is not None or order_items or store_rollups or regional_anomaly_rows or order_allow_empty:
            summary_sentence = (
                f"纸袋使用配比总体值为{self._fmt(ratio)}，"
                f"订单异常{len(order_items)}条，重点门店{len(store_rollups)}个，"
                f"重点地区{len(regional_anomaly_rows)}个。"
            )
        else:
            summary_sentence = "纸袋使用配比与异常订单模块已切换到订单级控制逻辑。"

        return {
            "overall_ratio": ratio,
            "overall_cost": overview_metrics["overall_cost"],
            "overall_sales_qty": overview_metrics["overall_sales_qty"],
            "overall_avg_price": overview_metrics["overall_avg_price"],
            "previous_ratio": previous_ratio,
            "ratio_history": ratio_history,
            "order_anomalies": order_items[:20],
            "store_rollups": store_rollups[:20],
            "store_anomalies": store_rollups[:20],
            "regional_anomaly_rows": regional_anomaly_rows[:20],
            "order_anomaly_empty_is_normal": order_allow_empty and not order_items,
            "order_anomaly_empty_reason": order_empty_reason,
            "analysis_card_scope": "l6e08fdcc7fef45ccaa31d1b",
            "summary_sentence": summary_sentence,
        }

    def _build_current_month_empty_order_reason(self, report_month: str, configured_reason: str) -> str:
        year, month = report_month.split("-")
        current_month_reason = f"{year}年{int(month)}月无异常订单属于正常现象"
        if not configured_reason or configured_reason.startswith("2026年3月"):
            return current_month_reason
        return configured_reason.replace("本期", f"{year}年{int(month)}月")

    def _extract_consumption_overview_metrics(
        self,
        overall_summary: NormalizedDataset | None,
        report_month: str,
    ) -> dict[str, float | None]:
        if overall_summary is None or not overall_summary.rows:
            return {"overall_cost": None, "overall_sales_qty": None, "overall_avg_price": None}

        report_year = report_month.split("-")[0]
        total_row = next(
            (
                row
                for row in overall_summary.rows
                if str(row.get("纸袋分类", "")).strip() == "总计"
            ),
            overall_summary.rows[0],
        )
        return {
            "overall_cost": self._find_numeric_value(total_row, [f"{report_year}-门店纸袋发生费用", "门店纸袋发生费用"]),
            "overall_sales_qty": self._find_numeric_value(total_row, [f"{report_year}-纸袋销售量", "纸袋销售量"]),
            "overall_avg_price": self._find_numeric_value(total_row, [f"{report_year}-纸袋平均单价(含税)", "纸袋平均单价", "纸袋平均单价(含税)"]),
        }

    def _extract_consumption_ratio(
        self,
        overall_summary: NormalizedDataset | None,
        monthly_dataset: NormalizedDataset | None,
        report_month: str,
    ) -> float | None:
        history = self._extract_consumption_ratio_history(monthly_dataset, overall_summary)
        target = self._select_series_item_by_report_month(history, report_month)
        if target is not None:
            return target["value"]

        ratio = self._first_numeric_value(overall_summary.rows if overall_summary else [], self.non_group_ratio_keys)
        if ratio is not None:
            return ratio
        ratio = self._first_numeric_value(overall_summary.rows if overall_summary else [], self.ratio_keys)
        if ratio is not None:
            return ratio
        return history[-1]["value"] if history else None

    def _extract_consumption_ratio_history(
        self,
        monthly_dataset: NormalizedDataset | None,
        overall_summary: NormalizedDataset | None,
    ) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []

        if monthly_dataset and monthly_dataset.rows:
            for row in monthly_dataset.rows:
                value = self._derive_consumption_ratio(row)
                label = self._extract_period_label(row)
                if value is None or label is None:
                    continue
                history.append({"label": label, "value": value})
            if history:
                history.sort(key=lambda item: self._period_sort_key(item["label"]))
                return history

        if overall_summary and overall_summary.rows:
            first_row = overall_summary.rows[0]
            for key, value in first_row.items():
                if "纸袋配比" not in key or not isinstance(value, (int, float)):
                    continue
                label = "当前" if key == "纸袋配比" else key.replace("纸袋配比-", "")
                history.append({"label": label, "value": float(value)})
        return history

    def _extract_order_anomalies(
        self,
        dataset: NormalizedDataset | None,
        report_month: str | None = None,
    ) -> list[dict[str, Any]]:
        if dataset is None:
            return []

        items: list[dict[str, Any]] = []
        for row in dataset.rows:
            label = self._extract_period_label(row)
            if report_month and label is not None and not str(label).startswith(report_month):
                continue
            ratio = self._find_numeric_value(row, self.ratio_keys)
            if ratio is None or ratio <= self.thresholds.order_anomaly_ratio_min:
                continue

            items.append(
                {
                    "label": label,
                    "region": self._find_text_value(row, self.region_keys),
                    "store": self._find_text_value(row, self.store_keys),
                    "store_code": self._find_text_value(row, ["原销售店号", "销售店号", "店铺编码", "门店编码", "店铺代码", "门店代码", "店号"]),
                    "model": self._find_text_value(row, self.model_keys),
                    "order_id": self._find_text_value(row, ["订单号", "销售单号", "单号", "订单"]),
                    "ratio": ratio,
                    "amount": self._find_numeric_value(row, self.amount_keys),
                    "raw": row,
                }
            )

        items.sort(key=lambda item: item["ratio"], reverse=True)
        return items

    def _aggregate_store_anomalies(
        self,
        order_items: list[dict[str, Any]],
        _store_dataset: NormalizedDataset | None,
    ) -> list[dict[str, Any]]:
        if order_items:
            grouped: dict[tuple[str | None, str | None], dict[str, Any]] = {}
            for item in order_items:
                key = (item.get("region"), item.get("store"))
                entry = grouped.setdefault(
                    key,
                    {
                        "region": item.get("region"),
                        "store": item.get("store"),
                        "ratio": item.get("ratio"),
                        "amount": 0.0,
                        "order_count": 0,
                        "max_ratio": item.get("ratio"),
                    },
                )
                entry["order_count"] += 1
                entry["max_ratio"] = max(entry["max_ratio"] or 0.0, item.get("ratio") or 0.0)
                if item.get("ratio") is not None:
                    entry["ratio"] = entry["max_ratio"]
                if item.get("amount") is not None:
                    entry["amount"] += item["amount"]
            return sorted(
                grouped.values(),
                key=lambda item: (item["order_count"], item["max_ratio"], item["amount"]),
                reverse=True,
            )

        return []

    def _aggregate_regional_order_anomalies(
        self,
        order_items: list[dict[str, Any]],
        report_month: str,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in order_items:
            region = item.get("region")
            if not region:
                continue
            entry = grouped.setdefault(
                region,
                {
                    "label": report_month,
                    "region": region,
                    "count": 0.0,
                    "max_ratio": item.get("ratio"),
                    "store_codes": [],
                    "raw": item.get("raw", {}),
                },
            )
            entry["count"] += 1
            store_code = item.get("store_code")
            if store_code and store_code not in entry["store_codes"]:
                entry["store_codes"].append(store_code)
            item_ratio = item.get("ratio")
            if item_ratio is not None:
                entry["max_ratio"] = max(entry.get("max_ratio") or 0.0, item_ratio)

        return sorted(grouped.values(), key=lambda item: item["count"], reverse=True)

    def _build_stocktake_risks(self, by_role: dict[str, NormalizedDataset], report_month: str) -> dict[str, Any]:
        stocktake_monthly = by_role.get("stocktake_monthly")
        stocktake_region = by_role.get("stocktake_region")
        stocktake_difference = by_role.get("stocktake_difference")
        stocktake_difference_chart = by_role.get("stocktake_difference_chart")

        monthly_rows = self._extract_stocktake_monthly_rows(stocktake_monthly)
        monthly_rows = self._filter_series_to_fiscal_window(monthly_rows, report_month)
        region_rows_from_card = self._extract_stocktake_region_rows(stocktake_region)
        difference_rows = self._extract_stocktake_difference_region_rows(stocktake_difference, report_month)
        difference_chart_rows = self._extract_stocktake_difference_region_rows(
            stocktake_difference_chart or stocktake_difference,
            report_month,
        )
        difference_fiscal_rows = self._extract_stocktake_fiscal_rows(stocktake_difference_chart)

        monthly_target = self._select_series_item_by_report_month(monthly_rows, report_month)
        previous_month_target = monthly_rows[-2] if len(monthly_rows) >= 2 else None
        monthly_loss = None
        if monthly_target:
            monthly_loss = monthly_target["loss_amount"] if monthly_target["loss_amount"] is not None else monthly_target["net_loss_qty"]
        previous_month_loss = None
        if previous_month_target:
            previous_month_loss = (
                previous_month_target["loss_amount"]
                if previous_month_target["loss_amount"] is not None
                else previous_month_target["net_loss_qty"]
            )

        regional_rows = region_rows_from_card or difference_rows
        focus_source_rows = difference_rows or regional_rows
        focus_regions = [
            item
            for item in focus_source_rows
            if (
                item["loss_amount"] is not None
                and abs(item["loss_amount"]) > self.thresholds.regional_inventory_loss_amount_max
            )
            or (
                item["loss_amount"] is None
                and item["net_loss_qty"] is not None
                and item["net_loss_qty"] > self.thresholds.regional_inventory_loss_qty_max
            )
        ]
        focus_regions.sort(
            key=lambda item: (
                abs(item["loss_amount"]) if item["loss_amount"] is not None else -1,
                item["net_loss_qty"] if item["net_loss_qty"] is not None else -1,
            ),
            reverse=True,
        )

        if monthly_rows or regional_rows or difference_rows:
            summary_sentence = (
                f"盘点模块已识别{len(focus_regions)}个盘差率大于5%的重点大区，"
                f"最新月度盘点指标为{self._fmt(monthly_loss)}。"
            )
        else:
            summary_sentence = "盘点控制模块已切换到“全国趋势 + 地区差异”结构。"

        return {
            "monthly_loss": monthly_loss,
            "previous_month_loss": previous_month_loss,
            "monthly_rows": monthly_rows,
            "regional_rows": regional_rows,
            "difference_rows": difference_rows,
            "difference_chart_rows": difference_chart_rows,
            "difference_fiscal_rows": difference_fiscal_rows,
            "focus_regions": focus_regions[:20],
            "focus_region_names": [item["region"] for item in focus_regions[:10]],
            "focus_stores": [],
            "regional_source": "门店纸袋盘点-by大区" if region_rows_from_card else "盘差率大于5%大区维度",
            "summary_sentence": summary_sentence,
        }

    def _extract_stocktake_fiscal_rows(self, dataset: NormalizedDataset | None) -> list[dict[str, Any]]:
        if dataset is None:
            return []

        rows: list[dict[str, Any]] = []
        for row in dataset.rows:
            fiscal_year = self._find_text_value(row, ["财年", "年份", "年度", "FY"])
            if not fiscal_year:
                continue
            fiscal_year_text = str(fiscal_year).strip()
            if fiscal_year_text.endswith(".0"):
                fiscal_year_text = fiscal_year_text[:-2]
            if not (len(fiscal_year_text) == 4 and fiscal_year_text.startswith("20")):
                continue

            loss_qty = self._find_numeric_value(row, ["盘亏数量", "盘差数量", "盘亏量", "差异数量"])
            gain_qty = self._find_numeric_value(row, ["盘盈数量"])
            loss_amount = self._find_numeric_value(row, ["盘亏金额", "盘差金额", "盘亏损失金额", "损失金额"])
            gain_amount = self._find_numeric_value(row, ["盘盈金额"])
            rows.append(
                {
                    "label": f"FY{fiscal_year_text[-2:]}",
                    "fiscal_year": fiscal_year_text,
                    "loss_qty": loss_qty,
                    "gain_qty": gain_qty,
                    "total_qty": (loss_qty or 0) + (gain_qty or 0),
                    "loss_amount": loss_amount,
                    "gain_amount": gain_amount,
                    "total_amount": (loss_amount or 0) + (gain_amount or 0),
                    "raw": row,
                }
            )

        return sorted(rows, key=lambda item: int(item["fiscal_year"]))

    def _extract_stocktake_monthly_rows(self, dataset: NormalizedDataset | None) -> list[dict[str, Any]]:
        if dataset is None:
            return []

        rows: list[dict[str, Any]] = []
        for row in dataset.rows:
            label = self._extract_period_label(row)
            if label is None:
                continue
            diff_qty = self._find_numeric_value(row, ["盘差数量", "盘亏数量", "盘差量", "差异数量"])
            gain_qty = self._find_numeric_value(row, ["盘盈数量"])
            rows.append(
                {
                    "label": label,
                    "loss_qty": diff_qty,
                    "gain_qty": gain_qty,
                    "net_loss_qty": self._calculate_net_loss_qty(diff_qty, gain_qty),
                    "total_qty": (diff_qty or 0) + (gain_qty or 0),
                    "loss_amount": self._find_numeric_value(row, ["盘亏金额", "盘亏损失金额", "损失金额"]),
                    "raw": row,
                }
            )
        rows.sort(key=lambda item: self._period_sort_key(item["label"]))
        return rows

    def _extract_stocktake_region_rows(self, regional_dataset: NormalizedDataset | None) -> list[dict[str, Any]]:
        if regional_dataset is None:
            return []

        rows: list[dict[str, Any]] = []
        for row in regional_dataset.rows:
            region = self._find_text_value(row, self.region_keys)
            if not region or self._is_total_region(region):
                continue
            diff_qty = self._find_numeric_value(row, ["盘亏数量", "盘差数量", "盘亏量", "差异数量"])
            gain_qty = self._find_numeric_value(row, ["盘盈数量"])
            rows.append(
                {
                    "region": region,
                    "loss_amount": self._find_numeric_value(row, ["盘亏金额", "盘亏损失金额", "损失金额"]),
                    "loss_qty": diff_qty,
                    "gain_qty": gain_qty,
                    "net_loss_qty": self._calculate_net_loss_qty(diff_qty, gain_qty),
                    "total_qty": (diff_qty or 0) + (gain_qty or 0),
                    "diff_rate": self._find_numeric_value(row, ["盘差率", "盘亏率", "差异率"]),
                    "raw": row,
                }
            )

        return sorted(
            rows,
            key=lambda item: (
                abs(item["loss_amount"]) if item["loss_amount"] is not None else -1,
                item["net_loss_qty"] if item["net_loss_qty"] is not None else -1,
            ),
            reverse=True,
        )

    def _extract_stocktake_difference_region_rows(
        self,
        stocktake_difference: NormalizedDataset | None,
        report_month: str,
    ) -> list[dict[str, Any]]:
        if stocktake_difference is None:
            return []

        rows: list[dict[str, Any]] = []
        for row in stocktake_difference.rows:
            label = self._extract_period_label(row)
            if label is not None and not str(label).startswith(report_month):
                continue
            region = self._find_text_value(row, self.region_keys)
            if not region or self._is_total_region(region):
                continue

            diff_qty = self._find_numeric_value(row, ["合计盘盈亏数量", "盘差数量", "盘亏数量", "盘亏量"])
            gain_qty = self._find_numeric_value(row, ["盘盈数量"])
            net_loss_qty = None
            if diff_qty is not None:
                net_loss_qty = abs(diff_qty) if diff_qty < 0 else diff_qty
            elif gain_qty is not None:
                net_loss_qty = self._calculate_net_loss_qty(diff_qty, gain_qty)

            loss_amount = self._find_numeric_value(row, ["盘差率大于5%损失计算", "损失计算", "盘亏损失金额", "损失金额"])

            diff_rate = None
            for rate_key in ("盘差率", "盘亏率", "差异率"):
                rate_value = row.get(rate_key)
                if isinstance(rate_value, (int, float)) and not isinstance(rate_value, bool):
                    diff_rate = float(rate_value)
                    break
            if diff_rate is None:
                book_inventory = self._find_numeric_value(row, ["账面库存"])
                if book_inventory not in (None, 0) and diff_qty is not None:
                    diff_rate = abs(diff_qty) / abs(book_inventory)

            rows.append(
                {
                    "label": label or report_month,
                    "region": region,
                    "loss_amount": loss_amount,
                    "loss_qty": diff_qty,
                    "gain_qty": gain_qty,
                    "net_loss_qty": net_loss_qty,
                    "total_qty": (diff_qty or 0) + (gain_qty or 0),
                    "diff_rate": diff_rate,
                    "book_inventory": self._find_numeric_value(row, ["账面库存"]),
                    "actual_inventory": self._find_numeric_value(row, ["实盘数量"]),
                    "raw": row,
                }
            )

        return sorted(
            rows,
            key=lambda item: (
                abs(item["loss_amount"]) if item["loss_amount"] is not None else -1,
                item["net_loss_qty"] if item["net_loss_qty"] is not None else -1,
            ),
            reverse=True,
        )

    def _top_store_anomalies(self, dataset: NormalizedDataset | None) -> list[dict[str, Any]]:
        if dataset is None:
            return []
        items: list[dict[str, Any]] = []
        for row in dataset.rows:
            items.append(
                {
                    "region": self._find_text_value(row, self.region_keys),
                    "store": self._find_text_value(row, self.store_keys),
                    "ratio": self._find_numeric_value(row, self.ratio_keys),
                    "amount": self._find_numeric_value(row, self.amount_keys),
                    "raw": row,
                }
            )
        return sorted(
            items,
            key=lambda item: (
                item["amount"] if item["amount"] is not None else -1,
                item["ratio"] if item["ratio"] is not None else -1,
            ),
            reverse=True,
        )

    def _build_ai_insights(
        self,
        report_month: str,
        regional_status: dict[str, Any],
        purchase_analysis: dict[str, Any],
        consumption_exceptions: dict[str, Any],
        stocktake_risks: dict[str, Any],
    ) -> dict[str, Any]:
        profiles: dict[str, dict[str, Any]] = {}

        def _profile(region: str) -> dict[str, Any]:
            entry = profiles.get(region)
            if entry is None:
                entry = {
                    "region": region,
                    "overstock_rows": [],
                    "future_gap_rows": [],
                    "order_anomaly_count": 0,
                    "max_order_ratio": None,
                    "stocktake_net_loss_qty": None,
                    "stocktake_loss_amount": None,
                    "inventory_status": None,
                }
                profiles[region] = entry
            return entry

        status_map = {row.get("region"): row.get("status") for row in regional_status.get("regional_rows", [])}
        for region, status in status_map.items():
            if region:
                _profile(region)["inventory_status"] = status

        for row in purchase_analysis.get("history_evaluations", []):
            region = row.get("region")
            if not region:
                continue
            _profile(region)["overstock_rows"].append(row)

        for row in purchase_analysis.get("future_demand_gaps", []):
            region = row.get("region")
            if not region:
                continue
            _profile(region)["future_gap_rows"].append(row)

        for row in consumption_exceptions.get("regional_anomaly_rows", []):
            region = row.get("region")
            if not region:
                continue
            profile = _profile(region)
            profile["order_anomaly_count"] += int(row.get("count") or 0)
            current_max = profile.get("max_order_ratio")
            candidate = row.get("max_ratio")
            if candidate is not None:
                profile["max_order_ratio"] = candidate if current_max is None else max(current_max, candidate)

        for row in stocktake_risks.get("focus_regions", []):
            region = row.get("region")
            if not region:
                continue
            profile = _profile(region)
            profile["stocktake_net_loss_qty"] = row.get("net_loss_qty")
            profile["stocktake_loss_amount"] = row.get("loss_amount")

        action_items: list[dict[str, Any]] = []
        for region, profile in profiles.items():
            overstock_rows = sorted(
                profile["overstock_rows"],
                key=lambda item: (item.get("excess_inventory_qty") or 0, item.get("future_ratio") or 0),
                reverse=True,
            )
            future_gap_rows = sorted(
                profile["future_gap_rows"],
                key=lambda item: (
                    self._purchase_level_priority(item.get("level", "待识别")),
                    -(item.get("suggested_order_qty") or 0),
                ),
            )
            focus_models: list[str] = []
            reason_parts: list[str] = []
            action_lines: list[str] = []
            action_details: list[dict[str, Any]] = []
            severity = 0

            for row in overstock_rows[:2]:
                model = row.get("model")
                if model and model not in focus_models:
                    focus_models.append(model)
                excess_qty = int(round(max(row.get("excess_inventory_qty") or 0, 0)))
                if excess_qty <= 0:
                    continue
                inventory_qty = int(round(max(row.get("inventory_qty") or 0, 0)))
                future_usage = int(round(max(row.get("future_usage") or 0, 0)))
                target_inventory_qty = int(round(max(row.get("target_inventory_qty") or 0, 0)))
                reason_parts.append(
                    f"{model}期末库存{inventory_qty}个，未来30天预计销量{future_usage}个，"
                    f"按次月期末库销比{self.thresholds.purchase_future_ratio_min:.1f}测算超储{excess_qty}个"
                )
                action_details.append(
                    {
                        "type": "overstock",
                        "model": model,
                        "action": "暂停新增订购",
                        "quantity": excess_qty,
                        "unit": "个",
                        "target_inventory_qty": target_inventory_qty,
                    }
                )
                action_lines.append(
                    self._format_action_line(
                        len(action_lines) + 1,
                        f"{model}：库存积压，库销比{self._fmt(row.get('ratio'))}",
                        "立即停止订购",
                    )
                )
                severity += 2 if (row.get("future_ratio") or 0) >= 6 or excess_qty >= 10000 else 1

            for row in future_gap_rows[:2]:
                model = row.get("model")
                if model and model not in focus_models:
                    focus_models.append(model)
                suggested_order_qty = int(round(max(row.get("suggested_order_qty") or 0, 0)))
                if suggested_order_qty <= 0:
                    continue
                inventory_qty = int(round(max(row.get("current_inventory") or 0, 0)))
                future_usage = int(round(max(row.get("future_usage") or 0, 0)))
                shortage_qty = int(round(max(row.get("shortage_qty") or 0, 0)))
                safety_target_ratio = row.get("safety_target_ratio", 0.5)
                reason_parts.append(
                    f"{model}期末库存{inventory_qty}个，未来30天预计销量{future_usage}个，"
                    f"按次月期末保留{self._fmt(safety_target_ratio)}个月安全库存测算需补{suggested_order_qty}个"
                )
                if shortage_qty > 0:
                    action_details.append(
                        {
                            "type": "shortage",
                            "model": model,
                            "action": "补货",
                            "quantity": suggested_order_qty,
                            "unit": "个",
                            "shortage_qty": shortage_qty,
                            "safety_target_ratio": safety_target_ratio,
                        }
                    )
                    action_lines.append(
                        self._format_action_line(
                            len(action_lines) + 1,
                            f"{model}：库存短缺，库销比{self._fmt(row.get('current_ratio'))}",
                            f"尽快补货{suggested_order_qty}个",
                        )
                    )
                else:
                    action_details.append(
                        {
                            "type": "shortage_buffer",
                            "model": model,
                            "action": "预留补货",
                            "quantity": suggested_order_qty,
                            "unit": "个",
                            "shortage_qty": shortage_qty,
                            "safety_target_ratio": safety_target_ratio,
                        }
                    )
                    action_lines.append(
                        self._format_action_line(
                            len(action_lines) + 1,
                            f"{model}：库存偏紧，库销比{self._fmt(row.get('current_ratio'))}",
                            f"预留补货{suggested_order_qty}个",
                        )
                    )
                severity += 2 if row.get("level") == "紧急" else 1

            if profile["order_anomaly_count"] > 0:
                max_order_ratio = profile.get("max_order_ratio")
                if max_order_ratio is not None:
                    reason_parts.append(
                        f"本期异常订单{int(profile['order_anomaly_count'])}单，最高纸袋配比{max_order_ratio:.2f}"
                    )
                    action_details.append(
                        {
                            "type": "order_anomaly",
                            "action": "复盘异常订单",
                            "quantity": int(profile["order_anomaly_count"]),
                            "unit": "单",
                            "max_order_ratio": float(max_order_ratio),
                        }
                    )
                    action_lines.append(
                        self._format_action_line(
                            len(action_lines) + 1,
                            f"异常订单：{int(profile['order_anomaly_count'])}单高配比",
                            "立即复盘整改",
                        )
                    )
                else:
                    reason_parts.append(f"本期异常订单{int(profile['order_anomaly_count'])}单")
                    action_details.append(
                        {
                            "type": "order_anomaly",
                            "action": "复盘异常订单",
                            "quantity": int(profile["order_anomaly_count"]),
                            "unit": "单",
                        }
                    )
                    action_lines.append(
                        self._format_action_line(
                            len(action_lines) + 1,
                            f"异常订单：{int(profile['order_anomaly_count'])}单异常",
                            "立即复盘整改",
                        )
                    )
                severity += 1
            if profile["stocktake_net_loss_qty"] not in (None, 0):
                loss_amount = profile.get("stocktake_loss_amount")
                net_loss_qty = int(round(max(profile.get("stocktake_net_loss_qty") or 0, 0)))
                if loss_amount is not None:
                    reason_parts.append(f"盘点损失金额{int(round(abs(loss_amount)))}元，净盘差{net_loss_qty}个")
                    action_details.append(
                        {
                            "type": "stocktake",
                            "action": "立即复核追损",
                            "quantity": net_loss_qty,
                            "unit": "个",
                            "loss_amount": int(round(abs(loss_amount))),
                        }
                    )
                    action_lines.append(
                        self._format_action_line(
                            len(action_lines) + 1,
                            f"盘点差异：净盘差{net_loss_qty}个",
                            f"立即复核追损{int(round(abs(loss_amount)))}元",
                        )
                    )
                else:
                    reason_parts.append(f"盘点净盘差{net_loss_qty}个")
                    action_details.append(
                        {
                            "type": "stocktake",
                            "action": "复核盘点差异",
                            "quantity": net_loss_qty,
                            "unit": "个",
                        }
                    )
                    action_lines.append(
                        self._format_action_line(
                            len(action_lines) + 1,
                            f"盘点差异：净盘差{net_loss_qty}个",
                            "立即复核并关闭台账",
                        )
                    )
                severity += 1
            if profile["inventory_status"] == "红灯":
                severity += 2
                reason_parts.append("地区整体库销比处于红灯区间")
            elif profile["inventory_status"] == "黄灯":
                severity += 1
                reason_parts.append("地区整体库销比处于黄灯区间")

            if not reason_parts or not action_lines:
                continue

            priority = "P1" if severity >= 5 else "P2" if severity >= 3 else "P3"
            action_types = {detail.get("type") for detail in action_details if isinstance(detail, dict)}
            if "stocktake" in action_types and focus_models:
                primary_issue = "库存与盘点复合问题"
            elif "stocktake" in action_types:
                primary_issue = "盘点差异复核"
            elif "order_anomaly" in action_types and focus_models:
                primary_issue = "库存与终端复合问题"
            else:
                primary_issue = "型号库存动作" if focus_models else "终端执行偏差"
            selected_action_details = action_details[:4]
            stocktake_details = [detail for detail in action_details if detail.get("type") == "stocktake"]
            if stocktake_details and not any(detail.get("type") == "stocktake" for detail in selected_action_details):
                selected_action_details = (selected_action_details[:3] + stocktake_details[:1]) if selected_action_details else stocktake_details[:1]
            selected_action_lines = action_lines[:4]
            stocktake_lines = [line for line in action_lines if "盘点差异" in line]
            if stocktake_lines and not any("盘点差异" in line for line in selected_action_lines):
                selected_action_lines = (selected_action_lines[:3] + stocktake_lines[:1]) if selected_action_lines else stocktake_lines[:1]
            issue_key = f"{region}-{primary_issue}"
            priority_rule = self._build_ai_action_priority_rule(priority, severity)
            priority_reason = self._build_ai_action_priority_reason(
                priority=priority,
                severity=severity,
                action_types=action_types,
                profile=profile,
                high_inventory_count=len(overstock_rows),
                future_gap_count=len(future_gap_rows),
            )
            action_items.append(
                {
                    "issue_key": issue_key,
                    "region": region,
                    "priority": priority,
                    "severity_score": severity,
                    "priority_rule": priority_rule,
                    "priority_reason": priority_reason,
                    "focus_models": focus_models,
                    "root_cause": self._join_text_parts(reason_parts[:3]),
                    "action_details": selected_action_details,
                    "business_plan": self._join_action_lines(selected_action_lines),
                    "baseline": {
                        "high_inventory_count": len(overstock_rows),
                        "future_gap_count": len(future_gap_rows),
                        "order_anomaly_count": profile["order_anomaly_count"],
                        "stocktake_net_loss_qty": profile["stocktake_net_loss_qty"],
                        "action_count": len(selected_action_lines),
                    },
                }
            )

        priority_order = {"P1": 0, "P2": 1, "P3": 2}
        action_items.sort(
            key=lambda item: (
                priority_order.get(str(item.get("priority")), 99),
                -float(item.get("severity_score") or 0),
                str(item.get("region") or ""),
            )
        )
        filtered_action_items = [item for item in action_items if item.get("priority") in {"P1", "P2"}]
        if filtered_action_items:
            summary = (
                f"{report_month} AI洞察识别{len(filtered_action_items)}个重点区域、"
                f"{sum(item['baseline'].get('action_count', 0) for item in filtered_action_items)}条可执行动作，"
                f"其中P1优先级{sum(1 for item in filtered_action_items if item['priority'] == 'P1')}个。"
            )
        else:
            summary = "AI洞察未识别到新增需要落地的动作。"
        return {
            "summary_sentence": summary,
            "regional_actions": filtered_action_items,
        }

    def _build_ai_action_priority_rule(self, priority: str, severity: int | float) -> str:
        if priority == "P1":
            return f"P1规则：严重度评分{severity:g}分，达到>=5的最高优先级阈值。"
        if priority == "P2":
            return f"P2规则：严重度评分{severity:g}分，达到3-4的常规优先级阈值。"
        return f"P3规则：严重度评分{severity:g}分，低于P1/P2展示阈值。"

    def _build_ai_action_priority_reason(
        self,
        *,
        priority: str,
        severity: int | float,
        action_types: set[Any],
        profile: dict[str, Any],
        high_inventory_count: int,
        future_gap_count: int,
    ) -> str:
        reason_parts: list[str] = [f"严重度评分{severity:g}分"]
        if high_inventory_count:
            reason_parts.append(f"高库存组合{high_inventory_count}个")
        if future_gap_count:
            reason_parts.append(f"需求缺口{future_gap_count}个")
        if "order_anomaly" in action_types:
            reason_parts.append(f"异常订单{int(profile.get('order_anomaly_count') or 0)}单")
        if "stocktake" in action_types:
            reason_parts.append("存在盘点差异")
        inventory_status = profile.get("inventory_status")
        if inventory_status in {"红灯", "黄灯"}:
            reason_parts.append(f"地区整体库销比{inventory_status}")
        rule_label = "P1" if priority == "P1" else "P2" if priority == "P2" else "P3"
        return f"{rule_label}判定：" + "；".join(reason_parts)

    def _summarize_model_focus(
        self,
        history_evaluations: list[dict[str, Any]],
        future_demand_gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}

        for item in history_evaluations:
            model = item["model"]
            entry = grouped.setdefault(
                model,
                {
                    "model": model,
                    "waste_regions": [],
                    "shortage_regions": [],
                    "waste_count": 0,
                    "shortage_count": 0,
                    "waste_qty": 0.0,
                    "shortage_qty": 0.0,
                    "max_ratio": 0.0,
                    "min_future_ratio": None,
                    "action_summary": "",
                },
            )
            entry["waste_count"] += 1
            entry["waste_qty"] += max(item.get("excess_inventory_qty") or 0, 0)
            entry["max_ratio"] = max(entry["max_ratio"], item["ratio"])
            if item["region"] not in entry["waste_regions"]:
                entry["waste_regions"].append(item["region"])

        for item in future_demand_gaps:
            model = item["model"]
            entry = grouped.setdefault(
                model,
                {
                    "model": model,
                    "waste_regions": [],
                    "shortage_regions": [],
                    "waste_count": 0,
                    "shortage_count": 0,
                    "waste_qty": 0.0,
                    "shortage_qty": 0.0,
                    "max_ratio": 0.0,
                    "min_future_ratio": None,
                    "action_summary": "",
                },
            )
            entry["shortage_count"] += 1
            entry["shortage_qty"] += max(item.get("suggested_order_qty") or 0, 0)
            if item["region"] not in entry["shortage_regions"]:
                entry["shortage_regions"].append(item["region"])
            if item["future_ratio"] is not None:
                current_min = entry["min_future_ratio"]
                entry["min_future_ratio"] = (
                    item["future_ratio"]
                    if current_min is None
                    else min(current_min, item["future_ratio"])
                )

        for entry in grouped.values():
            waste_qty = int(round(max(entry.get("waste_qty") or 0, 0)))
            shortage_qty = int(round(max(entry.get("shortage_qty") or 0, 0)))
            if waste_qty > 0 and shortage_qty > 0:
                entry["action_summary"] = (
                    f"高库存地区先停新增订购并消化约{waste_qty}个，"
                    f"缺口地区按预测补足约{shortage_qty}个。"
                )
            elif waste_qty > 0:
                entry["action_summary"] = f"压减后续订购，先消化约{waste_qty}个超额库存，并复核是否存在规格浪费。"
            elif shortage_qty > 0:
                entry["action_summary"] = f"按未来30天预测补足约{shortage_qty}个，并复核门店规格配置是否偏小。"
            else:
                entry["action_summary"] = "持续跟踪未来30天销量与库存结构。"

        return sorted(
            grouped.values(),
            key=lambda item: (
                item["waste_qty"] + item["shortage_qty"],
                item["waste_count"] + item["shortage_count"],
                item["max_ratio"],
            ),
            reverse=True,
        )

    def _describe_dataset_source(self, dataset: NormalizedDataset | None) -> dict[str, Any]:
        if dataset is None:
            return {"source_type": "missing", "label": "未获取到订购预测数据"}

        if dataset.role == "purchase_forecast_sheet":
            return {
                "source_type": "workbook",
                "label": dataset.card_name,
                "workbook_path": dataset.raw_payload.get("workbook_path"),
                "sheet_name": dataset.raw_payload.get("sheet_name"),
            }

        return {
            "source_type": "card",
            "label": dataset.card_name,
            "card_id": dataset.card_id,
        }

    def _inventory_light(self, ratio: float | None) -> str:
        if ratio is None:
            return "待识别"
        if ratio <= self.thresholds.inventory_green_max:
            return "绿灯"
        if ratio <= self.thresholds.inventory_yellow_max:
            return "黄灯"
        return "红灯"

    def _classify_purchase_history_risk_level(
        self,
        *,
        opening_ratio: float | None,
        ending_ratio: float | None,
        inbound_ratio: float | None,
    ) -> str | None:
        if opening_ratio is None or ending_ratio is None or inbound_ratio is None or inbound_ratio <= 0:
            return None

        opening_light = self._inventory_light(opening_ratio)
        ending_light = self._inventory_light(ending_ratio)
        if opening_light == "红灯" and ending_light in {"红灯", "黄灯"}:
            return "P1"
        if opening_light == "黄灯" and ending_light == "红灯":
            return "P1"
        if opening_light == "黄灯" and ending_light == "黄灯":
            return "P2"
        if opening_light == "绿灯" and ending_light == "红灯":
            return "P2"
        if opening_light == "绿灯" and ending_light == "黄灯":
            return "P3"
        return None

    def _purchase_history_priority(self, level: str | None) -> int:
        return {"P1": 3, "P2": 2, "P3": 1}.get(str(level or ""), 0)

    def _purchase_level(self, ratio: float | None) -> str:
        if ratio is None:
            return "待识别"
        if ratio <= self.thresholds.purchase_urgent_max:
            return "紧急"
        if ratio <= self.thresholds.purchase_focus_max:
            return "重点关注"
        if ratio <= self.thresholds.purchase_watch_max:
            return "关注"
        return "暂不提示"

    def _purchase_level_priority(self, level: str) -> int:
        order = {"紧急": 0, "重点关注": 1, "关注": 2, "暂不提示": 3, "待识别": 4}
        return order.get(level, 9)

    def _first_numeric_value(self, rows: list[dict[str, Any]], keys: list[str]) -> float | None:
        for row in rows:
            value = self._find_numeric_value(row, keys)
            if value is not None:
                return value
        return None

    def _derive_ratio(self, row: dict[str, Any]) -> float | None:
        ratio = self._find_numeric_value(row, self.ratio_keys)
        if ratio is not None:
            return ratio
        inventory = self._find_numeric_value(row, self.inventory_keys)
        sales = self._find_numeric_value(row, self.sales_keys)
        if inventory is not None and sales not in (None, 0):
            return inventory / sales
        return None

    def _derive_consumption_ratio(self, row: dict[str, Any]) -> float | None:
        ratio = self._find_numeric_value(row, self.non_group_ratio_keys)
        if ratio is not None:
            return ratio
        return self._find_numeric_value(row, self.ratio_keys)

    def _find_numeric_value(self, row: dict[str, Any], keys: list[str]) -> float | None:
        matches: list[tuple[int, int, int, int, float]] = []
        for candidate_position, (candidate_key, value) in enumerate(row.items()):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            best_match: tuple[int, int] | None = None
            for index, key in enumerate(keys):
                score = self._match_score(str(candidate_key), key)
                if score > 0:
                    candidate_match = (score, -index)
                    if best_match is None or candidate_match > best_match:
                        best_match = candidate_match
            if best_match is not None:
                matches.append((best_match[0], best_match[1], -len(str(candidate_key)), -candidate_position, float(value)))
        if not matches:
            return None
        matches.sort(reverse=True)
        return matches[0][4]

    def _find_text_value(self, row: dict[str, Any], keys: list[str]) -> str | None:
        matches: list[tuple[int, str]] = []
        for candidate_key, value in row.items():
            if value is None:
                continue
            value_str = str(value).strip()
            if not value_str:
                continue
            best_score: int | None = None
            for key in keys:
                score = self._match_score(str(candidate_key), key)
                if score <= 0:
                    continue
                if "号" in str(candidate_key) or "编码" in str(candidate_key):
                    score -= 15
                if len(value_str) > 8:
                    score += 5
                if best_score is None or score > best_score:
                    best_score = score
            if best_score is not None:
                matches.append((best_score, value_str))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def _match_score(self, candidate_key: str, key: str) -> int:
        if candidate_key == key:
            return 100
        if candidate_key.startswith(key) or candidate_key.endswith(key):
            return 90
        if key in candidate_key:
            return 80
        return 0

    def _extract_period_label(self, row: dict[str, Any]) -> str | None:
        for key in self.period_keys:
            value = row.get(key)
            if value is None:
                continue
            label = self._stringify_period_value(value)
            if label:
                return label

        for candidate_key, value in row.items():
            if any(period_key in str(candidate_key) for period_key in self.period_keys):
                label = self._stringify_period_value(value)
                if label:
                    return label
        return None

    def _stringify_period_value(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        text = str(value).strip()
        return text or None

    def _period_sort_key(self, label: str) -> tuple[int, int, int, str]:
        normalized = label.replace("/", "-")
        try:
            if len(normalized) == 7:
                dt = datetime.strptime(normalized, "%Y-%m")
                return (dt.year, dt.month, 1, normalized)
            if len(normalized) == 10:
                dt = datetime.strptime(normalized, "%Y-%m-%d")
                return (dt.year, dt.month, dt.day, normalized)
        except ValueError:
            pass
        return (0, 0, 0, normalized)

    def _select_series_item_by_report_month(self, rows: list[dict[str, Any]], report_month: str) -> dict[str, Any] | None:
        if not rows:
            return None
        target_prefix = report_month
        exact_match = next((item for item in rows if str(item.get("label", "")).startswith(target_prefix)), None)
        if exact_match is not None:
            return exact_match
        return rows[-1]

    def _calculate_net_loss_qty(self, diff_qty: float | None, gain_qty: float | None) -> float | None:
        if diff_qty is None and gain_qty is None:
            return None
        loss_component = abs(diff_qty) if diff_qty is not None and diff_qty < 0 else max(diff_qty or 0, 0)
        gain_component = gain_qty or 0
        return max(loss_component - gain_component, 0)

    def _derive_compare_base(self, current_value: float | None, delta: float | None) -> float | None:
        if current_value is None or delta is None or (1 + delta) == 0:
            return None
        return current_value / (1 + delta)

    def _filter_series_up_to_report_month(self, rows: list[dict[str, Any]], report_month: str) -> list[dict[str, Any]]:
        cutoff = self._period_sort_key(report_month)
        filtered = [item for item in rows if self._period_sort_key(str(item.get("label", ""))) <= cutoff]
        return filtered or rows

    def _filter_series_to_fiscal_window(self, rows: list[dict[str, Any]], report_month: str) -> list[dict[str, Any]]:
        start_month = self._fiscal_window_start(report_month)
        start_key = self._period_sort_key(start_month)
        end_key = self._period_sort_key(report_month)
        filtered = [
            item
            for item in rows
            if start_key <= self._period_sort_key(str(item.get("label", ""))) <= end_key
        ]
        return filtered or self._filter_series_up_to_report_month(rows, report_month)

    def _fiscal_window_start(self, report_month: str) -> str:
        year, month = map(int, report_month.split("-"))
        return f"{year - 1:04d}-{month:02d}"

    def _aggregate_regional_ratio(self, rows: list[dict[str, Any]]) -> float | None:
        total_inventory = 0.0
        total_sales = 0.0
        used = False
        for row in rows:
            region = self._find_text_value(row, self.region_keys)
            if not region or self._is_total_region(region):
                continue
            inventory_qty = self._find_numeric_value(row, self.inventory_keys)
            sales_qty = self._find_numeric_value(row, self.sales_keys)
            if inventory_qty is None or sales_qty in (None, 0):
                continue
            total_inventory += inventory_qty
            total_sales += sales_qty
            used = True
        if used and total_sales > 0:
            return total_inventory / total_sales
        return None

    def _fmt(self, value: float | None, pct: bool = False) -> str:
        if value is None:
            return "待确认"
        if pct:
            return f"{value:.2%}"
        return f"{value:.2f}"

    def _join_text_parts(self, parts: list[str]) -> str:
        normalized = [part.rstrip("。；; ") for part in parts if part]
        if not normalized:
            return ""
        return f"{'；'.join(normalized)}。"

    def _format_action_line(self, index: int, headline: str, detail: str) -> str:
        headline_text = str(headline or "").rstrip("。；; ")
        detail_text = str(detail or "").rstrip("。；; ")
        if detail_text:
            return f"{index}. {headline_text}，{detail_text}。"
        return f"{index}. {headline_text}。"

    def _join_action_lines(self, lines: list[str]) -> str:
        normalized = [line.strip() for line in lines if line]
        if not normalized:
            return ""
        return "<br>".join(normalized)

    def _model_sort_key(self, model: str | None) -> tuple[int, str]:
        if not model:
            return (99, "")
        normalized = str(model).replace("滔搏纸袋-", "").upper()
        order = {"XXS": 0, "XS": 1, "S": 2, "M": 3, "L": 4, "XL": 5, "XXL": 6}
        return (order.get(normalized, 90), str(model))

    def _model_rank(self, model: str | None) -> int:
        return self._model_sort_key(model)[0]

    def _is_total_region(self, region: str) -> bool:
        return any(tag in region for tag in ["总计", "合计", "全国", "小计"])

    def _is_total_model(self, model: str) -> bool:
        return any(tag in model for tag in ["总计", "小计", "合计"])
