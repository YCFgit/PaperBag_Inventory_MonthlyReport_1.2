# 第六模块“小袋多用”SQL实现逻辑与字段映射说明

## 1. 文档目的

本文说明以下 3 条 SQL 的具体实现逻辑，以及它们接入月报第六模块时各输出字段会如何使用：

- `config/sql/diagnosis_small_bag_overuse_summary.sql`
- `config/sql/diagnosis_small_bag_overuse_size_breakdown.sql`
- `config/sql/diagnosis_small_bag_overuse_combo_pattern.sql`

适用模块：

- `六、纸袋使用合规率与库存健康度诊断（AI驱动）`


## 2. 先说明当前状态

当前第六模块已经正式接入的是：

- 理论需求量
- 实际消耗量
- 月末库存量

它们用于计算：

- 综合得分
- 使用合规率得分
- 库存健康度得分
- 红黄绿灯

当前代码中的第六模块主渲染入口在：

- `config/report_template.md.j2`
- `src/services/diagnosis_service.py`
- `src/services/report_service.py`

目前这 3 条“小袋多用”SQL已经落盘，但**还没有接进诊断服务的正式计算链路**。因此，本文中的“怎么用”分两层：

1. 当前第六模块里可以接入的位置
2. 接入后每个字段建议承担的职责

也就是说，下面的字段映射是**落地建议口径**，不是“当前代码已经全部实现”的状态说明。


## 3. 第六模块当前的数据输出结构

第六模块最终渲染时，核心会使用这些诊断字段：

- `diagnosis_ranking`
  - 用于“大区纸袋健康度综合排名”
- `problem_light_details`
  - 用于红灯/黄灯大区展开详情
- `yellow_light_summary`
  - 用于黄灯大区简要提示
- `summary_sentence`
  - 用于“一句话概述”
- `usage_diagnosis`
  - 用于“使用合规诊断”
- `stock_diagnosis`
  - 用于“库存健康诊断”
- `priority_actions`
  - 用于“优先行动”

从业务口径上看，这 3 条“小袋多用”SQL主要影响的是：

- `usage_diagnosis.label`
- `usage_diagnosis.summary`
- `usage_diagnosis.extra_cost`
- `yellow_light_summary.usage_issue`
- `summary_sentence`
- `priority_actions`

它们**不直接参与综合得分计算**。综合得分仍由理论/实际/库存三张聚合表计算。


## 4. SQL 一：小袋多用总览

文件：

- `config/sql/diagnosis_small_bag_overuse_summary.sql`

### 4.1 这条 SQL 解决什么问题

这条 SQL 用来回答 3 个核心问题：

1. 某个大区在报告月里是否存在“小袋多用”
2. 这个问题的严重程度如何
3. 三个子类型各占多少

它是第六模块里“小袋多用”诊断的**总控表**。

### 4.2 实现逻辑

#### 第 1 层：`src_orders`

从运筹结果表读取订单级理论用袋和实际用袋，通过组织维表映射到大区。

| 输入字段 | 输出字段 | 说明 |
| --- | --- | --- |
| `t.period_sdate` | `period` | 统一为 `YYYY-MM` 格式 |
| `t.order_no` / `t.id` | `order_key` | 订单主键，优先取 `order_no`，为空时取 `id` |
| `t.opt_xs/s/m/l/xl` | `opt_xs/s/m/l/xl` | 理论用袋量，`COALESCE` 兜底为 0 |
| `t.orig_xs/s/m/l/xl` | `orig_xs/s/m/l/xl` | 实际用袋量，`COALESCE` 兜底为 0 |
| `t.cost`、`t.opt_cost` | `extra_cost` | `GREATEST(cost - opt_cost, 0)`，订单级额外成本 |
| `d.big_region_name` | `region` | 门店 → 大区映射 |

下游依赖：`region` 是所有后续聚合的主键维度；`order_key` 是计数去重的主键；`extra_cost` 是成本汇总的原子。

#### 第 2 层：`base_orders`

只保留 `${report_month}` 当月订单。

过滤条件：`period = '${report_month}'`

下游依赖：确保所有后续层只分析当月数据，不会混入历史月。

