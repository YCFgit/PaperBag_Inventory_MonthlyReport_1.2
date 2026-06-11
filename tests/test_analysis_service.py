import json

from src.services.analysis_service import AnalysisService


class DummyLogger:
    def __init__(self) -> None:
        self.infos: list[tuple[object, ...]] = []
        self.warnings: list[tuple[object, ...]] = []

    def info(self, *args, **_kwargs) -> None:
        self.infos.append(args)

    def warning(self, *_args, **_kwargs) -> None:
        self.warnings.append(_args)


class FakeLLMClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def chat_completion(self, system_prompt: str, user_prompt: str, *, structured_output: bool = True) -> dict:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "structured_output": structured_output,
            }
        )
        if not self.responses:
            raise AssertionError("No more fake responses available")
        return self.responses.pop(0)


def test_analysis_service_extracts_text_from_content_blocks() -> None:
    service = AnalysisService(llm_client=None, prompts={}, enable_llm=False, logger=DummyLogger())
    response = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": '{"summary":"ok","insights":[],"risks":[],"actions":[]}'}
                    ]
                }
            }
        ]
    }

    assert service._extract_response_content(response) == '{"summary":"ok","insights":[],"risks":[],"actions":[]}'


def test_analysis_service_raises_clear_error_when_message_has_no_content() -> None:
    service = AnalysisService(llm_client=None, prompts={}, enable_llm=False, logger=DummyLogger())
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant"
                }
            }
        ]
    }

    try:
        service._extract_response_content(response)
    except ValueError as exc:
        assert "without content" in str(exc)
    else:
        raise AssertionError("Expected ValueError for empty assistant message")


def test_analysis_service_extracts_text_from_responses_output_shape() -> None:
    service = AnalysisService(llm_client=None, prompts={}, enable_llm=False, logger=DummyLogger())
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"summary":"ok","insights":[],"risks":[],"actions":[]}'}
                ],
            }
        ]
    }

    assert service._extract_response_content(response) == '{"summary":"ok","insights":[],"risks":[],"actions":[]}'


def test_analysis_service_retries_with_compat_mode_when_primary_response_is_empty() -> None:
    logger = DummyLogger()
    llm_client = FakeLLMClient(
        responses=[
            {"choices": [{"message": {"role": "assistant"}}]},
            {"choices": [{"message": {"content": '```json\n{"summary":"ok","insights":["i"],"risks":[],"actions":["a"]}\n```'}}]},
        ]
    )
    service = AnalysisService(
        llm_client=llm_client,
        prompts={"system_prompt": "sys", "sections": {"inventory_diagnosis": "section"}},
        enable_llm=True,
        logger=logger,
    )

    analysis = service._analyze_with_llm("inventory_diagnosis", "Title", {"metric": 1})

    assert analysis.summary == "ok"
    assert analysis.insights == ["i"]
    assert analysis.actions == ["a"]
    assert [call["structured_output"] for call in llm_client.calls] == [True, False]
    assert "只返回 JSON 对象本身" in llm_client.calls[1]["user_prompt"]
    assert logger.infos
    assert any("LLM analysis succeeded for section %s mode=%s elapsed_ms=%s response=%s" == entry[0] for entry in logger.infos)


