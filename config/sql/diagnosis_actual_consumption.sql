-- SQL 2: 大区 × 月份 实际消耗量
-- 数据源: paimon.dwd_pub.t18_top_paper_bag_opt_price + hive.dws_pub.dws_dim_org_mainfo_ex
-- 口径: 实际使用量直接取运筹结果表 orig_xs ~ orig_xl，与理论值同表同粒度，避免跨系统口径不一致。
SELECT
    d.big_region_name                                          AS region,
    CONCAT(SUBSTR(t.period_sdate, 1, 4), '-', SUBSTR(t.period_sdate, 5, 2)) AS period,
    SUM(COALESCE(t.orig_xs, 0))                                AS xs_actual_qty,
    SUM(COALESCE(t.orig_s, 0))                                 AS s_actual_qty,
    SUM(COALESCE(t.orig_m, 0))                                 AS m_actual_qty,
    SUM(COALESCE(t.orig_l, 0))                                 AS l_actual_qty,
    SUM(COALESCE(t.orig_xl, 0))                                AS xl_actual_qty,
    SUM(
        COALESCE(t.orig_xs, 0)
        + COALESCE(t.orig_s, 0)
        + COALESCE(t.orig_m, 0)
        + COALESCE(t.orig_l, 0)
        + COALESCE(t.orig_xl, 0)
    )                                                          AS total_actual_qty
FROM paimon.dwd_pub.t18_top_paper_bag_opt_price t
LEFT JOIN dws_pub.dws_dim_org_mainfo_ex d
    ON t.org_name = d.org_name
WHERE SUBSTR(t.period_sdate, 1, 6) = REPLACE('${report_month}', '-', '')
  AND d.store_status = 1
  AND d.big_region_name IS NOT NULL
  AND d.big_region_name NOT IN ('总公司')
GROUP BY
    d.big_region_name,
    CONCAT(SUBSTR(t.period_sdate, 1, 4), '-', SUBSTR(t.period_sdate, 5, 2));