#### 第 3 层：`classified_orders`

对每一单计算总量并打三个布尔标记，是下游分型的**信号层**。

| 计算字段 | 公式 | 业务含义 |
| --- | --- | --- |
| `opt_total` | `opt_xs + opt_s + opt_m + opt_l + opt_xl` | 理论总袋数 |
| `orig_total` | `orig_xs + orig_s + orig_m + orig_l + orig_xl` | 实际总袋数 |
| `delta_total` | `orig_total - opt_total` | 实际比理论多用（正=多用，负=少用） |

| 标记字段 | 判断条件 | 业务含义 |
| --- | --- | --- |
| `has_increase` | 任一尺码 `orig_i > opt_i` → 1 | 有尺码被多用了 |
| `has_decrease` | 任一尺码 `orig_i < opt_i` → 1 | 有尺码被少用了（可能被替代） |
| `has_new_added_size` | 任一尺码 `opt_i = 0 且 orig_i > 0` → 1 | 出现了理论上不该有的全新尺码 |

下游依赖：`delta_total > 0` 是筛选小袋多用订单的门槛；三个标记是 `small_bag_orders` 分型的唯一依据。

#### 第 4 层：`small_bag_orders`

只保留 `delta_total > 0` 的订单（实际总袋数 > 理论总袋数），并按 V1.3 规则分型。

| 分型 | 条件 | 业务含义 |
| --- | --- | --- |
| `组合替代型` | `delta_total > 0` 且 `has_decrease = 1` 且 `has_increase = 1` | 有尺码减少同时有尺码增加 → 用小袋替代大袋 |
| `加袋型` | `delta_total > 0` 且 `has_decrease = 0` 且 `has_new_added_size = 1` | 没有尺码减少但出现新增尺码 → 额外加袋 |
| `纯粹多袋型` | `delta_total > 0`（其余） | 既没有减少也没有新增尺码 → 单纯多用 |

新增输出字段：`small_bag_type`（枚举值：`组合替代型` / `加袋型` / `纯粹多袋型`）

下游依赖：`small_bag_type` 是所有后续聚合和子类型拆分的分类维度。

#### 第 5 层：`all_orders`

按 `region + period` 统计总订单数，作为小袋多用占比的分母。

| 聚合字段 | 公式 | 用途 |
| --- | --- | --- |
| `total_order_cnt` | `COUNT(DISTINCT order_key)` | 小袋多用订单占比的分母 |

下游依赖：与 `small_bag_summary` 左连接，保证没有小袋多用订单的大区也能输出 0。

#### 第 6 层：`small_bag_summary`

按 `region + period` 汇总小袋多用的总量和三个子类型的拆分量。

| 聚合字段 | 公式 | 用途 |
| --- | --- | --- |
| `small_bag_order_cnt` | `COUNT(DISTINCT order_key)` | 小袋多用订单数 |
| `small_bag_extra_bag_qty` | `SUM(delta_total)` | 额外袋数总计 |
| `small_bag_extra_cost` | `SUM(extra_cost)` | 额外成本总计 |
| `add_order_cnt` | `COUNT(DISTINCT order_key) WHERE type='加袋型'` | 加袋型订单数 |
| `replace_order_cnt` | `COUNT(DISTINCT order_key) WHERE type='组合替代型'` | 组合替代型订单数 |
| `pure_order_cnt` | `COUNT(DISTINCT order_key) WHERE type='纯粹多袋型'` | 纯粹多袋型订单数 |
| `add_extra_bag_qty` | `SUM(delta_total) WHERE type='加袋型'` | 加袋型额外袋数 |
| `replace_extra_bag_qty` | `SUM(delta_total) WHERE type='组合替代型'` | 组合替代型额外袋数 |
| `pure_extra_bag_qty` | `SUM(delta_total) WHERE type='纯粹多袋型'` | 纯粹多袋型额外袋数 |
| `add_extra_cost` | `SUM(extra_cost) WHERE type='加袋型'` | 加袋型额外成本 |
| `replace_extra_cost` | `SUM(extra_cost) WHERE type='组合替代型'` | 组合替代型额外成本 |
| `pure_extra_cost` | `SUM(extra_cost) WHERE type='纯粹多袋型'` | 纯粹多袋型额外成本 |

