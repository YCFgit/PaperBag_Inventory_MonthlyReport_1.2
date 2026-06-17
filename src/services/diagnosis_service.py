from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any


@dataclass(slots=True)
class RegionSizeMetrics:
    theory_qty: int = 0
    actual_qty: int = 0
    stock_qty: int = 0
    deviation_rate: float = 0.0
    usage_ratio_gap: float = 0.0
    size_score: float = 100.0
    theory_ratio: float = 0.0
    actual_ratio: float = 0.0
    stock_ratio: float = 0.0
    expected_actual_qty: float = 0.0
    adjusted_deviation_rate: float = 0.0
    stock_gap_pp: float = 0.0
    adjusted_stock_gap_pp: float = 0.0
    inventory_depth_months: float = 0.0


@dataclass(slots=True)
class RegionDiagnosis:
    region: str
    period: str
    xs: RegionSizeMetrics
    s: RegionSizeMetrics
    m: RegionSizeMetrics
    l: RegionSizeMetrics
    xl: RegionSizeMetrics
    total_theory_qty: int = 0
    total_actual_qty: int = 0
    total_stock_qty: int = 0
    usage_compliance_score: float = 0.0
    inventory_health_score: float = 0.0
    composite_score: float = 0.0
    status: str = ""  # 🟢 绿灯 / 🟡 黄灯 / 🔴 红灯
    diagnosis_type: str = ""  # 双失衡 / 库存结构失衡 / 使用浪费严重 / 库存不足+使用规范
    usage_diagnosis: dict[str, Any] | None = None
    stock_diagnosis: dict[str, Any] | None = None
    inventory_structure_deviation: float = 0.0

    @property
    def size_metrics(self) -> list[tuple[str, RegionSizeMetrics]]:
        return [("xs", self.xs), ("s", self.s), ("m", self.m), ("l", self.l), ("xl", self.xl)]

    @property
    def problem_sizes(self) -> list[dict[str, Any]]:
        problems = []
        for name, metric in self.size_metrics:
            if metric.theory_ratio <= 0:
                continue
            if DiagnosisService._is_usage_problem(
                metric,
                rate_threshold=DiagnosisService.USAGE_TOLERANCE_RATE,
                gap_threshold=0.0,
            ):
                direction = "占比偏高" if metric.usage_ratio_gap > 0 else "占比偏低"
                problems.append({
                    "size": name.upper(),
                    "deviation_rate": metric.deviation_rate,
                    "usage_ratio_gap": metric.usage_ratio_gap,
                    "size_score": metric.size_score,
                    "direction": direction,
                })
        return problems

    @property
    def stock_problem_sizes(self) -> list[dict[str, Any]]:
        problems = []
        for name, metric in self.size_metrics:
            if metric.theory_ratio <= 0 and metric.stock_ratio <= 0:
                continue
            diff_pp = abs(metric.stock_ratio - metric.theory_ratio)
            if diff_pp >= DiagnosisService.STOCK_TOLERANCE_PP:
                direction = "库存过剩" if metric.stock_ratio > metric.theory_ratio else "库存不足"
                problems.append({
                    "size": name.upper(),
                    "stock_ratio": metric.stock_ratio,
                    "theory_ratio": metric.theory_ratio,
                    "diff_pp": diff_pp,
                    "direction": direction,
                })
        return problems


