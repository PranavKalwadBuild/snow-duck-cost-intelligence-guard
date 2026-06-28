-- ============================================================================
-- Query 1: Multi-Channel Sales Comparison with Rolling Averages
-- Estimated scan: ~26.7 TB (STORE_SALES 11.4 TB + CATALOG_SALES 10.2 TB + WEB_SALES 5.2 TB)
-- Compares store, catalog, and web sales by item with 90-day rolling averages,
-- year-over-year change, and daily revenue ranking.
-- ============================================================================
WITH daily_sales AS (
    SELECT d.d_date, i.i_item_id, i.i_item_desc,
           'store' AS channel,
           SUM(ss.ss_ext_sales_price) AS daily_revenue,
           SUM(ss.ss_quantity) AS daily_qty
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
    WHERE d.d_year = 2001
    GROUP BY d.d_date, i.i_item_id, i.i_item_desc
    UNION ALL
    SELECT d.d_date, i.i_item_id, i.i_item_desc,
           'catalog' AS channel,
           SUM(cs.cs_ext_sales_price),
           SUM(cs.cs_quantity)
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.CATALOG_SALES cs
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON cs.cs_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON cs.cs_item_sk = i.i_item_sk
    WHERE d.d_year = 2001
    GROUP BY d.d_date, i.i_item_id, i.i_item_desc
    UNION ALL
    SELECT d.d_date, i.i_item_id, i.i_item_desc,
           'web' AS channel,
           SUM(ws.ws_ext_sales_price),
           SUM(ws.ws_quantity)
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON ws.ws_item_sk = i.i_item_sk
    WHERE d.d_year = 2001
    GROUP BY d.d_date, i.i_item_id, i.i_item_desc
)
SELECT channel, d_date, i_item_id, i_item_desc,
       daily_revenue,
       AVG(daily_revenue) OVER (PARTITION BY channel, i_item_id ORDER BY d_date ROWS BETWEEN 89 PRECEDING AND CURRENT ROW) AS rolling_90d_avg,
       daily_revenue - LAG(daily_revenue, 365) OVER (PARTITION BY channel, i_item_id ORDER BY d_date) AS yoy_change,
       RANK() OVER (PARTITION BY channel, d_date ORDER BY daily_revenue DESC) AS daily_rank
FROM daily_sales
ORDER BY channel, d_date, daily_rank
LIMIT 10000;