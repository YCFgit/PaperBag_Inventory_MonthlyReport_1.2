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

    @property
    def size_metrics(self) -> list[tuple[str, RegionSizeMetrics]]:
        return [("xs", self.xs), ("s", self.s), ("m", self.m), ("l", self.l), ("xl", self.xl)]

    @property
    def problem_sizes(self) -> list[dict[str, Any]]:
        problems = []
        for name, metric in self.size_metrics:
            if metric.theory_ratio <= 0:
                continue
            if DiagnosisService._is_usage_problem(metric, rate_threshold=0.2, gap_threshold=0.03):
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
            if diff_pp >= 0.15:
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
    透视后计算综合健康度得分。旧版实际消耗/月末库存 SQL 仅作为无卡片
    数据时的兜底输入。
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
    USAGE_TOLERANCE_RATE = 0.15
    STOCK_TOLERANCE_PP = 0.05
    USAGE_SCORE_FACTOR = 150.0
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
            usage_ratio_gap = actual_ratio - theory_ratio
            expected_actual = theory_ratio * total_actual if total_theory > 0 else 0.0
            dev_rate = usage_ratio_gap
            adjusted_dev_rate = max(0.0, abs(dev_rate) - self.USAGE_TOLERANCE_RATE)
            size_score = max(0.0, 100.0 - min(100.0, adjusted_dev_rate * self.USAGE_SCORE_FACTOR))
            stock_ratio = stock / total_stock if total_stock > 0 else 0.0
            stock_gap_pp = abs(stock_ratio - theory_ratio)
            adjusted_stock_gap_pp = max(0.0, stock_gap_pp - self.STOCK_TOLERANCE_PP)

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

        diag_type = self._classify_diagnosis(usage_compliance, inventory_health)

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
        )

    @staticmethod
    def _classify_diagnosis(usage_score: float, inventory_score: float) -> str:
        usage_bad = usage_score < 70
        inventory_bad = inventory_score < 70
        if usage_bad and inventory_bad:
            return "用袋配比偏差、备货也不对"
        if usage_bad:
            return "门店用袋尺码占比偏离理论配比"
        if inventory_bad:
            return "仓库各尺码备货比例跟实际需求对不上"
        return "基本正常"

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
        }

    @classmethod
    def _red_detail_to_dict(cls, d: RegionDiagnosis) -> dict[str, Any]:
        usage_problems = cls._build_usage_problem_rows(d)
        stock_problems = cls._build_stock_problem_rows(d)

        return {
            "region": d.region,
            "composite_score": d.composite_score,
            "usage_compliance_score": d.usage_compliance_score,
            "inventory_health_score": d.inventory_health_score,
            "status": d.status,
            "diagnosis_type": d.diagnosis_type,
            "usage_problems": usage_problems,
            "stock_problems": stock_problems,
            "usage_problem_groups": cls._build_usage_problem_groups(usage_problems),
            "recommended_actions": cls._build_recommended_actions(d, usage_problems, stock_problems),
            "total_theory_qty": d.total_theory_qty,
            "total_actual_qty": d.total_actual_qty,
            "total_stock_qty": d.total_stock_qty,
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
        return {
            "region": d.region,
            "composite_score": d.composite_score,
            "usage_compliance_score": d.usage_compliance_score,
            "inventory_health_score": d.inventory_health_score,
            "diagnosis_type": d.diagnosis_type,
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
        parts.append(f"{len(green)}个大区得分85分以上，运行正常。")
        if red:
            types = set(d.diagnosis_type for d in red)
            parts.append("主要问题集中在：门店用袋尺码占比偏离理论配比、仓库各尺码备货比例不合理。")
        return "".join(parts)

    def _build_action_items(self, red: list[RegionDiagnosis]) -> list[dict[str, Any]]:
        """将红灯大区诊断结果转为 P1/P2 行动项，兼容 AI 行动清单格式。"""
        items: list[dict[str, Any]] = []
        for d in red:
            focus_models: list[str] = []
            reason_parts: list[str] = []
            action_lines: list[str] = []
            severity = 0

            # 使用端问题
            for name, metric in d.size_metrics:
                if self._is_usage_problem(metric, rate_threshold=0.5, gap_threshold=0.05):
                    focus_models.append(name.upper())
                    reason_parts.append(self._usage_reason(name, metric))
                    action_lines.append(self._usage_action(name, metric))
                    severity += 2 if abs(metric.deviation_rate) >= 1.0 else 1

            # 库存端问题
            for name, metric in d.size_metrics:
                diff_pp = abs(metric.stock_ratio - metric.theory_ratio)
                if metric.theory_ratio > 0 and diff_pp >= 0.2:
                    focus_models.append(name.upper())
                    if metric.stock_ratio > metric.theory_ratio:
                        reason_parts.append(
                            f"{name.upper()}码库存占比{metric.stock_ratio * 100:.1f}%，"
                            f"理论需求占比{metric.theory_ratio * 100:.1f}%，备多了{diff_pp * 100:.0f}个百分点"
                        )
                        action_lines.append(f"{name.upper()}码：暂停新增订购，消化现有库存")
                    else:
                        reason_parts.append(
                            f"{name.upper()}码库存占比{metric.stock_ratio * 100:.1f}%，"
                            f"理论需求占比{metric.theory_ratio * 100:.1f}%，备少了{diff_pp * 100:.0f}个百分点，有断货风险"
                        )
                        action_lines.append(f"{name.upper()}码：尽快补货，补齐缺口")
                    severity += 2 if diff_pp >= 0.3 else 1

            if not reason_parts:
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
                f"触发问题{len(reason_parts)}项"
            )

            # 确定问题类型
            has_usage = any(
                self._is_usage_problem(m, rate_threshold=0.2, gap_threshold=0.03)
                for _, m in d.size_metrics
            )
            has_stock = any(
                abs(m.stock_ratio - m.theory_ratio) >= 0.15
                for _, m in d.size_metrics
                if m.theory_ratio > 0 or m.stock_ratio > 0
            )
            if has_usage and has_stock:
                issue_type = "使用与库存双偏差"
            elif has_usage:
                issue_type = "偏大尺码使用风险" if self._has_large_size_overuse(d) else "使用尺码配比偏差"
            else:
                issue_type = "库存结构错配"

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
                "root_cause": "；".join(reason_parts),
                "root_cause_multiline": "<br>".join(reason_parts),
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
