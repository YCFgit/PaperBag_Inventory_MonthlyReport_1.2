-- SQL 5: 大区 × 月份 × 子类型 × 尺码归因
-- 用途: 支撑“小袋多用”子类型下的主多用尺码/被替代尺码展开描述。
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
        COALESCE(t.orig_xl, 0) AS orig_xl
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
        (orig_xs + orig_s + orig_m + orig_l + orig_xl)
        - (opt_xs + opt_s + opt_m + opt_l + opt_xl) AS delta_total,
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
            WHEN delta_total > 0
             AND (orig_xs < opt_xs OR orig_s < opt_s OR orig_m < opt_m OR orig_l < opt_l OR orig_xl < opt_xl)
             AND (orig_xs > opt_xs OR orig_s > opt_s OR orig_m > opt_m OR orig_l > opt_l OR orig_xl > opt_xl)
            THEN '组合替代型'
            WHEN delta_total > 0 AND has_decrease = 0 AND has_new_added_size = 1
            THEN '加袋型'
            WHEN delta_total > 0
            THEN '纯粹多袋型'
            ELSE NULL
        END AS small_bag_type
    FROM classified_orders
    WHERE delta_total > 0
), delta_rows AS (
    SELECT region, period, order_key, small_bag_type, 'XS' AS bag_size, orig_xs - opt_xs AS raw_delta FROM small_bag_orders
    UNION ALL
    SELECT region, period, order_key, small_bag_type, 'S' AS bag_size, orig_s - opt_s AS raw_delta FROM small_bag_orders
    UNION ALL
    SELECT region, period, order_key, small_bag_type, 'M' AS bag_size, orig_m - opt_m AS raw_delta FROM small_bag_orders
    UNION ALL
    SELECT region, period, order_key, small_bag_type, 'L' AS bag_size, orig_l - opt_l AS raw_delta FROM small_bag_orders
    UNION ALL
    SELECT region, period, order_key, small_bag_type, 'XL' AS bag_size, orig_xl - opt_xl AS raw_delta FROM small_bag_orders
), typed_delta_rows AS (
    SELECT
        region,
        period,
        order_key,
        small_bag_type,
        'increase' AS delta_role,
        bag_size,
        raw_delta AS delta_qty
    FROM delta_rows
    WHERE raw_delta > 0

    UNION ALL

    SELECT
        region,
        period,
        order_key,
        small_bag_type,
        'decrease' AS delta_role,
        bag_size,
        -raw_delta AS delta_qty
    FROM delta_rows
    WHERE raw_delta < 0
), agg AS (
    SELECT
        region,
        period,
        small_bag_type,
        delta_role,
        bag_size,
        COUNT(DISTINCT order_key) AS order_cnt,
        SUM(delta_qty) AS delta_qty
    FROM typed_delta_rows
    GROUP BY region, period, small_bag_type, delta_role, bag_size
)
SELECT
    region,
    period,
    small_bag_type,
    delta_role,
    bag_size,
    order_cnt,
    delta_qty,
    ROUND(
        delta_qty * 1.0 / SUM(delta_qty) OVER (PARTITION BY region, period, small_bag_type, delta_role),
        4
    ) AS qty_ratio_in_type
FROM agg
ORDER BY region, period, small_bag_type, delta_role, delta_qty DESC;
