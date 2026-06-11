# 联调说明

## 当前项目范围

项目已经收敛到 10 张卡片：

- 8 张通过观远 API 获取
- 2 张仅通过本地 Excel 兜底

详细卡片清单见 [README.md](../README.md)。

## 已确认的接口口径

### `xe5da9d423db44bbe96028ad`

- 使用动态参数传入同期、本期起止日期
- 当前与本地卡片集合为 `near_match`
- 差异仅为个别大区 `±1` 和极小浮点精度差

### `l6e08fdcc7fef45ccaa31d1b`

- 使用当月日期范围
- 当前与本地卡片集合 `exact_match`

### `a597c4441b7414c93a7c502d`

- 使用 `滔搏纸袋分类 IN [XS,S,M,L,XL]`
- 使用动态参数传入同期、本期起止日期
- 当前与本地卡片集合为 `near_match`
- 差异仅为个别大区 `±1` 和极小浮点精度差

### `qd0651b4b8bc944e88a6d1f0`

- 不能使用原始 `BT` 日期过滤
- 项目当前改为：
  - `盘点日 GE 2024-03-01`
  - `盘点日 LE {{report_month_end}}`
- 当前与本地卡片集合 `exact_match`

### `j21833508e589464c922d381`

- 必须使用 `view=GRID`
- 使用动态参数传入同期、本期起止日期
- 当前与本地卡片集合为 `near_match`
- 本地 Excel 多出的 `纸袋配比-同期 / 纸袋配比-同比` 属于衍生列，不再视为异常

### `l1d70dacd48c3422d9f7f67c`

- 不再追加纸袋分类过滤
- 保留总计、滔搏、非滔搏全部口径
- 当前与本地卡片集合 `exact_match`

### `d01d19a06c98445008a49a3f`

- 当前日期窗口为 `{{previous_month_start}} ~ {{report_month_end}}`
- 当前与本地卡片集合 `exact_match`

### `nb692ce19d26a49569de3ca8`

- 当前与本地卡片集合 `exact_match`
- 本地异常 `2323` 财年零值行已在本地归一化中剔除

## 本地兜底卡片

### `u114a0c72ae524037a53c8d1`

- 不再走远程卡片接口
- 直接读取本地 Excel

### `b0432cceaa1944241be3f0dc`

- 仅使用本地 Excel

## 最新对比结论

推荐查看：

- [cmp2605nearmatch_api_local_compare.md](../data/processed/inspection/2026-05/cmp2605nearmatch_api_local_compare.md)

状态分布：

- `exact_match`: 5
- `near_match`: 3
- `problem_cards`: 0

`near_match` 判定规则：

- 整数差值 `<= 1`
- 浮点差值 `<= 0.00005`
- 明确允许的本地衍生列不会作为异常计入
