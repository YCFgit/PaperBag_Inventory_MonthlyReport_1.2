-- SQL 1: 大区 × 月份 理论需求量
-- 数据源: paimon.dwd_pub.t18_top_paper_bag_opt_price + hive.dws_pub.dws_dim_org_mainfo_ex
SELECT
    d.big_region_name                                          AS region,
    CONCAT(SUBSTR(t.period_sdate, 1, 4), '-', SUBSTR(t.period_sdate, 5, 2)) AS period,
    SUM(COALESCE(t.opt_xs, 0))                                 AS xs_theory_qty,
    SUM(COALESCE(t.opt_s, 0))                                  AS s_theory_qty,
    SUM(COALESCE(t.opt_m, 0))                                  AS m_theory_qty,
    SUM(COALESCE(t.opt_l, 0))                                  AS l_theory_qty,
    SUM(COALESCE(t.opt_xl, 0))                                 AS xl_theory_qty,
    SUM(
        COALESCE(t.opt_xs, 0)
        + COALESCE(t.opt_s, 0)
        + COALESCE(t.opt_m, 0)
        + COALESCE(t.opt_l, 0)
        + COALESCE(t.opt_xl, 0)
    )                                                          AS total_theory_qty
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