下游依赖：与 `all_orders` 左连接后进入最终 SELECT。

#### 第 7 层：最终输出

把 `all_orders` 和 `small_bag_summary` 左连接，保证：

- 即使某大区没有小袋多用订单，也能保留该大区并输出 0

最终 SELECT 还计算了占比字段：

| 计算字段 | 公式 | 用途 |
| --- | --- | --- |
| `small_bag_order_ratio` | `small_bag_order_cnt / total_order_cnt` | 小袋多用订单占比，决定是否触发诊断（门槛 `> 10%`） |
| `add_order_ratio_in_small_bag` | `add_order_cnt / small_bag_order_cnt` | 加袋型占小袋多用订单比例 |
| `replace_order_ratio_in_small_bag` | `replace_order_cnt / small_bag_order_cnt` | 组合替代型占小袋多用订单比例 |
| `pure_order_ratio_in_small_bag` | `pure_order_cnt / small_bag_order_cnt` | 纯粹多袋型占小袋多用订单比例 |

### 4.3 输出字段逐字段说明

| 字段 | 含义 | 第六模块里的建议用途 |
| --- | --- | --- |
| `region` | 大区 | 作为第六模块按大区关联的主键 |
| `period` | 月份 | 与第六模块报告月对齐 |
| `total_order_cnt` | 大区当月总订单数 | 主要用于审计、复核分母；通常不直接渲染 |
| `small_bag_order_cnt` | 小袋多用订单数 | 支撑“识别出多少单存在未合并装袋” |
| `small_bag_order_ratio` | 小袋多用订单占比 | 决定是否触发“未合并装袋（小袋多用）”诊断；建议门槛 `> 10%` |
| `small_bag_extra_bag_qty` | 小袋多用导致的额外袋数总计 | 用于内部诊断和动作优先级，不一定直接在月报里展示 |
| `small_bag_extra_cost` | 小袋多用额外成本总计 | 直接用于 `usage_diagnosis.extra_cost` 和文案中的“月度额外成本约¥X,XXX” |
| `add_order_cnt` | 加袋型订单数 | 用于子类型占比计算 |
| `replace_order_cnt` | 组合替代型订单数 | 用于子类型占比计算 |
| `pure_order_cnt` | 纯粹多袋型订单数 | 用于子类型占比计算 |
| `add_order_ratio_in_small_bag` | 加袋型占小袋多用订单比例 | 决定是否展开“加袋型”描述；建议门槛 `> 10%` |
| `replace_order_ratio_in_small_bag` | 组合替代型占小袋多用订单比例 | 决定是否展开“组合替代型”描述；建议门槛 `> 10%` |
| `pure_order_ratio_in_small_bag` | 纯粹多袋型占小袋多用订单比例 | 决定是否展开“纯粹多袋型”描述；建议门槛 `> 10%` |
| `add_extra_bag_qty` | 加袋型额外袋数总计 | 用于“额外多用了 S 码 12,000 个”这类文案的数量基础 |
| `replace_extra_bag_qty` | 组合替代型额外袋数总计 | 用于组合替代型的总量描述 |
| `pure_extra_bag_qty` | 纯粹多袋型额外袋数总计 | 用于“多用了 S 码 6,000 个”这类文案的总量背景 |
| `add_extra_cost` | 加袋型额外成本 | 可用于子类型成本拆分，通常不必单独渲染 |
| `replace_extra_cost` | 组合替代型额外成本 | 可用于组合替代型成本拆分 |
| `pure_extra_cost` | 纯粹多袋型额外成本 | 可用于纯粹多袋型成本拆分 |

### 4.4 在第六模块中的推荐接法

#### 用于“使用合规诊断”

建议接入 `usage_diagnosis`：

- 当 `small_bag_order_ratio <= 0.10`
  - 不触发“小袋多用”诊断
