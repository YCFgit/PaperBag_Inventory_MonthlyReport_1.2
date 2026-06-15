# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperBag Inventory Monthly Report 1.2 — 滔搏体育（TopSports）纸袋库存月报自动化系统。每月自动从观远 BI 拉取纸袋相关数据卡片，经过清洗、标准化、指标计算、LLM 分析后生成结构化 Markdown 月报，通过钉钉/OpenClaw 投递。

## Commands

```bash
# 环境准备（首次）
cd /Users/ycf/Documents/OpenClaw/PaperBag_Inventory_MonthlyReport_1.2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 校验配置
python -m src.main validate-config

# 手动生成指定月份报告
python -m src.main run-once --month 2026-03

# 联调模式（跳过 LLM 分析和钉钉发送）
PAPER_BAG_RUNTIME_DIR=/tmp/paper_bag_monthly_report \
python -m src.main run-once --month 2026-03 --skip-llm --skip-send

# 按月定时运行（默认每月1号09:00 Asia/Shanghai）
python -m src.main schedule

# 联调勘测单张卡片
python -m src.main inspect-card --month 2026-03 --card-id u5ced9a38526c4daa8720dd3

# 基于最近原始包做离线字段检查
python -m src.main inspect-latest-raw --month 2026-03

# 批量巡检全部卡片
python -m src.main inspect-all-cards --month 2026-03

# 重跑已归档的原始数据
python -m src.main replay-raw --raw-file data/raw/2026-03/<run_id>/<file>.json --skip-llm --skip-send
```

## Architecture

系统采用分层管道架构，`src/main.py` 中的 `run_pipeline()` 是核心入口，串联以下阶段：

1. **认证** → `AuthClient`（OAuth2 client_credentials）+ `TokenService`（带缓存/自动刷新）
2. **拉取卡片** → `CardService` 按 `cards.yaml` 配置批量请求观远 BI 数据卡片，原始响应归档到 `data/raw/`
3. **标准化** → `TransformService` 将各种卡片格式统一为 `NormalizedDataset`（兼容 `rows`/`rowList`/`list`）
4. **兜底补充** → `CardCollectionFallbackService` 对报错/空卡片尝试从本地 xlsx 兜底；`SupplementalDataService` 加载预测表和纸袋规格表
5. **范围过滤** → `ScopeFilterService` 按地区/品牌白名单本地过滤（不推送远端筛选，避免观远 500）
6. **指标计算** → `MetricsService` 计算库销比、红黄绿灯、异常门店列表等，生成 `report_facts` 结构化事实
7. **健康度诊断** → `DiagnosisService` 读取理论需求 CSV/JSON，并优先从 a597 规范化卡片数据透视近30天销售量和期末业务库存量，生成第六章诊断事实
8. **LLM 分析** → `AnalysisService` 将 facts 传给 LLM（按章节 prompt 生成经营洞察 JSON）
9. **报告渲染** → `ReportService` 用 Jinja2 模板（`config/report_template.md.j2`）渲染 Markdown
10. **投递** → `SendService` 优先走 OpenClaw API，失败回退钉钉 Webhook

所有中间产物按 `data/processed/{normalized,facts,delivery,inspection}/<month>/<run_id>.json` 归档，便于回溯和排障。

## Key Modules

- `src/models/schemas.py` — 全部数据模型定义（`AppConfig`、`CardConfig`、`NormalizedDataset`、`ReportDocument` 等），是理解系统数据结构的核心入口
- `src/services/metrics_service.py` — 核心业务规则计算（库销比阈值判定、地区分级、异常识别），字段候选规则在此维护
- `src/services/diagnosis_service.py` — 第六章“纸袋使用合规率与库存健康度诊断”计算逻辑；理论需求来自 SQL/CSV，实际消耗和期末库存优先来自 a597 地区×型号卡片透视，旧版实际/库存 SQL 仅兜底
- `src/services/analysis_service.py` — LLM 分析调度，按章节组装 prompt 并解析 JSON 响应
- `src/utils/template.py` — 嵌套模板变量渲染（`{{变量名}}` 形式），用于 cards.yaml 中的时间范围等动态参数
- `src/utils/config.py` — YAML 配置加载，环境变量覆盖逻辑
- `src/utils/date_helper.py` — 月份解析和各种日期范围计算（报告月、上月、去年同期、滚动30天）

## Configuration Files

- `config/app.yaml` — 主配置：观远 BI 连接信息、LLM 配置、钉钉配置、调度 cron、存储路径、地区/品牌白名单、补充数据路径
- `config/cards.yaml` — 数据卡片配置（18张卡片）：支持 `preset_refs` 引用公共筛选器预设、模板变量 `{{report_month_start}}` 等、`local_only` 标记仅用本地数据的卡片
- `config/thresholds.yaml` — 业务判定阈值（库销比红灯 3.5/黄灯 2.5、盘差率上限 5%、盘亏金额上限 1000 元等）
- `config/prompts.yaml` — LLM 系统提示词和章节分析提示词，约束输出结构化 JSON 和表达风格
- `config/field_aliases.yaml` — 字段别名映射（兼容观远卡片字段命名差异）
- `config/report_template.md.j2` — Jinja2 报告模板，含 HTML 表格、Mermaid 图表占位符、彩色标签卡片宏
- `config/sql/diagnosis_theory_demand.sql` — 第六章理论需求量取数 SQL
- `config/sql/diagnosis_actual_consumption.sql` — 第六章旧版实际消耗量兜底 SQL；主入口已切换为 a597 卡片 `期末近30天累计纸袋销售量`
- `config/sql/diagnosis_inventory.sql` — 第六章旧版月末库存量兜底 SQL；主入口已切换为 a597 卡片 `期末业务库存量`

## Important Constraints

**观远 BI 接口限制（已验证 2026-04-09）：** 多张卡片在追加 filters 后返回 `500 / None.get`，因此当前采用"不推送远端筛选 + 本地标准化后过滤"策略。修改卡片筛选逻辑前务必参考 `docs/integration_notes.md` 中的已验证行为。

**环境变量覆盖：** `config/app.yaml` 中的敏感字段（client_secret、llm_api_key、dingtalk_app_secret 等）通过 `.env` 文件覆盖，`.env.example` 列出了所有可用变量。

**报告月默认推导规则：** 默认取上月作为报告月（如当前 2026-06 则报告 2026-05），可通过 `--month YYYY-MM` 显式指定。

**PAPER_BAG_RUNTIME_DIR：** 设置此环境变量可将运行时产物（日志、原始数据、报告）输出到指定目录，适配联调和受限环境。

**第六章实际/库存来源：** 实际消耗量和期末库存量优先来自 `a597c4441b7414c93a7c502d`（`regional_model_purchase_analysis`），API 优先、同月卡片集合 Excel 兜底。程序按 `滔搏纸袋分类`/`型号`/`pro_code` 识别尺码并透视为 XS/S/M/L/XL；编码识别映射为 `ZD010XS/ZD2023XS -> xs`、`ZD010S/ZD2023S -> s`、`ZD010M/ZD2023M -> m`、`ZD010L/ZD2023L -> l`、`ZD010XL/ZD2023XL -> xl`。合计、小计、总公司、其他等行不进入实际消耗和期末库存诊断字段。

## Docs

- `docs/integration_notes.md` — 观远 BI 真实接口行为联调记录，包含字段口径确认和接口兼容性说明
- `docs/self_optimization_notes.md` — 已落地的优化点和下一轮建议
- `docs/cards_filter_examples.md` — 卡片筛选器模板变量示例
