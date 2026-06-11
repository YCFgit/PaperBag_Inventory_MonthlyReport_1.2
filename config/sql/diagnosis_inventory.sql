-- SQL 3: 大区 × 月份 × 尺码 月末库存量（取报告月内最新库存快照）
-- 数据源: ads_pub.ads_gy_fact_day_org_pro_inv
-- 口径: 纸袋库存仅统计 ZD010/ZD2023 系列编码；每个大区取报告月内最新 p_day 快照并汇总全部组织库存。
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
), latest_region_snapshot AS (
    SELECT
        big_region_name AS region,
        MAX(p_day) AS latest_p_day
    FROM ads_pub.ads_gy_fact_day_org_pro_inv
    WHERE pro_cate_name IN ('纸袋')
      AND SUBSTR(p_day, 1, 6) = REPLACE('${report_month}', '-', '')
      AND big_region_name IS NOT NULL
      AND big_region_name NOT IN ('总公司')
    GROUP BY big_region_name
), month_end_stock AS (
    SELECT
        i.big_region_name AS region,
        '${report_month}' AS period,
        m.bag_size,
        SUM(COALESCE(i.wl_biz_inv_qty, 0)) AS stock_qty
    FROM ads_pub.ads_gy_fact_day_org_pro_inv i
    INNER JOIN latest_region_snapshot l
        ON i.big_region_name = l.region
       AND i.p_day = l.latest_p_day
    INNER JOIN paper_bag_size_map m
        ON i.pro_code = m.pro_code
    WHERE i.pro_cate_name IN ('纸袋')
      AND i.big_region_name IS NOT NULL
      AND i.big_region_name NOT IN ('总公司')
    GROUP BY i.big_region_name, m.bag_size
)
SELECT
    region,
    period,
    SUM(CASE WHEN bag_size = 'xs' THEN stock_qty ELSE 0 END) AS xs_stock_qty,
    SUM(CASE WHEN bag_size = 's'  THEN stock_qty ELSE 0 END) AS s_stock_qty,
    SUM(CASE WHEN bag_size = 'm'  THEN stock_qty ELSE 0 END) AS m_stock_qty,
    SUM(CASE WHEN bag_size = 'l'  THEN stock_qty ELSE 0 END) AS l_stock_qty,
    SUM(CASE WHEN bag_size = 'xl' THEN stock_qty ELSE 0 END) AS xl_stock_qty,
    SUM(stock_qty) AS total_stock_qty
FROM month_end_stock
GROUP BY region, period;
