from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.clients.llm_client import LLMClient
from src.models.schemas import SectionAnalysis


class AnalysisService:
    def __init__(self, llm_client: LLMClient | None, prompts: dict[str, Any], enable_llm: bool, logger: Any) -> None:
        self.llm_client = llm_client
        self.prompts = prompts
        self.enable_llm = enable_llm and llm_client is not None
        self.logger = logger

    def analyze_sections(self, report_facts: dict[str, Any]) -> list[SectionAnalysis]:
        reference_context = report_facts.get("reference_context", {})
        section_items = list(report_facts["sections"].items())

        def analyze_item(item: tuple[str, dict[str, Any]]) -> SectionAnalysis:
            section_key, payload = item
            title = payload["title"]
            facts = payload["facts"]
            section_reference = reference_context.get(section_key, {})
            if self.enable_llm:
                return self._analyze_with_llm(section_key, title, facts, section_reference)
            return self._fallback_analysis(section_key, title, facts)

        if self.enable_llm and len(section_items) > 1:
            max_workers = min(4, len(section_items))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                return list(executor.map(analyze_item, section_items))

        analyses: list[SectionAnalysis] = []
        for item in section_items:
            analyses.append(analyze_item(item))
        return analyses

    def _analyze_with_llm(
        self,
        section_key: str,
        title: str,
        facts: dict[str, Any],
        reference_context: dict[str, Any] | None = None,
    ) -> SectionAnalysis:
        started_at = time.monotonic()
        response: dict[str, Any] | None = None
        mode = "structured"
        retried = False
        llm_facts = self._facts_for_llm(section_key, facts)
        try:
            system_prompt = self.prompts["system_prompt"]
            section_prompt = self.prompts["sections"].get(section_key, "")
            user_prompt = self._build_user_prompt(section_prompt, llm_facts, reference_context=reference_context)
            llm_client = self._llm_client_for_request()
            response = llm_client.chat_completion(system_prompt, user_prompt, structured_output=True)
            content = self._extract_response_content(response)
            parsed = self._parse_json_response(content)
        except Exception as exc:
            if not self._should_retry_with_compat_mode(exc):
                self.logger.warning("LLM analysis failed for section %s, fallback enabled: %s", section_key, exc)
                return self._llm_fallback_analysis(section_key, title, facts, started_at, exc)

            try:
                retried = True
                self.logger.info("Retrying LLM analysis for section %s with compatibility mode: %s", section_key, exc)
                compat_prompt = self._build_user_prompt(
                    section_prompt,
                    llm_facts,
                    reference_context=reference_context,
                    compatibility_mode=True,
                )
                compat_response = llm_client.chat_completion(
                    system_prompt,
                    compat_prompt,
                    structured_output=False,
                )
                response = compat_response
                mode = "compat"
                compat_content = self._extract_response_content(compat_response)
                parsed = self._parse_json_response(compat_content)
            except Exception as retry_exc:
                self.logger.warning("LLM analysis failed for section %s, fallback enabled: %s", section_key, retry_exc)
                return self._llm_fallback_analysis(section_key, title, facts, started_at, retry_exc, retried=True)

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        response_summary = self._response_debug_summary(response or {})
        self.logger.info(
            "LLM analysis succeeded for section %s mode=%s elapsed_ms=%s response=%s",
            section_key,
            mode,
            elapsed_ms,
            response_summary,
        )

        return SectionAnalysis(
            section_key=section_key,
            title=title,
            summary=parsed.get("summary", ""),
            insights=parsed.get("insights", []),
            risks=parsed.get("risks", []),
            actions=parsed.get("actions", []),
            metrics=facts,
            metadata={
                "source": "llm",
                "mode": mode,
                "elapsed_ms": elapsed_ms,
                "retried": retried,
                "facts_compacted": llm_facts is not facts,
                "prompt_facts_bytes": len(json.dumps(llm_facts, ensure_ascii=False)),
                "response": response_summary,
            },
        )

    def _facts_for_llm(self, section_key: str, facts: dict[str, Any]) -> dict[str, Any]:
        if section_key != "inventory_diagnosis":
            return facts
        return self._compact_inventory_facts_for_llm(facts)

    def _compact_inventory_facts_for_llm(self, facts: dict[str, Any]) -> dict[str, Any]:
        purchase = facts.get("purchase_analysis", {})
        compact_purchase = {
            "summary_sentence": purchase.get("summary_sentence"),
            "forecast_source": purchase.get("forecast_source"),
            "high_inventory_high_inbound_count": purchase.get("high_inventory_high_inbound_count"),
            "high_inventory_low_inbound_count": purchase.get("high_inventory_low_inbound_count"),
            "model_structure_mismatch_count": purchase.get("model_structure_mismatch_count"),
            "history_evaluations": self._compact_rows(
                purchase.get("history_evaluations", []),
                [
                    "region",
                    "model",
                    "ratio",
                    "future_ratio",
                    "future_usage",
                    "same_period_sales_qty",
                    "opening_ratio",
                    "purchase_risk_level",
                    "sales_qty",
                    "regional_sales_qty",
                    "inventory_qty",
                    "inbound_qty",
                    "inbound_ratio",
                    "regional_ratio",
                    "risk_score",
                    "diagnosis",
                    "decision_comment",
                    "inbound_scenario",
                    "target_inventory_qty",
                    "excess_inventory_qty",
                    "status",
                ],
            ),
            "report_rows": self._compact_rows(
                purchase.get("report_rows", []),
                [
                    "region",
                    "model",
                    "sales_qty",
                    "inventory_qty",
                    "ratio",
                    "inbound_qty",
                    "inbound_ratio",
                    "same_period_sales_qty",
                    "future_usage",
                    "future_ratio",
                ],
            ),
            "future_demand_gaps": self._compact_rows(
                purchase.get("future_demand_gaps", []),
                [
                    "region",
                    "model",
                    "current_inventory",
                    "current_ratio",
                    "future_usage",
                    "future_ratio",
                    "level",
                    "shortage_qty",
                    "suggested_order_qty",
                    "safety_target_ratio",
                ],
            ),
            "model_focus": self._compact_rows(
                purchase.get("model_focus", []),
                [
                    "model",
                    "waste_regions",
                    "shortage_regions",
                    "waste_count",
                    "shortage_count",
                    "waste_qty",
                    "shortage_qty",
                    "max_ratio",
                    "min_future_ratio",
                    "action_summary",
                ],
            ),
            "model_inventory_analysis": self._compact_rows(
                purchase.get("model_inventory_analysis", []),
                [
                    "region",
                    "top_model",
                    "top_share",
                    "secondary_model",
                    "usage_top_model",
                    "usage_top_share",
                    "usage_large_share",
                    "inventory_large_share",
                    "inventory_top_usage_share",
                    "usage_top_inventory_share",
                    "structure_label",
                    "structure_gap_pp",
                    "waste_risk",
                    "structure_comment",
                    "suggestion",
                ],
            ),
        }
        compact_purchase = {key: value for key, value in compact_purchase.items() if value is not None}

        return {
            "inventory_overview": self._compact_mapping(
                facts.get("inventory_overview", {}),
                [
                    "summary_sentence",
                    "status",
                    "ratio",
                    "mom",
                    "yoy",
                    "mom_base_ratio",
                    "yoy_base_ratio",
                    "month_start_ratio",
                    "month_peak_ratio",
                    "plateau_summary_sentence",
                    "blocking_reasons",
                    "source_name",
                ],
            ),
            "regional_status": self._compact_mapping(
                facts.get("regional_status", {}),
                ["summary_sentence", "red_count", "yellow_count", "green_count", "regional_rows"],
            ),
            "purchase_analysis": compact_purchase,
        }

    def _compact_rows(self, rows: Any, keys: list[str]) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            return []
        return [self._compact_mapping(row, keys) for row in rows if isinstance(row, dict)]

    def _compact_mapping(self, row: Any, keys: list[str]) -> dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {key: self._compact_value(row[key]) for key in keys if key in row and row[key] is not None}

    def _compact_value(self, value: Any) -> Any:
        if isinstance(value, float):
            rounded = round(value, 4)
            return int(rounded) if rounded.is_integer() else rounded
        if isinstance(value, list):
            return [self._compact_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._compact_value(item) for key, item in value.items() if key != "raw"}
        return value

    def _llm_client_for_request(self) -> LLMClient:
        clone = getattr(self.llm_client, "clone", None)
        if callable(clone):
            return clone()
        return self.llm_client

    def _llm_fallback_analysis(
        self,
        section_key: str,
        title: str,
        facts: dict[str, Any],
        started_at: float,
        exc: Exception,
        *,
        retried: bool = False,
    ) -> SectionAnalysis:
        analysis = self._fallback_analysis(section_key, title, facts)
        analysis.metadata.update(
            {
                "source": "fallback",
                "llm_attempted": True,
                "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                "retried": retried,
                "error": str(exc),
            }
        )
        return analysis

    def _build_user_prompt(
        self,
        section_prompt: str,
        facts: dict[str, Any],
        *,
        reference_context: dict[str, Any] | None = None,
        compatibility_mode: bool = False,
    ) -> str:
        instruction = (
            "请根据以下结构化事实生成 JSON，对象字段必须包含 "
            "`summary`, `insights`, `risks`, `actions`。"
        )
        instruction += (
            "\n生成结论时必须先判断对象是否为滔搏纸袋相关数据；涉及型号、规格、分类时，"
            "优先使用“滔搏纸袋-型号”的业务表述，不要泛化为普通包装物料。"
            "\n核心问题和管理动作必须使用通俗、可执行的管理语言，避免“仍需追损”、"
            "“停订去化”等过短术语；例如写成“引起管理者关注并考虑执行追损”、"
            "“高库销纸袋停止订购”。"
        )
        if compatibility_mode:
            instruction += "\n只返回 JSON 对象本身，不要使用 Markdown 代码块，也不要补充额外解释。"
        prompt = (
            f"{section_prompt}\n\n"
            f"{instruction}\n\n"
            f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
        )
        if reference_context:
            prompt += (
                "\n\n以下是辅助判断纸袋型号与使用场景的参考资料。"
                "这些资料不是事实统计口径，但在判断型号是否错配、是否存在偏大尺码大袋小用浪费时必须参考；"
                "小尺码占比偏高不能直接归因为使用浪费：\n\n"
                f"{json.dumps(reference_context, ensure_ascii=False, indent=2)}"
            )
        return prompt

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        candidate = content.strip()
        if not candidate:
            raise ValueError("LLM provider returned empty content.")

        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end < 0 or start >= end:
                raise
            parsed = json.loads(candidate[start : end + 1])

        if not isinstance(parsed, dict):
            raise ValueError(f"LLM response JSON must be an object, got {type(parsed).__name__}.")

        return parsed

    def _should_retry_with_compat_mode(self, exc: Exception) -> bool:
        if isinstance(exc, (json.JSONDecodeError, ValueError)):
            return True

        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return status_code in {400, 422}

    def _extract_text_payload(self, payload: Any) -> str | None:
        if isinstance(payload, str):
            return payload

        if isinstance(payload, list):
            text_parts: list[str] = []
            for item in payload:
                text = self._extract_text_payload(item)
                if text:
                    text_parts.append(text)
            return "".join(text_parts) if text_parts else None

        if isinstance(payload, dict):
            for key in ("text", "content", "output_text", "value"):
                text = self._extract_text_payload(payload.get(key))
                if text:
                    return text

        return None

    def _response_debug_summary(self, response: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {"top_keys": list(response.keys())}
        if "id" in response:
            summary["id"] = response.get("id")
        if "model" in response:
            summary["model"] = response.get("model")
        if isinstance(response.get("usage"), dict):
            summary["usage"] = response.get("usage")

        choices = response.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            first_choice = choices[0]
            summary["choice_keys"] = list(first_choice.keys())
            if "finish_reason" in first_choice:
                summary["finish_reason"] = first_choice.get("finish_reason")
            message = first_choice.get("message")
            if isinstance(message, dict):
                summary["message_keys"] = list(message.keys())

        output = response.get("output")
        if isinstance(output, list) and output and isinstance(output[0], dict):
            summary["output_item_keys"] = list(output[0].keys())

        return summary

    def _extract_response_content(self, response: dict[str, Any]) -> str:
        choices = response.get("choices")
        message: dict[str, Any] | None = None
        if isinstance(choices, list) and choices:
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
            if isinstance(message, dict):
                content = self._extract_text_payload(message.get("content"))
                if content:
                    return content

                for key in ("text", "output_text"):
                    extra_text = self._extract_text_payload(message.get(key))
                    if extra_text:
                        return extra_text

            delta = first_choice.get("delta") if isinstance(first_choice, dict) else None
            if isinstance(delta, dict):
                delta_text = self._extract_text_payload(delta.get("content"))
                if delta_text:
                    return delta_text

            for key in ("text", "output_text"):
                choice_text = self._extract_text_payload(first_choice.get(key)) if isinstance(first_choice, dict) else None
                if choice_text:
                    return choice_text

        for key in ("content", "output_text", "output"):
            text = self._extract_text_payload(response.get(key))
            if text:
                return text

        if isinstance(message, dict):
            raise ValueError(
                f"LLM provider returned assistant message without content. summary={self._response_debug_summary(response)}"
            )

        raise ValueError(f"LLM provider response does not contain readable content. summary={self._response_debug_summary(response)}")

    def _fallback_analysis(self, section_key: str, title: str, facts: dict[str, Any]) -> SectionAnalysis:
        if section_key == "paper_bag_diagnosis":
            return SectionAnalysis(
                section_key=section_key,
                title=title,
                summary=facts.get("summary_sentence", "纸袋健康度诊断结论待补充。"),
                insights=[
                    f"共{facts.get('total_regions', 0)}个大区参与诊断，"
                    f"红灯{facts.get('red_count', 0)}个、黄灯{facts.get('yellow_count', 0)}个、绿灯{facts.get('green_count', 0)}个。",
                ],
                risks=[
                    "红灯大区存在使用浪费或库存结构失衡，需优先关注。",
                    "黄灯大区存在一定偏差，建议跟踪是否持续恶化。",
                ],
                actions=[
                    "对红灯大区逐区展开尺码级偏差分析，制定订购调整和使用整改计划。",
                    "将黄灯大区纳入下月重点关注范围。",
                ],
                metrics=facts,
                metadata={"source": "fallback", "llm_attempted": False},
            )
        if section_key == "inventory_diagnosis":
            overview = facts["inventory_overview"]
            regional = facts["regional_status"]
            purchase = facts["purchase_analysis"]
            return SectionAnalysis(
                section_key=section_key,
                title=title,
                summary=overview["summary_sentence"],
                insights=[
                    regional["summary_sentence"],
                    purchase["summary_sentence"],
                ],
                risks=[
                    "若红灯地区数量持续偏高，说明库存周转与采购节奏存在偏差。",
                    "若超额订购风险与高库销地区重叠，需优先复核地区订购策略。",
                ],
                actions=[
                    "优先关注红灯地区及高库销型号，按未来30天预测核减超额库存。",
                    "对存在次月需求缺口的地区型号补足具体数量，并形成跟踪清单。",
                ],
                metrics=facts,
                metadata={"source": "fallback", "llm_attempted": False},
            )
        consumption = facts["consumption_exceptions"]
        stocktake = facts["stocktake_risks"]
        return SectionAnalysis(
            section_key=section_key,
            title=title,
            summary=consumption["summary_sentence"],
            insights=[
                stocktake["summary_sentence"],
                f"当前重点门店数量为 {len(stocktake['focus_stores'])}。",
            ],
            risks=[
                "若异常订单、异常门店与盘亏门店重叠，说明存在管理闭环风险。",
                "需要持续监控配比控制后是否出现通过盘点调整掩盖异常的情况。",
            ],
            actions=[
                "对异常门店清单进行地区责任人分派，并要求逐店复核。",
                "将高风险门店纳入下月重点盘点与销账复盘范围。",
            ],
            metrics=facts,
            metadata={"source": "fallback", "llm_attempted": False},
        )