- 当 `small_bag_order_ratio > 0.10`
  - 生成：
    - `usage_diagnosis.label = 未合并装袋（小袋多用）`
    - `usage_diagnosis.extra_cost = small_bag_extra_cost`
    - `usage_diagnosis.summary` 里写入：
      - 小袋多用订单占比
      - 展开的子类型
      - 月度额外成本

#### 用于“黄灯大区简要提示”

建议优先使用：

- `small_bag_order_ratio`
- 三个 `*_order_ratio_in_small_bag`
- `small_bag_extra_cost`

生成类似：

> 小袋多用占比 18%，主要类型为加袋型（占比 45%），月度额外成本约 ¥2,100

#### 用于“一句话概述”

可以统计：

- 有多少大区 `small_bag_order_ratio > 10%`
- 哪些大区问题最严重

生成类似：

> 本月 3 个大区存在明显未合并装袋问题，主要集中在华西区、华南一区。


## 5. SQL 二：小袋多用尺码归因明细

文件：

- `config/sql/diagnosis_small_bag_overuse_size_breakdown.sql`

### 5.1 这条 SQL 解决什么问题

这条 SQL 不负责判断“有没有小袋多用”，而是回答：

1. 每个子类型里，究竟是哪些尺码在增加
2. 组合替代型里，哪些尺码在减少
3. 哪个尺码最值得在文案里点名

它是第六模块“小袋多用”诊断的**归因明细表**。

### 5.2 实现逻辑

前半段与总览 SQL 基本一致：

- `src_orders` → 同 SQL 一（字段映射见 4.2 节第 1 层）
- `base_orders` → 同 SQL 一（过滤当月）
- `classified_orders` → 与 SQL 一略有不同：本条 SQL **不计算** `opt_total`、`orig_total`、`has_increase`、`has_new_added_size`，只计算 `delta_total` 和 `has_decrease`，因为后续只需判断有无尺码减少
- `small_bag_orders` → 分型逻辑与 SQL 一相同，但判断 `组合替代型` 时直接内联尺码比较而非依赖 `has_increase` 标记

不同点在后半段。

#### 第 1 层：`delta_rows`

把每单的 5 个尺码横表拆成纵表（行转置）。

| 输入字段 | 输出字段 | 说明 |
| --- | --- | --- |
| `orig_xs - opt_xs` | `raw_delta`（bag_size = 'XS'） | XS 尺码差值 |
| `orig_s - opt_s` | `raw_delta`（bag_size = 'S'） | S 尺码差值 |
| `orig_m - opt_m` | `raw_delta`（bag_size = 'M'） | M 尺码差值 |
| `orig_l - opt_l` | `raw_delta`（bag_size = 'L'） | L 尺码差值 |
| `orig_xl - opt_xl` | `raw_delta`（bag_size = 'XL'） | XL 尺码差值 |

每个订单从 1 行变成 5 行（每个尺码一行）。

下游依赖：`raw_delta` 的正负值决定 `typed_delta_rows` 的 `increase` / `decrease` 角色。

#### 第 2 层：`typed_delta_rows`

把 `raw_delta` 拆成两个角色，并统一为正数。

| 输出字段 | 来源 | 说明 |
| --- | --- | --- |
| `delta_role = 'increase'` | `raw_delta > 0` | 该尺码被多用了 |
| `delta_role = 'decrease'` | `raw_delta < 0` | 该尺码被少用了/被替代了 |
| `delta_qty` | `increase` 取原值，`decrease` 取 `-raw_delta` | 统一为正数，方便聚合 |

下游依赖：`delta_role` 是聚合时区分"多用尺码"和"被替代尺码"的关键维度。

#### 第 3 层：`agg`

按 `region + period + small_bag_type + delta_role + bag_size` 汇总。

| 聚合字段 | 公式 | 用途 |
| --- | --- | --- |
| `order_cnt` | `COUNT(DISTINCT order_key)` | 出现该尺码差异的订单数，用于判断现象是否稳定 |
| `delta_qty` | `SUM(delta_qty)` | 该尺码总差值量，直接用于"多用了 S 码 12,000 个"这类文案 |

下游依赖：进入最终 SELECT 计算占比。

#### 第 4 层：最终输出

