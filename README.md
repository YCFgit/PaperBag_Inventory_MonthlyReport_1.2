# PaperBag Inventory Monthly Report 1.2

纸袋库存月报自动化项目。当前版本已收敛到 10 张卡片，其中 8 张走观远 API，2 张仅使用本地 Excel 兜底。

## 目录

- `config/`: 应用配置、卡片配置、阈值和提示词
- `src/`: 业务代码
- `scripts/`: 辅助脚本
- `tests/`: 测试
- `docs/`: 当前联调说明
- `data/raw/`: 原始接口响应归档
- `data/processed/`: 中间产物、对比结果、缓存
- `data/reports/`: 报告输出

## 当前卡片范围

### API 卡片

1. `xe5da9d423db44bbe96028ad` 大区库销比_不含团购_配合AI月报使用
2. `l6e08fdcc7fef45ccaa31d1b` 店铺订单维度纸袋使用配比明细
3. `a597c4441b7414c93a7c502d` 库销比&进销比-by大区*(滔搏纸袋-分型号)
4. `qd0651b4b8bc944e88a6d1f0` 门店纸袋盘点-by月
5. `j21833508e589464c922d381` 门店纸袋配比[总]-by月
6. `l1d70dacd48c3422d9f7f67c` 门店纸袋使用情况[总]-财年
7. `d01d19a06c98445008a49a3f` 滔搏纸袋库销比历史变化趋势-by日
8. `nb692ce19d26a49569de3ca8` 纸袋盘差表（月度盘差率大于5%）大区图表

### 本地 Excel 卡片

1. `u114a0c72ae524037a53c8d1` 滔搏纸袋订购辅助-未来30天纸袋使用量预测
2. `b0432cceaa1944241be3f0dc` 纸袋盘差表（月度盘差率大于5%）大区维度

## 环境准备

```bash
cd /Users/ycf/Documents/OpenClaw/PaperBag_Inventory_MonthlyReport_1.2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

关键环境变量：

- `GUANYUAN_CLIENT_ID`
- `GUANYUAN_CLIENT_SECRET`
- `GUANYUAN_USER_ID`
- `LLM_API_KEY`
- `DINGTALK_APP_KEY` + `DINGTALK_APP_SECRET` + `DINGTALK_AGENT_ID`（用于钉钉群文件空间上传与 `convFile` 发送）
- `DINGTALK_CORP_ID`（仅在 H5 绑定页初始化 `dd.config` 时需要）

## 常用命令

校验配置：

```bash
python -m src.main validate-config
```

检查钉钉发送链路是否就绪：

```bash
python -m src.main check-dingtalk --month 2026-05
```

按月定时运行：

```bash
python -m src.main schedule
```

默认配置为 `Asia/Shanghai` 时区、每月 `2` 日 `09:00` 触发，并按 `DINGTALK_DELIVERY_MODE=conversation_file_only` 发送 PDF 到钉钉群文件。

启动本地钉钉 JSAPI 签名服务：

```bash
python -m src.main serve-dingtalk-jsapi --host 127.0.0.1 --port 8000
```

启动后可直接打开：

```text
http://127.0.0.1:8000/dingtalk/choose-conversation
```

这个页面会：

- 优先尝试自动读取钉钉客户端里的 `corpId`
- 自动获取 `dd.config` 签名参数
- 让你选择目标钉钉群
- 自动把 `openConversationId` 保存到 `data/processed/dingtalk_binding.json`

目标群绑定只需要做一次。后续定时任务会直接读取这个绑定并自动发送 PDF。

生成指定月份报告：

```bash
python -m src.main run-once --month 2026-05
```

不重跑分析，直接重发已生成的 PDF：

```bash
python -m src.main send-existing-report --month 2026-05
```

跳过 LLM 和发送，仅做数据联调：

```bash
PAPER_BAG_RUNTIME_DIR=/tmp/paper_bag_monthly_report \
python -m src.main run-once --month 2026-05 --skip-llm --skip-send
```

单卡巡检：

```bash
python -m src.main inspect-card --month 2026-05 --card-id xe5da9d423db44bbe96028ad
```

批量对比 API 与本地卡片集合：

```bash
python3 scripts/compare_api_local.py --month 2026-05
```

## 当前关键口径

- `qd0651b4b8bc944e88a6d1f0` 使用 `盘点日 GE 2024-03-01` 与 `LE {{report_month_end}}`
- `j21833508e589464c922d381` 必须使用 `view=GRID`
- `d01d19a06c98445008a49a3f` 使用 `{{previous_month_start}} ~ {{report_month_end}}`
- `l1d70dacd48c3422d9f7f67c` 不再追加纸袋分类过滤，保持与本地导出口径一致

## 本地兜底文件

- 卡片集合目录：`/Users/ycf/Documents/AI纸袋月报/纸袋卡片集合-2605`
- 纸袋规格：`/Users/ycf/Documents/AI纸袋月报/纸袋规格.xlsx`

## 最新对比结果

当前推荐使用：

- [cmp2605nearmatch_api_local_compare.md](data/processed/inspection/2026-05/cmp2605nearmatch_api_local_compare.md)

该结果显示：

- `exact_match`: 5 张
- `near_match`: 3 张
- `problem_cards`: 0 张

`near_match` 仅表示存在 `±1` 或 `1e-5` 级别的可接受精度差，不再视为异常。

## 补充说明

现行联调结论见 [docs/integration_notes.md](docs/integration_notes.md)。
观远卡片 API 的通用介绍、调用方法和多语言示例见 [docs/guanyuan_card_api_operation.md](docs/guanyuan_card_api_operation.md)。
钉钉群 `openConversationId` 的获取说明见 [docs/dingtalk_open_conversation_id.md](docs/dingtalk_open_conversation_id.md)。