class DiagnosisService:
    """纸袋使用合规率 & 库存健康度诊断服务。

    理论需求来自诊断 SQL/CSV；实际消耗和期末库存优先来自
    a597c4441b7414c93a7c502d 卡片的地区×型号明细，按大区×月份×型号
    透视后计算综合健康度得分。运行时不再读取本地实际消耗/月末库存文件。
    """

    SIZES = ("xs", "s", "m", "l", "xl")
    LARGE_SIZE_NAMES = {"m", "l", "xl"}
    DIAGNOSIS_ALLOWED_REGIONS = {
        "华西区",
        "华东二区",
        "华北一区",
        "华北二区",
        "华南二区",
        "华中一区",
        "华南一区",
        "华中二区",
        "华东一区",
    }
    SQL_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "sql"
    INPUT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "input_data"
    USAGE_TOLERANCE_RATE = 0.10
    STOCK_TOLERANCE_PP = 0.10
    USAGE_SCORE_FACTOR = 150.0
    INVENTORY_SUPPORT_MONTH_MIN = 1.0
    INVENTORY_OVERSTOCK_MONTH_MAX = 2.0
    THEORETICAL_DEMAND_SHARE_MIN = 0.10
    PRICE_BY_SIZE = {
        "xs": 0.64,
        "s": 0.75,
        "m": 0.82,
        "l": 0.89,
        "xl": 1.59,
    }
    SIZE_ORDER = {"xs": 0, "s": 1, "m": 2, "l": 3, "xl": 4}
    MODEL_FIELD_KEYS = ("滔搏纸袋分类", "型号", "规格", "货号", "纸袋型号", "尺码", "包装规格", "pro_code", "商品编码", "纸袋编码")
    REGION_FIELD_KEYS = ("原销售大区", "大区", "地区", "区域", "管理大区", "区域名称", "战区")
    ACTUAL_CARD_FIELD_KEYS = ("期末近30天累计纸袋销售量", "近30天纸袋销量", "30天累计纸袋销售量", "近30天累计销量", "销售量")
    STOCK_CARD_FIELD_KEYS = ("期末业务库存量", "纸袋业务库存量", "业务库存量", "库存量", "期末库存", "库存")
    PRO_CODE_SIZE_MAP = {
        "ZD010XS": "xs",
        "ZD2023XS": "xs",
        "ZD010S": "s",
        "ZD2023S": "s",
        "ZD010M": "m",
        "ZD2023M": "m",
        "ZD010L": "l",
        "ZD2023L": "l",
        "ZD010XL": "xl",
        "ZD2023XL": "xl",
    }

    def __init__(self, sql_executor: Any = None, logger: Any = None) -> None:
        self.sql_executor = sql_executor
        self.logger = logger

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def build_diagnosis(
        self,
        theory_rows: list[dict[str, Any]],
        actual_rows: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        report_month: str,
    ) -> dict[str, Any]:
        """合并三张表数据并计算健康度评分。"""
        merged = self._merge_three_tables(theory_rows, actual_rows, stock_rows)
        diagnoses: list[RegionDiagnosis] = []
        for row in merged:
            if row.get("region") not in self.DIAGNOSIS_ALLOWED_REGIONS:
                continue
            diag = self._compute_scores(row)
            diagnoses.append(diag)

        diagnoses.sort(key=self._diagnosis_rank_key)

        red = [d for d in diagnoses if d.status == "🔴 红灯"]
        yellow = [d for d in diagnoses if d.status == "🟡 黄灯"]
        green = [d for d in diagnoses if d.status == "🟢 绿灯"]

        summary_sentence = self._build_summary_sentence(diagnoses, red, yellow, green)
        action_items = self._build_action_items(red)

        return {
            "diagnosis_ranking": [self._region_to_dict(d) for d in diagnoses],
            "red_light_details": [self._red_detail_to_dict(d) for d in red],
            "problem_light_details": [self._red_detail_to_dict(d) for d in red + yellow],
            "yellow_light_summary": [self._yellow_summary_to_dict(d) for d in yellow],
            "green_light_count": len(green),
            "summary_sentence": summary_sentence,
            "red_count": len(red),
            "yellow_count": len(yellow),
            "green_count": len(green),
            "total_regions": len(diagnoses),
            "action_items": action_items,
        }

    def build_actual_and_stock_rows_from_model_card(
        self,
        rows: list[dict[str, Any]],
        report_month: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """将 a597 地区×型号卡片行透视为第六章评分需要的实际/库存输入。"""
        by_region: dict[str, dict[str, Any]] = {}
        last_size = ""

        for row in rows:
            model_text = self._find_text_value(row, self.MODEL_FIELD_KEYS)
            size = self._normalize_bag_size(model_text)
            if size:
                last_size = size
            elif last_size:
                size = last_size

            region = self._find_text_value(row, self.REGION_FIELD_KEYS)
            if not region or self._is_total_region(region) or self._is_total_model(model_text):
                continue
            if size not in self.SIZES:
                continue

            bucket = by_region.setdefault(region, self._empty_card_pivot_row(region, report_month))
            bucket[f"{size}_actual_qty"] += self._to_int(self._find_value(row, self.ACTUAL_CARD_FIELD_KEYS))
            bucket[f"{size}_stock_qty"] += self._to_int(self._find_value(row, self.STOCK_CARD_FIELD_KEYS))

        actual_rows: list[dict[str, Any]] = []
        stock_rows: list[dict[str, Any]] = []
        for combined in by_region.values():
            actual_row = {
                "region": combined["region"],
                "period": combined["period"],
                **{f"{size}_actual_qty": combined[f"{size}_actual_qty"] for size in self.SIZES},
            }
            actual_row["total_actual_qty"] = sum(actual_row[f"{size}_actual_qty"] for size in self.SIZES)

            stock_row = {
                "region": combined["region"],
                "period": combined["period"],
                **{f"{size}_stock_qty": combined[f"{size}_stock_qty"] for size in self.SIZES},
            }
            stock_row["total_stock_qty"] = sum(stock_row[f"{size}_stock_qty"] for size in self.SIZES)
            actual_rows.append(actual_row)
            stock_rows.append(stock_row)

        return actual_rows, stock_rows

    def extract_model_card_rows(self, dataset: Any) -> list[dict[str, Any]]:
        """优先从原始 API payload 提取 a597 行，避免读取被本地月对齐替换后的 rows。"""
        raw_payload = getattr(dataset, "raw_payload", {}) or {}
        raw_rows = self._extract_rows_from_raw_payload(raw_payload)
        if raw_rows:
            return raw_rows
        return list(getattr(dataset, "rows", []) or [])

    def load_and_render_sql(self, sql_filename: str, report_month: str) -> str:
        """加载 SQL 模板并替换 ${report_month} 占位符。"""
        sql_path = self.SQL_DIR / sql_filename
        raw = sql_path.read_text(encoding="utf-8")
        return Template(raw).safe_substitute(report_month=report_month)

    def load_input_csv_rows(self, report_month: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        """从 data/input_data 读取人工执行 SQL 后下载的三份 CSV。"""
        files = {
            "theory": self.INPUT_DATA_DIR / f"{report_month}理论需求量.csv",
            "actual": self.INPUT_DATA_DIR / f"{report_month}实际消耗量.csv",
            "stock": self.INPUT_DATA_DIR / f"{report_month}月末库存量.csv",
        }
        if not all(path.exists() for path in files.values()):
            return None
        return (
            self._read_csv_rows(files["theory"]),
            self._read_csv_rows(files["actual"]),
            self._read_csv_rows(files["stock"]),
        )

    def load_theory_input_rows(self, report_month: str) -> list[dict[str, Any]] | None:
        """读取第六章理论需求 CSV。实际/库存优先由 a597 卡片透视。"""
        path = self.INPUT_DATA_DIR / f"{report_month}理论需求量.csv"
        if not path.exists():
            return None
        return self._read_csv_rows(path)

    # ------------------------------------------------------------------
    # 内部：工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_period(period: str) -> str:
        """统一年月格式为 YYYY-MM（兼容 YYYYMM 和 YYYY-MM）。"""
        period = str(period).strip()
        if len(period) == 6 and period.isdigit():
            return f"{period[:4]}-{period[4:]}"
        return period[:7]

    @classmethod
    def _read_csv_rows(cls, path: Path) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for encoding in ("utf-8-sig", "gb18030", "gbk"):
            try:
                with path.open("r", encoding=encoding, newline="") as fh:
                    return [cls._normalize_csv_row(row) for row in csv.DictReader(fh)]
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ValueError(f"Unable to read CSV with supported encodings: {path}") from last_error

    @classmethod
    def _normalize_csv_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            clean_key = str(key or "").strip().strip('"')
            if value is None:
                normalized[clean_key] = 0 if clean_key.endswith("_qty") else ""
                continue
            clean_value = str(value).strip().strip('"')
            if clean_key == "period":
                normalized[clean_key] = cls._normalize_period(clean_value)
            elif clean_key.endswith("_qty"):
                normalized[clean_key] = cls._to_int(clean_value)
            else:
                normalized[clean_key] = clean_value
        return normalized

    @classmethod
    def _extract_rows_from_raw_payload(cls, raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in raw_payload.get("pages", []) or []:
            rows.extend(cls._extract_rows_from_page(page))
        return rows

    @classmethod
    def _extract_rows_from_page(cls, page: dict[str, Any]) -> list[dict[str, Any]]:
        data = page.get("data")
        result = page.get("result")
        candidates = [
            page.get("rows"),
            data.get("rows") if isinstance(data, dict) else None,
            data.get("rowList") if isinstance(data, dict) else None,
            result.get("rows") if isinstance(result, dict) else None,
            data.get("list") if isinstance(data, dict) else None,
            page.get("list"),
        ]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [cls._normalize_card_row(row) for row in candidate if isinstance(row, dict)]
        return []

    @classmethod
    def _normalize_card_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            normalized[str(key).strip()] = cls._normalize_card_value(value)
        return normalized

    @staticmethod
    def _normalize_card_value(value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip().replace(",", "")
            if stripped.endswith("%"):
                try:
                    return float(stripped[:-1]) / 100
                except ValueError:
                    return value.strip()
            try:
                if "." in stripped:
                    return float(stripped)
                return int(stripped)
            except ValueError:
                return value.strip()
        return value

    @staticmethod
    def _diagnosis_rank_key(diagnosis: RegionDiagnosis) -> tuple[int, float, str]:
        status_order = {
            "🔴 红灯": 0,
            "🟡 黄灯": 1,
            "🟢 绿灯": 2,
        }
        return (status_order.get(diagnosis.status, 9), diagnosis.composite_score, diagnosis.region)

    @staticmethod
    def _to_int(value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            return int(round(float(str(value).replace(",", ""))))
        except ValueError:
            return 0

    @classmethod
    def _empty_card_pivot_row(cls, region: str, report_month: str) -> dict[str, Any]:
        row: dict[str, Any] = {"region": region, "period": report_month}
        for size in cls.SIZES:
            row[f"{size}_actual_qty"] = 0
            row[f"{size}_stock_qty"] = 0
        return row

    @staticmethod
    def _find_value(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
        normalized_items = [(str(key or "").strip(), value) for key, value in row.items()]
        for expected in keys:
            for key, value in normalized_items:
                if key == expected and value not in (None, ""):
                    return value
        for expected in keys:
            for key, value in normalized_items:
                if expected in key and value not in (None, ""):
                    return value
        return None

    @classmethod
    def _find_text_value(cls, row: dict[str, Any], keys: tuple[str, ...]) -> str:
        value = cls._find_value(row, keys)
        return str(value).strip() if value not in (None, "") else ""

    @classmethod
    def _normalize_bag_size(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text or cls._is_total_model(text):
            return ""

        compact = re.sub(r"\s+", "", text.upper())
        for pro_code, size in cls.PRO_CODE_SIZE_MAP.items():
            if pro_code in compact:
                return size

        if "XS" in compact:
            return "xs"
        if "XL" in compact:
            return "xl"
        for size in ("M", "L", "S"):
            if re.search(rf"(^|[^A-Z0-9]){size}([^A-Z0-9]|$)", compact):
                return size.lower()
        return ""

    @staticmethod
    def _is_total_region(value: Any) -> bool:
        text = str(value or "").strip()
        return any(marker in text for marker in ("总计", "合计", "小计", "全国", "总公司", "总部"))

    @staticmethod
    def _is_total_model(value: Any) -> bool:
        text = str(value or "").strip()
        return any(marker in text for marker in ("总计", "合计", "小计", "其他"))

    # ------------------------------------------------------------------
    # 内部：三表合并
    # ------------------------------------------------------------------

    def _merge_three_tables(
        self,
        theory_rows: list[dict[str, Any]],
        actual_rows: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        theory_by_key = {(r["region"], self._normalize_period(r["period"])): r for r in theory_rows}
        actual_by_key = {(r["region"], self._normalize_period(r["period"])): r for r in actual_rows}
        stock_by_key = {(r["region"], self._normalize_period(r["period"])): r for r in stock_rows}
        all_keys = set(theory_by_key) | set(actual_by_key) | set(stock_by_key)

        merged = []
        for key in all_keys:
            t = theory_by_key.get(key, {})
            a = actual_by_key.get(key, {})
            s = stock_by_key.get(key, {})
            merged.append({
                "region": key[0],
                "period": key[1],
                **{f"{sz}_theory_qty": t.get(f"{sz}_theory_qty", 0) for sz in self.SIZES},
                "total_theory_qty": t.get("total_theory_qty", 0),
                **{f"{sz}_actual_qty": a.get(f"{sz}_actual_qty", 0) for sz in self.SIZES},
                "total_actual_qty": a.get("total_actual_qty", 0),
                **{f"{sz}_stock_qty": s.get(f"{sz}_stock_qty", 0) for sz in self.SIZES},
                "total_stock_qty": s.get("total_stock_qty", 0),
            })
        return merged

    # ------------------------------------------------------------------
    # 内部：评分计算（核心逻辑）
    # ------------------------------------------------------------------

    def _compute_scores(self, row: dict[str, Any]) -> RegionDiagnosis:
        total_theory = row["total_theory_qty"]
        total_actual = row["total_actual_qty"]
        total_stock = row["total_stock_qty"]

        size_metrics: dict[str, RegionSizeMetrics] = {}
        for sz in self.SIZES:
            theory = self._to_int(row.get(f"{sz}_theory_qty", 0))
            actual = self._to_int(row.get(f"{sz}_actual_qty", 0))
            stock = self._to_int(row.get(f"{sz}_stock_qty", 0))

            theory_ratio = theory / total_theory if total_theory > 0 else 0.0
            actual_ratio = actual / total_actual if total_actual > 0 else 0.0
            expected_actual = theory_ratio * total_actual if total_theory > 0 else 0.0
            usage_ratio_gap = actual_ratio - theory_ratio
            if expected_actual > 0:
                dev_rate = (actual - expected_actual) / expected_actual
            elif actual == 0:
                dev_rate = 0.0
            else:
                dev_rate = 1.0
            adjusted_dev_rate = max(0.0, abs(dev_rate) - self.USAGE_TOLERANCE_RATE)
            size_score = max(0.0, 100.0 - min(100.0, adjusted_dev_rate * self.USAGE_SCORE_FACTOR))
            stock_ratio = stock / total_stock if total_stock > 0 else 0.0
            stock_gap_pp = abs(stock_ratio - theory_ratio)
            adjusted_stock_gap_pp = max(0.0, stock_gap_pp - self.STOCK_TOLERANCE_PP)
            inventory_depth_months = stock / theory if theory > 0 else 0.0

            m = RegionSizeMetrics(
                theory_qty=theory,
                actual_qty=actual,
                stock_qty=stock,
                deviation_rate=dev_rate,
                usage_ratio_gap=usage_ratio_gap,
                size_score=size_score,
                theory_ratio=theory_ratio,
                actual_ratio=actual_ratio,
                stock_ratio=stock_ratio,
                expected_actual_qty=expected_actual,
                adjusted_deviation_rate=adjusted_dev_rate,
                stock_gap_pp=stock_gap_pp,
                adjusted_stock_gap_pp=adjusted_stock_gap_pp,
                inventory_depth_months=inventory_depth_months,
            )
            size_metrics[sz] = m

        usage_compliance = sum(
            size_metrics[sz].size_score * size_metrics[sz].theory_ratio for sz in self.SIZES
        )
        stock_deviation = 0.5 * sum(
            size_metrics[sz].adjusted_stock_gap_pp for sz in self.SIZES
        )
        inventory_health = max(0.0, (1.0 - stock_deviation) * 100.0)
        composite = usage_compliance * 0.5 + inventory_health * 0.5

        if composite >= 85:
            status = "🟢 绿灯"
        elif composite >= 70:
            status = "🟡 黄灯"
        else:
            status = "🔴 红灯"

        temp_diag = RegionDiagnosis(
            region=row["region"],
            period=row["period"],
            xs=size_metrics["xs"],
            s=size_metrics["s"],
            m=size_metrics["m"],
            l=size_metrics["l"],
            xl=size_metrics["xl"],
            total_theory_qty=total_theory,
            total_actual_qty=row["total_actual_qty"],
            total_stock_qty=total_stock,
            usage_compliance_score=round(usage_compliance, 2),
            inventory_health_score=round(inventory_health, 2),
            composite_score=round(composite, 2),
            status=status,
            inventory_structure_deviation=round(stock_deviation * 100, 2),
        )
        usage_diagnosis = self._build_usage_diagnosis(temp_diag)
        stock_diagnosis = self._build_stock_diagnosis(temp_diag)
        diag_type = self._classify_diagnosis(usage_diagnosis, stock_diagnosis)

        return RegionDiagnosis(
            region=row["region"],
            period=row["period"],
            xs=size_metrics["xs"],
            s=size_metrics["s"],
            m=size_metrics["m"],
            l=size_metrics["l"],
            xl=size_metrics["xl"],
            total_theory_qty=total_theory,
            total_actual_qty=row["total_actual_qty"],
            total_stock_qty=total_stock,
            usage_compliance_score=round(usage_compliance, 2),
            inventory_health_score=round(inventory_health, 2),
            composite_score=round(composite, 2),
            status=status,
            diagnosis_type=diag_type,
            usage_diagnosis=usage_diagnosis,
            stock_diagnosis=stock_diagnosis,
            inventory_structure_deviation=round(stock_deviation * 100, 2),
        )

    @staticmethod
    def _classify_diagnosis(usage_diagnosis: dict[str, Any], stock_diagnosis: dict[str, Any]) -> str:
        usage_label = str(usage_diagnosis.get("label", "使用基本合规"))
        stock_findings = stock_diagnosis.get("findings", [])
        blocking = any(item.get("label") == "库存无法支持合理使用" for item in stock_findings)
        structure = any(item.get("label") == "库存结构不科学" for item in stock_findings)
        if usage_label != "使用基本合规" and blocking:
            return "使用与库存双失衡"
        if blocking:
            return "库存无法支持合理使用"
        if usage_label != "使用基本合规" and structure:
            return "使用偏差叠加库存错配"
        if usage_label != "使用基本合规":
            return usage_label
        if structure:
            return "库存结构不科学"
        return "配置与使用基本合理"

    @staticmethod
    def _is_usage_problem(
        metric: RegionSizeMetrics,
        *,
        rate_threshold: float,
        gap_threshold: float,
    ) -> bool:
        return (
            metric.theory_ratio > 0
            and metric.adjusted_deviation_rate > 0
            and abs(metric.deviation_rate) >= rate_threshold
            and abs(metric.usage_ratio_gap) >= gap_threshold
        )

    @classmethod
    def _is_stock_problem(cls, metric: RegionSizeMetrics, *, gap_threshold: float | None = None) -> bool:
        threshold = cls.STOCK_TOLERANCE_PP if gap_threshold is None else gap_threshold
        return (metric.theory_ratio > 0 or metric.stock_ratio > 0) and metric.stock_gap_pp > threshold

    @classmethod
    def _usage_direction(cls, size_name: str, metric: RegionSizeMetrics) -> str:
        size = size_name.lower()
        if metric.usage_ratio_gap > 0:
            if size in cls.LARGE_SIZE_NAMES:
                return "实际使用占比高于理论占比，存在偏大尺码使用偏高或大袋小用风险"
            return "实际使用占比高于理论占比，说明小尺码使用偏多，需复核理论配比和门店尺码匹配"
        if size in {"xs", "s"}:
            return "实际使用占比低于理论占比，可能被更大尺码替代"
        if size == "xl":
            return "实际使用占比低于理论占比，需复核理论配比和实际业务场景"
        return "实际使用占比低于理论占比，需排查是否被相邻尺码替代"

    @classmethod
    def _usage_action(cls, size_name: str, metric: RegionSizeMetrics) -> str:
        size = size_name.lower()
        label = size.upper()
        if metric.usage_ratio_gap > 0:
            if size in cls.LARGE_SIZE_NAMES:
                return f"{label}码：压降偏大尺码使用占比，复核是否存在大袋小用"
            return f"{label}码：复核小尺码适用场景和理论配比，避免误判为大袋替小袋"
        if size in {"xs", "s"}:
            return f"{label}码：排查是否被更大尺码替代，恢复理论使用占比"
        return f"{label}码：复核实际使用场景与理论配比，避免相邻尺码错配"

    @classmethod
    def _usage_reason(cls, size_name: str, metric: RegionSizeMetrics) -> str:
        gap = metric.usage_ratio_gap * 100
        compare = "高" if gap > 0 else "低"
        return (
            f"{size_name.upper()}码实际使用占比{metric.actual_ratio * 100:.1f}%，"
            f"理论需求占比{metric.theory_ratio * 100:.1f}%，"
            f"实际{compare}了{abs(gap):.1f}个百分点，{cls._usage_direction(size_name, metric)}"
        )

    @classmethod
    def _has_large_size_overuse(cls, d: RegionDiagnosis) -> bool:
        return any(
            name in cls.LARGE_SIZE_NAMES
            and metric.usage_ratio_gap > 0
            and cls._is_usage_problem(metric, rate_threshold=0.2, gap_threshold=0.03)
            for name, metric in d.size_metrics
        )

    @classmethod
    def _size_label(cls, size_name: str) -> str:
        return size_name.upper()

    @classmethod
    def _price(cls, size_name: str) -> float:
        return float(cls.PRICE_BY_SIZE.get(size_name.lower(), 0.0))

    @staticmethod
    def _format_percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    @classmethod
    def _adjusted_usage_qty(cls, metric: RegionSizeMetrics) -> float:
        if metric.expected_actual_qty <= 0:
            return max(0.0, float(metric.actual_qty))
        return max(0.0, metric.expected_actual_qty * metric.adjusted_deviation_rate)

    @classmethod
    def _usage_fact_lines(
        cls,
        d: RegionDiagnosis,
        *,
        limit: int = 4,
        include_stock_gap: bool = False,
    ) -> list[str]:
        focus_rows: list[tuple[str, RegionSizeMetrics]] = []
        for size_name, metric in d.size_metrics:
            if (
                cls._is_usage_problem(metric, rate_threshold=cls.USAGE_TOLERANCE_RATE, gap_threshold=0.0)
                or cls._is_stock_problem(metric)
            ):
                focus_rows.append((size_name, metric))
        if not focus_rows:
            return []

        focus_rows.sort(key=lambda item: cls.SIZE_ORDER.get(item[0], 99))
        lines: list[str] = []
        for index, (size_name, metric) in enumerate(focus_rows[:limit], start=1):
            line = (
                f"{index}. {cls._size_label(size_name)}码：理论使用需求占比{cls._format_percent(metric.theory_ratio)}，"
                f"实际使用占比{cls._format_percent(metric.actual_ratio)}，"
                f"库存占比{cls._format_percent(metric.stock_ratio)}"
            )
            if include_stock_gap and metric.stock_qty > 0 and metric.theory_ratio > 0:
                signed_gap = (metric.stock_ratio - metric.theory_ratio) * 100
                line += f"，库存偏差{signed_gap:+.1f}个百分点"
            lines.append(line)
        return lines

    @classmethod
    def _build_usage_diagnosis(cls, d: RegionDiagnosis) -> dict[str, Any]:
        pairs: list[dict[str, Any]] = []
        for large_name, large_metric in d.size_metrics:
            if cls.SIZE_ORDER.get(large_name, -1) < cls.SIZE_ORDER["m"]:
                continue
            if large_metric.deviation_rate <= cls.USAGE_TOLERANCE_RATE:
                continue
            smaller_candidates = [
                (small_name, small_metric)
                for small_name, small_metric in d.size_metrics
                if cls.SIZE_ORDER.get(small_name, -1) < cls.SIZE_ORDER.get(large_name, -1)
                and small_metric.deviation_rate < -cls.USAGE_TOLERANCE_RATE
            ]
            if not smaller_candidates:
                continue
            smaller_name, smaller_metric = min(
                smaller_candidates,
                key=lambda item: cls.SIZE_ORDER.get(large_name, 99) - cls.SIZE_ORDER.get(item[0], 0),
            )
            substitute_qty = min(
                cls._adjusted_usage_qty(large_metric),
                cls._adjusted_usage_qty(smaller_metric),
            )
            extra_cost = substitute_qty * max(0.0, cls._price(large_name) - cls._price(smaller_name))
            pairs.append(
                {
                    "from_size": smaller_name,
                    "to_size": large_name,
                    "from_size_label": cls._size_label(smaller_name),
                    "to_size_label": cls._size_label(large_name),
                    "substitute_qty": round(substitute_qty),
                    "extra_cost": round(extra_cost, 2),
                    "summary": (
                        f"{cls._size_label(large_name)}码替代{cls._size_label(smaller_name)}码"
                        f"（{cls._size_label(smaller_name)}码理论占比{smaller_metric.theory_ratio * 100:.1f}%，"
                        f"实际{smaller_metric.actual_ratio * 100:.1f}%，偏差{smaller_metric.deviation_rate * 100:+.1f}%；"
                        f"{cls._size_label(large_name)}码理论占比{large_metric.theory_ratio * 100:.1f}%，"
                        f"实际{large_metric.actual_ratio * 100:.1f}%，偏差{large_metric.deviation_rate * 100:+.1f}%）"
                    ),
                }
            )

        if pairs:
            total_extra_cost = sum(item["extra_cost"] for item in pairs)
            involved_under_sizes = sorted(
                {
                    item["from_size_label"]
                    for item in pairs
                    if next(
                        (
                            metric.usage_ratio_gap < 0
                            for size_name, metric in d.size_metrics
                            if cls._size_label(size_name) == item["from_size_label"]
                        ),
                        False,
                    )
                },
                key=lambda item: cls.SIZE_ORDER.get(item.lower(), 99),
            )
            involved_over_sizes = sorted(
                {
                    item["to_size_label"]
                    for item in pairs
                },
                key=lambda item: cls.SIZE_ORDER.get(item.lower(), 99),
            )
            under_text = "、".join(involved_under_sizes)
            over_text = "、".join(involved_over_sizes)
            headline = (
                f"{under_text}码门店实际使用占比低于理论占比，{over_text}码实际使用占比偏高，"
                "地区尺码订购与终端需求不匹配，存在大袋小用并带来额外费用。"
                if under_text and over_text
                else "地区纸袋尺码使用结构偏离理论配比，存在大袋小用并带来额外费用。"
            )
            fact_lines = cls._usage_fact_lines(d)
            summary_parts = [headline]
            if fact_lines:
                summary_parts.append("<br>".join(fact_lines))
            if total_extra_cost > 0:
                summary_parts.append(f"剔除容忍区间后，月度额外成本约¥{round(total_extra_cost):,.0f}。")
            severity = "🔴" if total_extra_cost >= 300 or abs(d.composite_score) < 60 else "🟡"
            return {
                "label": "大袋小用",
                "severity": severity,
                "summary": "<br>".join(summary_parts),
                "extra_cost": round(total_extra_cost, 2),
                "details": pairs,
            }

        small_overuse = [
            (size_name, metric)
            for size_name, metric in d.size_metrics
            if size_name in {"xs", "s"} and metric.deviation_rate > cls.USAGE_TOLERANCE_RATE
        ]
        total_excess_qty = max(0.0, d.total_actual_qty - d.total_theory_qty)
        if small_overuse and (total_excess_qty > 0 or d.total_theory_qty and d.total_actual_qty / d.total_theory_qty > 1.5):
            extra_qty = min(
                sum(cls._adjusted_usage_qty(metric) for _, metric in small_overuse),
                total_excess_qty if total_excess_qty > 0 else sum(metric.actual_qty for _, metric in small_overuse),
            )
            weighted_unit_cost = (
                sum(cls._adjusted_usage_qty(metric) * cls._price(size_name) for size_name, metric in small_overuse)
                / max(
                    1.0,
                    sum(cls._adjusted_usage_qty(metric) for _, metric in small_overuse),
                )
            )
            extra_cost = extra_qty * weighted_unit_cost
            size_labels = "、".join(cls._size_label(size_name) for size_name, _ in small_overuse)
            fact_lines = cls._usage_fact_lines(d)
            summary_parts = [
                f"{size_labels}码实际使用占比偏高，而大尺码配置低于理论需求，门店可能存在合包执行不足或拆分装袋。",
            ]
            if fact_lines:
                summary_parts.append("<br>".join(fact_lines))
            if extra_cost > 0:
                summary_parts.append(f"剔除容忍区间后，月度额外成本约¥{round(extra_cost):,.0f}。")
            return {
                "label": "合包问题",
                "severity": "🔴" if d.total_theory_qty and d.total_actual_qty / d.total_theory_qty > 1.5 else "🟡",
                "summary": "<br>".join(summary_parts),
                "extra_cost": round(extra_cost, 2),
                "details": [
                    {
                        "size_label": cls._size_label(size_name),
                        "summary": (
                            f"{cls._size_label(size_name)}码理论占比{metric.theory_ratio * 100:.1f}%，"
                            f"实际{metric.actual_ratio * 100:.1f}%，偏差{metric.deviation_rate * 100:+.1f}%"
                        ),
                    }
                    for size_name, metric in small_overuse
                ],
            }

        return {
            "label": "使用基本合规",
            "severity": "🟢",
            "summary": "各型号实际使用结构与理论最优结构基本一致，偏差均在±10%宽容区间内。",
            "extra_cost": 0.0,
            "details": [],
        }

    @classmethod
    def _build_stock_diagnosis(cls, d: RegionDiagnosis) -> dict[str, Any]:
        blocking: list[dict[str, Any]] = []
        structure: list[dict[str, Any]] = []
        structure_threshold = cls.STOCK_TOLERANCE_PP * 100
        for size_name, metric in d.size_metrics:
            if metric.theory_ratio < cls.THEORETICAL_DEMAND_SHARE_MIN:
                continue
            signed_gap = metric.stock_ratio - metric.theory_ratio
            is_blocking_understock = (
                metric.inventory_depth_months < cls.INVENTORY_SUPPORT_MONTH_MIN
                and signed_gap < -cls.STOCK_TOLERANCE_PP
            )
            if is_blocking_understock:
                blocking.append(
                    {
                        "label": "库存无法支持合理使用",
                        "size": size_name,
                        "size_label": cls._size_label(size_name),
                        "summary": (
                            f"{cls._size_label(size_name)}码库存深度仅{metric.inventory_depth_months:.2f}月，"
                            f"库存偏差{signed_gap * 100:+.1f}个百分点，无法支撑门店按推荐方案使用。"
                        ),
                    }
                )
            if (
                d.inventory_structure_deviation > structure_threshold
                or (metric.inventory_depth_months > cls.INVENTORY_OVERSTOCK_MONTH_MAX and signed_gap > cls.STOCK_TOLERANCE_PP)
                or (signed_gap < -cls.STOCK_TOLERANCE_PP and not is_blocking_understock)
            ):
                if signed_gap > cls.STOCK_TOLERANCE_PP:
                    structure.append(
                        {
                            "label": "库存结构不科学",
                            "size": size_name,
                            "size_label": cls._size_label(size_name),
                            "summary": (
                                f"{cls._size_label(size_name)}码库存深度{metric.inventory_depth_months:.2f}月，"
                                f"库存偏差{signed_gap * 100:+.1f}个百分点，存在积压风险。"
                            ),
                        }
                    )
                elif signed_gap < -cls.STOCK_TOLERANCE_PP and not is_blocking_understock:
                    structure.append(
                        {
                            "label": "库存结构不科学",
                            "size": size_name,
                            "size_label": cls._size_label(size_name),
                            "summary": (
                                f"{cls._size_label(size_name)}码库存深度{metric.inventory_depth_months:.2f}月，"
                                f"库存偏差{signed_gap * 100:+.1f}个百分点，需在后续订购中补齐。"
                            ),
                        }
                    )

        if not blocking and not structure and d.inventory_structure_deviation <= structure_threshold:
            findings = [
                {
                    "label": "库存基本合理",
                    "severity": "🟢",
                    "summary": f"库存结构偏差度未超过{int(structure_threshold)}%，主要尺码库存能够支撑常规使用。",
                }
            ]
        else:
            findings = [
                *[
                    {"label": item["label"], "severity": "🔴", "summary": item["summary"], "size_label": item["size_label"]}
                    for item in blocking
                ],
                *[
                    {"label": item["label"], "severity": "🟡", "summary": item["summary"], "size_label": item["size_label"]}
                    for item in structure
                ],
            ]
        return {
            "findings": findings,
            "structure_deviation_pct": round(d.inventory_structure_deviation, 1),
        }

    @classmethod
    def _build_priority_actions(
        cls,
        d: RegionDiagnosis,
        usage_diagnosis: dict[str, Any],
        stock_diagnosis: dict[str, Any],
    ) -> list[str]:
        actions: list[str] = []
        blocking_sizes = [
            item.get("size_label", "")
            for item in stock_diagnosis.get("findings", [])
            if item.get("label") == "库存无法支持合理使用"
        ]
        if blocking_sizes:
            actions.append(f"紧急补齐{'、'.join(blocking_sizes[:3])}码库存，目标库存深度≥1个月。")
        overstock_sizes = [
            cls._size_label(name)
            for name, metric in d.size_metrics
            if metric.inventory_depth_months > cls.INVENTORY_OVERSTOCK_MONTH_MAX
            and metric.stock_ratio - metric.theory_ratio > cls.STOCK_TOLERANCE_PP
        ]
        if overstock_sizes:
            actions.append(f"暂停或压降{'、'.join(overstock_sizes[:3])}码订购，优先调拨与消化存量。")
        usage_label = usage_diagnosis.get("label")
        usage_problem_sizes = [
            cls._size_label(name)
            for name, metric in d.size_metrics
            if cls._is_usage_problem(metric, rate_threshold=cls.USAGE_TOLERANCE_RATE, gap_threshold=0.0)
        ]
        overused_sizes = [
            cls._size_label(name)
            for name, metric in d.size_metrics
            if cls._is_usage_problem(metric, rate_threshold=cls.USAGE_TOLERANCE_RATE, gap_threshold=0.0)
            and metric.usage_ratio_gap > 0
        ]
        underused_sizes = [size for size in usage_problem_sizes if size not in overused_sizes]
        if usage_label == "大袋小用":
            if overused_sizes and underused_sizes:
                actions.append(
                    f"复盘{'、'.join(overused_sizes[:3])}码替代{'、'.join(underused_sizes[:3])}码的场景，按理论配比纠偏，避免大袋小用。"
                )
            else:
                actions.append("复盘门店领用与订购配比，压降偏大尺码替代使用。")
        elif usage_label == "合包问题":
            actions.append("复核合包规则与门店执行，减少偏小尺码拆分装袋。")
        elif d.composite_score < 85:
            actions.append("持续复核理论配比与门店业务场景，防止偏差进一步扩大。")
        return actions[:3]

    # ------------------------------------------------------------------
    # 内部：输出序列化
    # ------------------------------------------------------------------

    @staticmethod
    def _region_to_dict(d: RegionDiagnosis) -> dict[str, Any]:
        return {
            "region": d.region,
            "composite_score": d.composite_score,
            "usage_compliance_score": d.usage_compliance_score,
            "inventory_health_score": d.inventory_health_score,
            "status": d.status,
            "diagnosis_type": d.diagnosis_type,
            "usage_issue": (d.usage_diagnosis or {}).get("label", "使用基本合规"),
            "stock_issue": "；".join(item.get("label", "") for item in (d.stock_diagnosis or {}).get("findings", []) if item.get("label") != "库存基本合理") or "库存基本合理",
        }

    @classmethod
    def _red_detail_to_dict(cls, d: RegionDiagnosis) -> dict[str, Any]:
        usage_problems = cls._build_usage_problem_rows(d)
        stock_problems = cls._build_stock_problem_rows(d)
        usage_diagnosis = d.usage_diagnosis or cls._build_usage_diagnosis(d)
        stock_diagnosis = d.stock_diagnosis or cls._build_stock_diagnosis(d)

        return {
            "region": d.region,
            "composite_score": d.composite_score,
            "usage_compliance_score": d.usage_compliance_score,
            "inventory_health_score": d.inventory_health_score,
            "status": d.status,
            "diagnosis_type": d.diagnosis_type,
            "usage_diagnosis": usage_diagnosis,
            "stock_diagnosis": stock_diagnosis,
            "usage_problems": usage_problems,
            "stock_problems": stock_problems,
            "usage_problem_groups": cls._build_usage_problem_groups(usage_problems),
            "recommended_actions": cls._build_recommended_actions(d, usage_problems, stock_problems),
            "priority_actions": cls._build_priority_actions(d, usage_diagnosis, stock_diagnosis),
            "total_theory_qty": d.total_theory_qty,
            "total_actual_qty": d.total_actual_qty,
            "total_stock_qty": d.total_stock_qty,
            "inventory_structure_deviation_pct": round(d.inventory_structure_deviation, 1),
        }

    @classmethod
    def _build_usage_problem_rows(cls, d: RegionDiagnosis) -> list[dict[str, Any]]:
        rows = []
        for name, metric in d.size_metrics:
            if not cls._is_usage_problem(metric, rate_threshold=cls.USAGE_TOLERANCE_RATE, gap_threshold=0.0):
                continue
            direction = cls._usage_direction(name, metric)
            rows.append({
                "size": name.upper(),
                "deviation_rate_pct": f"{metric.deviation_rate * 100:+.1f}%",
                "adjusted_deviation_rate_pct": f"{metric.adjusted_deviation_rate * 100:.1f}%",
                "usage_gap_pp": round(metric.usage_ratio_gap * 100, 1),
                "usage_gap_text": f"{metric.usage_ratio_gap * 100:+.1f}个百分点",
                "size_score": round(metric.size_score, 1),
                "direction": direction,
                "theory_ratio_pct": f"{metric.theory_ratio * 100:.1f}%",
                "actual_ratio_pct": f"{metric.actual_ratio * 100:.1f}%",
                "expected_actual_qty": round(metric.expected_actual_qty, 1),
                "actual_qty": metric.actual_qty,
                "problem_type": cls._usage_problem_type(name, metric),
            })
        rows.sort(key=lambda row: abs(row["usage_gap_pp"]), reverse=True)
        return rows

    @classmethod
    def _build_stock_problem_rows(cls, d: RegionDiagnosis) -> list[dict[str, Any]]:
        rows = []
        for name, metric in d.size_metrics:
            if not cls._is_stock_problem(metric):
                continue
            if metric.stock_ratio > metric.theory_ratio:
                direction = "库存占比高于理论需求，占用库存空间"
                problem_type = f"{name.upper()}码库存偏高"
            else:
                direction = "库存占比低于理论需求，存在缺货或调拨压力"
                problem_type = f"{name.upper()}码库存不足"
            rows.append({
                "size": name.upper(),
                "stock_ratio_pct": f"{metric.stock_ratio * 100:.1f}%",
                "theory_ratio_pct": f"{metric.theory_ratio * 100:.1f}%",
                "diff_pp": round(metric.stock_gap_pp * 100, 1),
                "diff_pct": f"{(metric.stock_ratio - metric.theory_ratio) * 100:+.1f}%",
                "adjusted_diff_pp": round(metric.adjusted_stock_gap_pp * 100, 1),
                "adjusted_diff_pct": f"{metric.adjusted_stock_gap_pp * 100:.1f}%",
                "direction": direction,
                "problem_type": problem_type,
                "stock_qty": metric.stock_qty,
                "inventory_depth_months": round(metric.inventory_depth_months, 2),
            })
        rows.sort(key=lambda row: row["diff_pp"], reverse=True)
        return rows

    @classmethod
    def _usage_problem_type(cls, size_name: str, metric: RegionSizeMetrics) -> str:
        label = size_name.upper()
        if metric.usage_ratio_gap > 0:
            return f"{label}码使用偏好"
        return f"{label}码使用不足"

    @classmethod
    def _build_usage_problem_groups(cls, usage_problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not usage_problems:
            return []
        size_order = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}
        positive = [p for p in usage_problems if p["usage_gap_pp"] > 0]
        anchors = positive or usage_problems
        anchor = max(anchors, key=lambda p: abs(p["usage_gap_pp"]))
        anchor_index = size_order.get(anchor["size"], 0)
        related = [
            p for p in usage_problems
            if p is anchor or abs(size_order.get(p["size"], 0) - anchor_index) <= 2
        ]
        involved_sizes = "、".join(p["size"] for p in sorted(related, key=lambda p: size_order.get(p["size"], 0)))
        squeezed = [p for p in related if p["usage_gap_pp"] < 0]
        if anchor["usage_gap_pp"] > 0 and squeezed:
            squeezed_text = "、".join(p["size"] for p in squeezed)
            description = f"{anchor['size']}码实际使用占比偏高，挤压{squeezed_text}码使用空间"
        elif anchor["usage_gap_pp"] > 0:
            description = f"{anchor['size']}码实际使用占比偏高，需复核门店使用场景"
        else:
            description = f"{anchor['size']}码实际使用占比偏低，需排查是否被相邻尺码替代"
        return [{
            "problem_no": "问题1",
            "problem_type": anchor["problem_type"],
            "description": description,
            "sizes": involved_sizes,
            "details": related,
        }]

    @classmethod
    def _build_recommended_actions(
        cls,
        d: RegionDiagnosis,
        usage_problems: list[dict[str, Any]],
        stock_problems: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        high_stock = [p for p in stock_problems if "偏高" in p["problem_type"]]
        low_stock = [p for p in stock_problems if "不足" in p["problem_type"]]
        overused_large = [p for p in usage_problems if p["size"].lower() in cls.LARGE_SIZE_NAMES and p["usage_gap_pp"] > 0]
        underused_small = [p for p in usage_problems if p["size"].lower() in {"xs", "s"} and p["usage_gap_pp"] < 0]
        if low_stock:
            sizes = "、".join(p["size"] for p in low_stock[:3])
            actions.append({
                "priority": "高" if d.composite_score < 70 else "中",
                "action_item": "订购调整",
                "measure": f"优先补齐{sizes}码库存缺口，下一轮订购提高对应尺码占比",
                "expected_effect": "库存结构向理论需求占比收敛，降低断货风险",
                "deadline": "1周内",
            })
        if high_stock:
            sizes = "、".join(p["size"] for p in high_stock[:3])
            actions.append({
                "priority": "中",
                "action_item": "库存消化",
                "measure": f"暂停或压降{sizes}码新增订购，优先跨区调拨和存量消化",
                "expected_effect": "降低库存占比偏高尺码的资金占用",
                "deadline": "1个月内",
            })
        if overused_large:
            sizes = "、".join(p["size"] for p in overused_large[:3])
            actions.append({
                "priority": "高" if underused_small else "中",
                "action_item": "使用整改",
                "measure": f"复盘{sizes}码门店领用场景，限制偏大尺码替代小尺码",
                "expected_effect": "实际使用占比回落至理论结构宽容区间内",
                "deadline": "2周内",
            })
        if usage_problems and not overused_large:
            sizes = "、".join(p["size"] for p in usage_problems[:3])
            actions.append({
                "priority": "中",
                "action_item": "配比复核",
                "measure": f"复核{sizes}码理论配比与门店实际销售包装场景",
                "expected_effect": "澄清偏差来源，避免把总量差异误判为浪费",
                "deadline": "2周内",
            })
        priority_order = {"高": 0, "中": 1, "低": 2}
        actions.sort(key=lambda action: priority_order.get(action.get("priority", ""), 99))
        return actions[:3]

    @staticmethod
    def _yellow_summary_to_dict(d: RegionDiagnosis) -> dict[str, Any]:
        usage_diagnosis = d.usage_diagnosis or {}
        stock_diagnosis = d.stock_diagnosis or {}
        priority_actions = DiagnosisService._build_priority_actions(d, usage_diagnosis, stock_diagnosis)
        return {
            "region": d.region,
            "composite_score": d.composite_score,
            "usage_compliance_score": d.usage_compliance_score,
            "inventory_health_score": d.inventory_health_score,
            "diagnosis_type": d.diagnosis_type,
            "usage_issue": usage_diagnosis.get("label", "使用基本合规"),
            "stock_issue": "；".join(
                item.get("label", "") for item in stock_diagnosis.get("findings", []) if item.get("label") != "库存基本合理"
            ) or "库存基本合理",
            "suggestion": "；".join(priority_actions) if priority_actions else "持续跟踪当前结构，按下期偏差再微调。",
        }

    def _build_summary_sentence(
        self,
        diagnoses: list[RegionDiagnosis],
        red: list[RegionDiagnosis],
        yellow: list[RegionDiagnosis],
        green: list[RegionDiagnosis],
    ) -> str:
        parts = [f"本月共{len(diagnoses)}个大区参与纸袋健康度诊断，"]
        if red:
            regions = "、".join(d.region for d in red)
            parts.append(f"其中{len(red)}个大区得分低于70分（{regions}），需要重点关注。")
        if yellow:
            parts.append(f"{len(yellow)}个大区得分在70-84分之间，有一定偏差需跟踪。")
        if green:
            parts.append(f"{len(green)}个大区得分85分以上，运行正常。")
        if red:
            usage_labels = {str((d.usage_diagnosis or {}).get("label", "")) for d in red}
            stock_labels = {
                item.get("label", "")
                for d in red
                for item in (d.stock_diagnosis or {}).get("findings", [])
                if item.get("label") and item.get("label") != "库存基本合理"
            }
            problem_bits = [label for label in (*sorted(usage_labels), *sorted(stock_labels)) if label and label != "使用基本合规"]
            if problem_bits:
                parts.append(f"主要问题集中在：{'、'.join(problem_bits[:3])}。")
        return "".join(parts)

    def _build_action_items(self, red: list[RegionDiagnosis]) -> list[dict[str, Any]]:
        """将红灯大区诊断结果转为 P1/P2 行动项，兼容 AI 行动清单格式。"""
        items: list[dict[str, Any]] = []
        for d in red:
            usage_diagnosis = d.usage_diagnosis or self._build_usage_diagnosis(d)
            stock_diagnosis = d.stock_diagnosis or self._build_stock_diagnosis(d)
            focus_models: list[str] = []
            action_lines = self._build_priority_actions(d, usage_diagnosis, stock_diagnosis)
            severity = 0

            # 使用端问题
            for name, metric in d.size_metrics:
                if self._is_usage_problem(metric, rate_threshold=0.5, gap_threshold=0.05):
                    focus_models.append(name.upper())
                    severity += 2 if abs(metric.deviation_rate) >= 1.0 else 1

            # 库存端问题
            for name, metric in d.size_metrics:
                diff_pp = abs(metric.stock_ratio - metric.theory_ratio)
                if metric.theory_ratio > 0 and diff_pp >= 0.2:
                    focus_models.append(name.upper())
                    severity += 2 if diff_pp >= 0.3 else 1

            root_cause_lines = []
            usage_summary = str(usage_diagnosis.get("summary", "")).strip()
            if usage_summary and usage_diagnosis.get("label") != "使用基本合规":
                root_cause_lines.append(usage_summary)
            root_cause_lines.extend(
                item.get("summary", "")
                for item in stock_diagnosis.get("findings", [])
                if item.get("label") != "库存基本合理" and item.get("summary")
            )
            root_cause_lines = list(dict.fromkeys(line for line in root_cause_lines if line))

            if not root_cause_lines:
                continue

            focus_models = list(dict.fromkeys(focus_models))  # 去重保序
            priority = "P1" if severity >= 5 or d.composite_score < 40 else "P2"
            priority_rule = (
                f"P1规则：健康度诊断严重度{severity}分或综合得分低于40分。"
                if priority == "P1"
                else f"P2规则：健康度诊断识别结构问题，严重度{severity}分，综合得分{d.composite_score}分。"
            )
            priority_reason = (
                f"{priority}判定：健康度综合得分{d.composite_score}分；"
                f"使用合规得分{d.usage_compliance_score}分；库存健康得分{d.inventory_health_score}分；"
                f"触发问题{len(root_cause_lines)}项"
            )

            stock_labels = [
                item.get("label", "")
                for item in stock_diagnosis.get("findings", [])
                if item.get("label") and item.get("label") != "库存基本合理"
            ]
            if usage_diagnosis.get("label") != "使用基本合规" and stock_labels:
                issue_type = f"{usage_diagnosis.get('label')} + {' / '.join(stock_labels[:2])}"
            elif usage_diagnosis.get("label") != "使用基本合规":
                issue_type = str(usage_diagnosis.get("label"))
            else:
                issue_type = " / ".join(stock_labels[:2]) or "库存结构不科学"

            items.append({
                "issue_key": f"{d.region}-健康度诊断",
                "region": d.region,
                "priority": priority,
                "severity_score": severity,
                "priority_rule": priority_rule,
                "priority_reason": priority_reason,
                "issue_type": issue_type,
                "issue_type_label": issue_type,
                "focus_models": focus_models,
                "root_cause": "；".join(root_cause_lines),
                "root_cause_multiline": "<br>".join(root_cause_lines),
                "business_plan": "<br>".join(action_lines),
                "action_details": [
                    {"type": "diagnosis", "action": line, "source": "健康度诊断"}
                    for line in action_lines
                ],
                "review_metric": f"下月综合得分（当前{d.composite_score}分）",
                "review_metric_text": f"下月综合得分目标≥70分（当前{d.composite_score}分）",
                "baseline": {
                    "diagnosis_composite_score": d.composite_score,
                    "usage_compliance_score": d.usage_compliance_score,
                    "inventory_health_score": d.inventory_health_score,
                    "high_inventory_count": sum(
                        1
                        for _, metric in d.size_metrics
                        if metric.stock_ratio > metric.theory_ratio and abs(metric.stock_ratio - metric.theory_ratio) >= 0.2
                    ),
                    "future_gap_count": sum(
                        1
                        for _, metric in d.size_metrics
                        if metric.stock_ratio < metric.theory_ratio and abs(metric.stock_ratio - metric.theory_ratio) >= 0.2
                    ),
                    "order_anomaly_count": 0,
                    "stocktake_net_loss_qty": None,
                },
                "source": "diagnosis",
            })

        # P1 在前，P2 在后
        items.sort(key=lambda x: (0 if x["priority"] == "P1" else 1))
        return items