计算 `qty_ratio_in_type`，决定哪个尺码值得在文案中展开。

| 计算字段 | 公式 | 用途 |
| --- | --- | --- |
| `qty_ratio_in_type` | `delta_qty / SUM(delta_qty) OVER (PARTITION BY region, period, small_bag_type, delta_role)` | 某尺码在当前子类型、当前角色中的数量占比，门槛 `> 30%` 时展开 |

示例：若华西区组合替代型 `increase` 中 M 码占比 45%，则文案展开为"主要多用 M 码"。

### 5.3 输出字段逐字段说明

| 字段 | 含义 | 第六模块里的建议用途 |
| --- | --- | --- |
| `region` | 大区 | 与总览表按大区关联 |
| `period` | 月份 | 与报告月对齐 |
| `small_bag_type` | 子类型：加袋型 / 组合替代型 / 纯粹多袋型 | 决定该行属于哪类小袋多用现象 |
| `delta_role` | `increase` 或 `decrease` | `increase` 用于“多用了哪些尺码”；`decrease` 用于“少用了哪些尺码/被替代了哪些尺码” |
| `bag_size` | 尺码 | 直接决定文案里点名的尺码 |
| `order_cnt` | 出现该尺码差异的订单数 | 用于辅助判断现象是否稳定，不一定直接渲染 |
| `delta_qty` | 该尺码总差值量 | 直接用于“多用了 S 码 12,000 个”这类文案 |
| `qty_ratio_in_type` | 该尺码在当前子类型、当前角色中的数量占比 | 决定是否达到“型号展开阈值”；建议门槛 `> 30%` |

### 5.4 在第六模块中的推荐接法

#### 加袋型

只看：

- `small_bag_type = '加袋型'`
- `delta_role = 'increase'`

再按 `qty_ratio_in_type` 排序：

- 若某尺码占比 `> 30%`
  - 文案展开为：
    - “主要表现为额外多加 S 码”
- 若都未过门槛
  - 文案只保留：
    - “现象较分散，未形成突出尺码”

#### 纯粹多袋型

只看：

- `small_bag_type = '纯粹多袋型'`
- `delta_role = 'increase'`

规则同上，用于生成：

- “主要表现为 S 码多用 6,000 个”

#### 组合替代型

可以分两部分使用：

1. `delta_role = 'increase'`
   - 看替代后的目标尺码
2. `delta_role = 'decrease'`
   - 看被替代掉的原尺码

但真正要生成“XL 被 M+L 替代”这种句子，更适合结合第三条 SQL 来做。


## 6. SQL 三：组合替代型模式识别

文件：

- `config/sql/diagnosis_small_bag_overuse_combo_pattern.sql`

### 6.1 这条 SQL 解决什么问题

这条 SQL 专门面向 `组合替代型`，用于识别：

- 哪个原尺码被替代
- 被替代成了什么组合
- 哪种替代模式最常见

它是第六模块里“组合替代型”子文案的**模式识别表**。

### 6.2 实现逻辑

前半段仍然与前两条 SQL 类似：

- `src_orders` → 同 SQL 一（字段映射见 4.2 节第 1 层）
- `base_orders` → 同 SQL 一（过滤当月）
- `classified_orders` → 与 SQL 二相同，只计算 `delta_total` 和 `has_decrease`，不计算 `has_increase` / `has_new_added_size`，因为后续只需筛选组合替代型

#### 第 1 层：`combo_orders`

从 `classified_orders` 中只保留组合替代型订单。

| 过滤条件 | 说明 |
| --- | --- |
| `delta_total > 0` | 实际总袋数 > 理论总袋数 |
| 任一尺码 `orig_i < opt_i` | 有尺码减少（被替代） |
| 任一尺码 `orig_i > opt_i` | 有尺码增加（替代后） |

三个条件同时满足 = 组合替代型。下游依赖：所有后续层都只分析组合替代型订单。

#### 第 2 层：`delta_rows`

与 SQL 二的 `delta_rows` 逻辑相同，把 5 个尺码横表拆成纵表。

