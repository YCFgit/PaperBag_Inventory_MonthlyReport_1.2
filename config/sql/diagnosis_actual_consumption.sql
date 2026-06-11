-- SQL 2: 大区 × 月份 × 尺码 实际消耗量
-- 数据源: ads_pub.ads_fact_day_org_pp_ord_sal_inv
-- 口径: 报告月内线下/离店开单、自提、非团购单纸袋销售量；仅统计 ZD010/ZD2023 系列编码。
WITH paper_bag_size_map AS (
    SELECT 'xs' AS bag_size,
        'ZD010XS' AS pro_code UNION ALL
    SELECT 'xs', 'ZD2023XS' UNION ALL

    SELECT 's', 'ZD010S' UNION ALL
    SELECT 's', 'ZD2023S' UNION ALL

    SELECT 'm', 'ZD010M' UNION ALL
    SELECT 'm', 'ZD2023M' UNION ALL

    SELECT 'l', 'ZD010L' UNION ALL
    SELECT 'l', 'ZD2023L' UNION ALL

    SELECT 'xl', 'ZD010XL' UNION ALL
    SELECT 'xl', 'ZD2023XL'
), monthly_actual AS (
    SELECT
        a.shop_big_region_name AS region,
        SUBSTR(CAST(a.period_date AS STRING), 1, 7) AS period,
        m.bag_size,
        SUM(COALESCE(a.pp_sal_qty, 0)) AS actual_qty
    FROM ads_pub.ads_fact_day_org_pp_ord_sal_inv a
    INNER JOIN paper_bag_size_map m
        ON a.pro_code = m.pro_code
    WHERE SUBSTR(CAST(a.period_date AS STRING), 1, 7) = '${report_month}'
      AND SUBSTR(CAST(a.pt_day AS STRING), 1, 7) = '${report_month}'
      AND (a.special_flag IS NULL OR a.special_flag NOT IN ('团购单'))
      AND a.online_offline_name IN ('线下', '离店开单')
      AND a.logistics_mode IN ('自提')
      AND a.shop_big_region_name IS NOT NULL
      AND a.shop_big_region_name NOT IN ('总公司')
    GROUP BY
        a.shop_big_region_name,
        SUBSTR(CAST(a.period_date AS STRING), 1, 7),
        m.bag_size
)
SELECT
    region,
    period,
    SUM(CASE WHEN bag_size = 'xs' THEN actual_qty ELSE 0 END) AS xs_actual_qty,
    SUM(CASE WHEN bag_size = 's'  THEN actual_qty ELSE 0 END) AS s_actual_qty,
    SUM(CASE WHEN bag_size = 'm'  THEN actual_qty ELSE 0 END) AS m_actual_qty,
    SUM(CASE WHEN bag_size = 'l'  THEN actual_qty ELSE 0 END) AS l_actual_qty,
    SUM(CASE WHEN bag_size = 'xl' THEN actual_qty ELSE 0 END) AS xl_actual_qty,
    SUM(actual_qty) AS total_actual_qty
FROM monthly_actual
GROUP BY region, period
