-- SQL 2: 大区 × 月份 实际消耗量
SELECT
      shop_big_region_name                                       AS region,
      SUBSTR(CAST(period_date AS STRING), 1, 7)                  AS period,
      SUM(CASE WHEN pro_code IN ('ZD2023XS','ZD010XS') THEN pp_sal_qty ELSE 0 END) AS xs_actual_qty,
      SUM(CASE WHEN pro_code IN ('ZD2023S','ZD010S')   THEN pp_sal_qty ELSE 0 END) AS s_actual_qty,
      SUM(CASE WHEN pro_code IN ('ZD2023M','ZD010M')   THEN pp_sal_qty ELSE 0 END) AS m_actual_qty,
      SUM(CASE WHEN pro_code IN ('ZD2023L','ZD010L')   THEN pp_sal_qty ELSE 0 END) AS l_actual_qty,
      SUM(CASE WHEN pro_code IN ('ZD2023XL','ZD010XL') THEN pp_sal_qty ELSE 0 END) AS xl_actual_qty,
      SUM(pp_sal_qty)                                            AS total_actual_qty
  FROM hive.ads_pub.ads_fact_day_org_pp_ord_sal_inv
  WHERE SUBSTR(CAST(period_date AS STRING), 1, 7) = '${report_month}'
    AND pro_code IN ('ZD2023XS','ZD2023S','ZD2023M','ZD2023L','ZD2023XL',
                     'ZD010XS','ZD010S','ZD010M','ZD010L','ZD010XL')
    AND online_offline_name IN ('离店开单', '线下')
    AND logistics_mode = '自提'
  GROUP BY shop_big_region_name, SUBSTR(CAST(period_date AS STRING), 1, 7);