| 输入字段 | 输出字段 | 说明 |
| --- | --- | --- |
| `orig_i - opt_i` | `raw_delta` | 每个尺码的差值，正=多用，负=少用 |
| — | `bag_size` | 尺码枚举：XS / S / M / L / XL |
| — | `extra_cost` | 从 `combo_orders` 透传，用于后续成本汇总 |

下游依赖：`raw_delta` 的正负值分流到 `combo_increase` 和 `combo_decrease`。

#### 第 3 层：`combo_increase`

把同一订单中所有 `raw_delta > 0`（多用）的尺码拼成一个签名字符串。

| 输出字段 | 拼接逻辑 | 示例 |
| --- | --- | --- |
| `replaced_to` | `CONCAT_WS('+', SORT_ARRAY(COLLECT_LIST(CONCAT(bag_size, 'x', delta))))` | `Mx1+Lx1` |

- `SORT_ARRAY` 保证相同组合总是相同顺序（确定性签名）
- `GROUP BY region, period, order_key` → 每个订单一行

下游依赖：`replaced_to` 表示替代后的实际组合，是最终模式签名的一半。

#### 第 4 层：`combo_decrease`

把同一订单中所有 `raw_delta < 0`（少用）的尺码拼成一个签名字符串。

| 输出字段 | 拼接逻辑 | 示例 |
| --- | --- | --- |
| `replaced_from` | `CONCAT_WS('+', SORT_ARRAY(COLLECT_LIST(CONCAT(bag_size, 'x', -delta))))` | `XLx1` |

- 注意 `-delta`：因为 `raw_delta` 是负数，取反后为正数

下游依赖：`replaced_from` 表示被替代掉的理论组合，是最终模式签名的另一半。

#### 第 5 层：`combo_pattern`

把 `combo_increase` 和 `combo_decrease` 按订单内连接，拼回一条完整的替代模式记录。

| 连接 | 关联键 | 输出 |
| --- | --- | --- |
| `combo_increase` INNER JOIN `combo_decrease` | `region + period + order_key` | `replaced_from` + `replaced_to` |
| INNER JOIN `combo_orders` | `region + period + order_key` | 回带 `extra_cost` |

示例：一个订单 `replaced_from = 'XLx1'`，`replaced_to = 'Mx1+Lx1'` → 表示”XL 被 M+L 替代”。

下游依赖：进入最终 SELECT 按模式聚合。

#### 第 6 层：最终输出

按 `region + period + replaced_from + replaced_to` 聚合，统计每种替代模式的规模。

| 聚合字段 | 公式 | 用途 |
| --- | --- | --- |
| `combo_order_cnt` | `COUNT(DISTINCT order_key)` | 该替代模式订单数，用于选出 Top1 / TopN 模式 |
| `combo_extra_cost` | `SUM(extra_cost)` | 该模式贡献的额外成本 |
| `combo_order_ratio_in_region` | `combo_order_cnt / SUM(combo_order_cnt) OVER (PARTITION BY region, period)` | 该模式占本大区组合替代型订单的比例，决定是否在文案中展开 |

示例输出：

| replaced_from | replaced_to | combo_order_cnt | combo_order_ratio_in_region |
| --- | --- | --- | --- |
| `XLx1` | `Mx1+Lx1` | 85 | 0.42 |
| `Lx1` | `Mx1+Sx1` | 32 | 0.16 |

### 6.3 输出字段逐字段说明

| 字段 | 含义 | 第六模块里的建议用途 |
| --- | --- | --- |
| `region` | 大区 | 与总览表按大区关联 |
| `period` | 月份 | 与报告月对齐 |
| `replaced_from` | 被替代掉的理论组合 | 用于生成“谁被替代了” |
| `replaced_to` | 实际替代后的组合 | 用于生成“被什么替代了” |
| `combo_order_cnt` | 该替代模式订单数 | 用于选出 Top1 / TopN 模式 |
| `combo_extra_cost` | 该模式额外成本 | 用于补充成本解释 |
| `combo_order_ratio_in_region` | 该模式占本大区组合替代型订单的比例 | 决定是否在文案中重点展开 |

### 6.4 在第六模块中的推荐接法

推荐主要用于 `usage_diagnosis.summary` 中“组合替代型”子句的生成。