def test_analysis_service_logs_successful_llm_analysis() -> None:
    logger = DummyLogger()
    llm_client = FakeLLMClient(
        responses=[
            {
                "choices": [
                    {
                        "message": {"content": '{"summary":"ok","insights":[],"risks":[],"actions":[]}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        ]
    )
    service = AnalysisService(
        llm_client=llm_client,
        prompts={"system_prompt": "sys", "sections": {"inventory_diagnosis": "section"}},
        enable_llm=True,
        logger=logger,
    )

    service._analyze_with_llm("inventory_diagnosis", "Title", {"metric": 1})

    success_logs = [entry for entry in logger.infos if entry[0] == "LLM analysis succeeded for section %s mode=%s elapsed_ms=%s response=%s"]
    assert len(success_logs) == 1
    assert success_logs[0][1] == "inventory_diagnosis"
    assert success_logs[0][2] == "structured"
    assert isinstance(success_logs[0][3], int)
    assert success_logs[0][4]["finish_reason"] == "stop"


def test_analysis_service_preserves_section_order_when_llm_runs_in_parallel() -> None:
    logger = DummyLogger()
    llm_client = FakeLLMClient(
        responses=[
            {"choices": [{"message": {"content": '{"summary":"first","insights":[],"risks":[],"actions":[]}'}}]},
            {"choices": [{"message": {"content": '{"summary":"second","insights":[],"risks":[],"actions":[]}'}}]},
        ]
    )
    service = AnalysisService(
        llm_client=llm_client,
        prompts={"system_prompt": "sys", "sections": {"a": "section a", "b": "section b"}},
        enable_llm=True,
        logger=logger,
    )

    analyses = service.analyze_sections(
        {
            "sections": {
                "a": {"title": "A", "facts": {"metric": 1}},
                "b": {"title": "B", "facts": {"metric": 2}},
            }
        }
    )

    assert [analysis.section_key for analysis in analyses] == ["a", "b"]
    assert all(analysis.metadata["source"] == "llm" for analysis in analyses)
    assert all("elapsed_ms" in analysis.metadata for analysis in analyses)


def test_analysis_service_includes_reference_context_in_prompt() -> None:
    logger = DummyLogger()
    llm_client = FakeLLMClient(
        responses=[
            {"choices": [{"message": {"content": '{"summary":"ok","insights":[],"risks":[],"actions":[]}'}}]},
        ]
    )
    service = AnalysisService(
        llm_client=llm_client,
        prompts={"system_prompt": "sys", "sections": {"inventory_diagnosis": "section"}},
        enable_llm=True,
        logger=logger,
    )

    service.analyze_sections(
        {
            "sections": {
                "inventory_diagnosis": {
                    "title": "纸袋库销诊断",
                    "facts": {"metric": 1},
                }
            },
            "reference_context": {
                "inventory_diagnosis": {
                    "paper_bag_specs": [
                        {"paper_bag_model": "滔搏纸袋-XL", "usage_scenes": "棉羽；特殊鞋盒"}
                    ]
                }
            },
        }
    )

    assert "辅助判断纸袋型号与使用场景的参考资料" in llm_client.calls[0]["user_prompt"]
    assert "滔搏纸袋-XL" in llm_client.calls[0]["user_prompt"]


def test_inventory_diagnosis_prompt_uses_compacted_llm_facts() -> None:
    logger = DummyLogger()
    llm_client = FakeLLMClient(
        responses=[
            {"choices": [{"message": {"content": '{"summary":"ok","insights":[],"risks":[],"actions":[]}'}}]},
        ]
    )
    service = AnalysisService(
        llm_client=llm_client,
        prompts={"system_prompt": "sys", "sections": {"inventory_diagnosis": "section"}},
        enable_llm=True,
        logger=logger,
    )
    facts = {
        "inventory_overview": {
            "summary_sentence": "库存总览",
            "ratio": 2.123456,
            "trend_series": [{"month": "2026-05", "ratio": 2.1}],
        },
        "regional_status": {
            "summary_sentence": "区域状态",
            "red_count": 1,
            "yellow_count": 2,
            "green_count": 3,
            "regional_rows": [{"region": "华北一区", "ratio": 0.7, "status": "红灯"}],
        },
        "purchase_analysis": {
            "summary_sentence": "采购诊断",
            "forecast_source": "forecast.xlsx",
            "history_evaluations": [
                {
                    "region": "华北一区",
                    "model": "滔搏纸袋-M",
                    "ratio": 2.234567,
                    "decision_comment": "订购偏多",
                    "raw": {"large": "payload"},
                }
            ],
            "joined_rows": [{"raw": {"large": "payload"}, "unused": "drop"}],
            "report_rows": [{"region": "华北一区", "model": "滔搏纸袋-M", "raw": {"large": "payload"}}],
            "future_demand_gaps": [{"region": "华北一区", "model": "滔搏纸袋-M", "shortage_qty": 123.4567}],
            "model_focus": [{"model": "滔搏纸袋-M", "action_summary": "补足缺口"}],
            "model_inventory_analysis": [{"region": "华北一区", "structure_comment": "结构待跟踪"}],
            "model_inventory_pivot": [{"unused": "drop"}],
        },
    }

    analysis = service._analyze_with_llm("inventory_diagnosis", "纸袋库销诊断", facts)

    prompt = llm_client.calls[0]["user_prompt"]
    assert "raw" not in prompt
    assert "joined_rows" not in prompt
    assert "model_inventory_pivot" not in prompt
    assert "trend_series" not in prompt
    assert "滔搏纸袋-M" in prompt
    assert "decision_comment" in prompt
    assert "structure_comment" in prompt
    assert analysis.metrics is facts
    assert analysis.metadata["facts_compacted"] is True
    assert analysis.metadata["prompt_facts_bytes"] < len(json.dumps(facts, ensure_ascii=False))


def test_non_inventory_llm_facts_are_not_compacted() -> None:
    service = AnalysisService(llm_client=None, prompts={}, enable_llm=False, logger=DummyLogger())
    facts = {"raw": {"keep": True}, "metric": 1}

    assert service._facts_for_llm("consumption_exceptions", facts) is facts
