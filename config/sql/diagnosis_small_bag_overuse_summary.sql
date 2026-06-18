-- SQL 4: 大区 × 月份 小袋多用总览
-- 数据源: paimon.dwd_pub.t18_top_paper_bag_opt_price + hive.dws_pub.dws_dim_org_mainfo_ex
-- 口径: 仅识别订单级 orig_total > opt_total 的“小袋多用”订单，按 V1.3 分为加袋型 / 组合替代型 / 纯粹多袋型。
WITH src_orders AS (
    SELECT
        d.big_region_name AS region,
        CASE
            WHEN t.period_sdate LIKE '%-%' THEN SUBSTR(t.period_sdate, 1, 7)
            ELSE CONCAT(SUBSTR(t.period_sdate, 1, 4), '-', SUBSTR(t.period_sdate, 5, 2))
        END AS period,
        COALESCE(t.order_no, CAST(t.id AS STRING)) AS order_key,
        COALESCE(t.opt_xs, 0) AS opt_xs,
        COALESCE(t.opt_s, 0) AS opt_s,
        COALESCE(t.opt_m, 0) AS opt_m,
        COALESCE(t.opt_l, 0) AS opt_l,
        COALESCE(t.opt_xl, 0) AS opt_xl,
        COALESCE(t.orig_xs, 0) AS orig_xs,
        COALESCE(t.orig_s, 0) AS orig_s,
        COALESCE(t.orig_m, 0) AS orig_m,
        COALESCE(t.orig_l, 0) AS orig_l,
        COALESCE(t.orig_xl, 0) AS orig_xl,
        GREATEST(COALESCE(t.cost, 0) - COALESCE(t.opt_cost, 0), 0) AS extra_cost
    FROM paimon.dwd_pub.t18_top_paper_bag_opt_price t
    LEFT JOIN dws_pub.dws_dim_org_mainfo_ex d
        ON t.org_name = d.org_name
    WHERE d.store_status = 1
      AND d.big_region_name IS NOT NULL
      AND d.big_region_name NOT IN ('总公司')
      -- AND t.business_type IN ('0', '1')
), base_orders AS (
    SELECT *
    FROM src_orders
    WHERE period = '${report_month}'
), classified_orders AS (
    SELECT
        *,
        opt_xs + opt_s + opt_m + opt_l + opt_xl AS opt_total,
        orig_xs + orig_s + orig_m + orig_l + orig_xl AS orig_total,
        (orig_xs + orig_s + orig_m + orig_l + orig_xl)
        - (opt_xs + opt_s + opt_m + opt_l + opt_xl) AS delta_total,
        CASE
            WHEN orig_xs > opt_xs OR orig_s > opt_s OR orig_m > opt_m OR orig_l > opt_l OR orig_xl > opt_xl
            THEN 1 ELSE 0
        END AS has_increase,
        CASE
            WHEN orig_xs < opt_xs OR orig_s < opt_s OR orig_m < opt_m OR orig_l < opt_l OR orig_xl < opt_xl
            THEN 1 ELSE 0
        END AS has_decrease,
        CASE
            WHEN (opt_xs = 0 AND orig_xs > 0)
              OR (opt_s = 0 AND orig_s > 0)
              OR (opt_m = 0 AND orig_m > 0)
              OR (opt_l = 0 AND orig_l > 0)
              OR (opt_xl = 0 AND orig_xl > 0)
            THEN 1 ELSE 0
        END AS has_new_added_size
    FROM base_orders
), small_bag_orders AS (
    SELECT
        *,
        CASE
            WHEN delta_total > 0 AND has_decrease = 1 AND has_increase = 1 THEN '组合替代型'
            WHEN delta_total > 0 AND has_decrease = 0 AND has_new_added_size = 1 THEN '加袋型'
            WHEN delta_total > 0 THEN '纯粹多袋型'
            ELSE NULL
        END AS small_bag_type
    FROM classified_orders
    WHERE delta_total > 0
), all_orders AS (
    SELECT
        region,
        period,
        COUNT(DISTINCT order_key) AS total_order_cnt
    FROM base_orders
    GROUP BY region, period
), small_bag_summary AS (
    SELECT
        region,
        period,
        COUNT(DISTINCT order_key) AS small_bag_order_cnt,
        SUM(delta_total) AS small_bag_extra_bag_qty,
        SUM(extra_cost) AS small_bag_extra_cost,
        COUNT(DISTINCT CASE WHEN small_bag_type = '加袋型' THEN order_key END) AS add_order_cnt,
        COUNT(DISTINCT CASE WHEN small_bag_type = '组合替代型' THEN order_key END) AS replace_order_cnt,
        COUNT(DISTINCT CASE WHEN small_bag_type = '纯粹多袋型' THEN order_key END) AS pure_order_cnt,
        SUM(CASE WHEN small_bag_type = '加袋型' THEN delta_total ELSE 0 END) AS add_extra_bag_qty,
        SUM(CASE WHEN small_bag_type = '组合替代型' THEN delta_total ELSE 0 END) AS replace_extra_bag_qty,
        SUM(CASE WHEN small_bag_type = '纯粹多袋型' THEN delta_total ELSE 0 END) AS pure_extra_bag_qty,
        SUM(CASE WHEN small_bag_type = '加袋型' THEN extra_cost ELSE 0 END) AS add_extra_cost,
        SUM(CASE WHEN small_bag_type = '组合替代型' THEN extra_cost ELSE 0 END) AS replace_extra_cost,
        SUM(CASE WHEN small_bag_type = '纯粹多袋型' THEN extra_cost ELSE 0 END) AS pure_extra_cost
    FROM small_bag_orders
    GROUP BY region, period
)
SELECT
    a.region,
    a.period,
    a.total_order_cnt,
    COALESCE(s.small_bag_order_cnt, 0) AS small_bag_order_cnt,
    CASE
        WHEN a.total_order_cnt = 0 THEN 0
        ELSE ROUND(COALESCE(s.small_bag_order_cnt, 0) * 1.0 / a.total_order_cnt, 4)
    END AS small_bag_order_ratio,
    COALESCE(s.small_bag_extra_bag_qty, 0) AS small_bag_extra_bag_qty,
    COALESCE(s.small_bag_extra_cost, 0) AS small_bag_extra_cost,
    COALESCE(s.add_order_cnt, 0) AS add_order_cnt,
    COALESCE(s.replace_order_cnt, 0) AS replace_order_cnt,
    COALESCE(s.pure_order_cnt, 0) AS pure_order_cnt,
    CASE
        WHEN COALESCE(s.small_bag_order_cnt, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(s.add_order_cnt, 0) * 1.0 / s.small_bag_order_cnt, 4)
    END AS add_order_ratio_in_small_bag,
    CASE
        WHEN COALESCE(s.small_bag_order_cnt, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(s.replace_order_cnt, 0) * 1.0 / s.small_bag_order_cnt, 4)
    END AS replace_order_ratio_in_small_bag,
    CASE
        WHEN COALESCE(s.small_bag_order_cnt, 0) = 0 THEN 0
        ELSE ROUND(COALESCE(s.pure_order_cnt, 0) * 1.0 / s.small_bag_order_cnt, 4)
    END AS pure_order_ratio_in_small_bag,
    COALESCE(s.add_extra_bag_qty, 0) AS add_extra_bag_qty,
    COALESCE(s.replace_extra_bag_qty, 0) AS replace_extra_bag_qty,
    COALESCE(s.pure_extra_bag_qty, 0) AS pure_extra_bag_qty,
    COALESCE(s.add_extra_cost, 0) AS add_extra_cost,
    COALESCE(s.replace_extra_cost, 0) AS replace_extra_cost,
    COALESCE(s.pure_extra_cost, 0) AS pure_extra_cost
FROM all_orders a
LEFT JOIN small_bag_summary s
    ON a.region = s.region
   AND a.period = s.period;