例如：

- 若 `combo_order_ratio_in_region > 10%`
  - 取 Top1 模式
  - 生成：
    - `XL被M+L替代`
- 若模式分布很散
  - 生成：
    - `组合替代型占22%，各替代模式较分散，未形成突出特征`

注意：

- 这里的 `replaced_from`、`replaced_to` 是技术签名
- 真正渲染时建议把 `XLx1` 格式转换成更自然的中文描述


## 7. 三条 SQL 如何协同支撑第六模块

建议接入顺序如下：

### 第一步：总览判断是否触发

先用 `diagnosis_small_bag_overuse_summary.sql` 判断：

- 这个大区有没有小袋多用
- 小袋多用占比是否超过 10%
- 哪个子类型最重要

这一步决定：

- 是否在第六模块中出现“未合并装袋（小袋多用）”

### 第二步：明细决定点名哪个尺码

再用 `diagnosis_small_bag_overuse_size_breakdown.sql` 判断：

- 哪个尺码最值得展开
- 某个子类型里是 S 码主导，还是 XS 码主导

这一步决定：

- 文案里点名哪个尺码
- 是否写出具体数量

### 第三步：组合替代模式补充自然语言

最后用 `diagnosis_small_bag_overuse_combo_pattern.sql` 判断：

- 替代关系最常见的模式是什么

这一步决定：

- 是否生成“XL被M+L替代”这类句子


## 8. 推荐的第六模块字段落位

建议在诊断服务里新增一段“小袋多用诊断结果”，最终汇入 `usage_diagnosis`。

推荐映射如下：

| 第六模块字段 | 推荐来源 | 用法 |
| --- | --- | --- |
| `usage_diagnosis.label` | `small_bag_order_ratio` | `>10%` 时可置为“未合并装袋（小袋多用）”，或与“大袋小用”并列输出 |
| `usage_diagnosis.summary` | 三条 SQL 联合生成 | 写整体占比、子类型、主尺码/主替代模式、额外成本 |
| `usage_diagnosis.extra_cost` | `small_bag_extra_cost` | 输出“月度额外成本约¥X,XXX” |
| `yellow_light_summary.usage_issue` | `small_bag_order_ratio` + Top1 子类型 | 黄灯大区简述 |
| `summary_sentence` | 汇总各大区 `small_bag_order_ratio` | 全国层一句话概述 |
| `priority_actions` | Top 子类型 + Top 尺码/替代模式 | 生成“加强合包执行”“限制重复领用小袋”等动作建议 |


## 9. 接入时需要特别注意的点

### 9.1 不要让小袋多用参与综合得分重算

这 3 条 SQL 的作用是：

- 增强“使用合规诊断”的业务解释力

它们不是用来重算：

- 使用合规率得分
- 库存健康度得分
- 综合得分

### 9.2 小袋多用与大袋小用可以同时存在

V1.3 文档的口径是：

- 大袋小用
- 小袋多用

可以并行成立。

因此 `usage_diagnosis` 的设计不要被限制成“只能有一个标签”。更稳妥的做法是：

- 保留一个主标签
- 同时允许 `details/findings` 中出现多个问题项

### 9.3 组合替代型的文案不要直接展示技术签名

SQL 输出的：

- `XLx1`
- `Mx1+Lx1`

更适合程序内部排序与匹配。

最终月报里建议转换成自然语言：

- `XL被M+L替代`

### 9.4 `business_type` 过滤仍需业务最终确认

当前 3 条 SQL 中都保留了：

- `-- AND t.business_type IN (...)`

如果后续确认只统计零售订单，需要统一补上，不然“小袋多用占比”会受其他业务类型影响。


## 10. 一句话总结

这 3 条 SQL 的分工非常明确：

- `summary` 负责判断是否触发、问题有多大、哪类最重要
- `size_breakdown` 负责判断该点名哪个尺码
- `combo_pattern` 负责把组合替代型翻译成可读的替代模式

接入第六模块后，它们主要增强的是：

- 使用合规诊断文案
- 黄灯简述
- 一句话概述
- 优先行动

而不是综合评分本身。
