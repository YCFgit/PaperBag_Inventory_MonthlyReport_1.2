-- SQL 6: 大区 × 月份 组合替代型主替代模式
-- 用途: 支撑“XL被M+L替代”之类的组合替代模式识别。
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
        (orig_xs + orig_s + orig_m + orig_l + orig_xl)
        - (opt_xs + opt_s + opt_m + opt_l + opt_xl) AS delta_total
    FROM base_orders
), combo_orders AS (
    SELECT *
    FROM classified_orders
    WHERE delta_total > 0
      AND (orig_xs < opt_xs OR orig_s < opt_s OR orig_m < opt_m OR orig_l < opt_l OR orig_xl < opt_xl)
      AND (orig_xs > opt_xs OR orig_s > opt_s OR orig_m > opt_m OR orig_l > opt_l OR orig_xl > opt_xl)
), delta_rows AS (
    SELECT region, period, order_key, extra_cost, 'XS' AS bag_size, orig_xs - opt_xs AS raw_delta FROM combo_orders
    UNION ALL
    SELECT region, period, order_key, extra_cost, 'S' AS bag_size, orig_s - opt_s AS raw_delta FROM combo_orders
    UNION ALL
    SELECT region, period, order_key, extra_cost, 'M' AS bag_size, orig_m - opt_m AS raw_delta FROM combo_orders
    UNION ALL
    SELECT region, period, order_key, extra_cost, 'L' AS bag_size, orig_l - opt_l AS raw_delta FROM combo_orders
    UNION ALL
    SELECT region, period, order_key, extra_cost, 'XL' AS bag_size, orig_xl - opt_xl AS raw_delta FROM combo_orders
), combo_increase AS (
    SELECT
        region,
        period,
        order_key,
        CONCAT_WS('+', SORT_ARRAY(COLLECT_LIST(CONCAT(bag_size, 'x', CAST(raw_delta AS STRING))))) AS replaced_to
    FROM delta_rows
    WHERE raw_delta > 0
    GROUP BY region, period, order_key
), combo_decrease AS (
    SELECT
        region,
        period,
        order_key,
        CONCAT_WS('+', SORT_ARRAY(COLLECT_LIST(CONCAT(bag_size, 'x', CAST(-raw_delta AS STRING))))) AS replaced_from
    FROM delta_rows
    WHERE raw_delta < 0
    GROUP BY region, period, order_key
), combo_pattern AS (
    SELECT
        i.region,
        i.period,
        i.order_key,
        d.replaced_from,
        i.replaced_to,
        c.extra_cost
    FROM combo_increase i
    INNER JOIN combo_decrease d
        ON i.region = d.region
       AND i.period = d.period
       AND i.order_key = d.order_key
    INNER JOIN combo_orders c
        ON i.region = c.region
       AND i.period = c.period
       AND i.order_key = c.order_key
)
SELECT
    region,
    period,
    replaced_from,
    replaced_to,
    COUNT(DISTINCT order_key) AS combo_order_cnt,
    SUM(extra_cost) AS combo_extra_cost,
    ROUND(
        COUNT(DISTINCT order_key) * 1.0
        / SUM(COUNT(DISTINCT order_key)) OVER (PARTITION BY region, period),
        4
    ) AS combo_order_ratio_in_region
FROM combo_pattern
GROUP BY region, period, replaced_from, replaced_to
ORDER BY region, period, combo_order_cnt DESC;
