-- Compute-intensive analytical queries against SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL for warehouse load testing.
-- Co-authored with CoCo
--
-- Scale factor: TPCDS_SF100TCL (STORE_SALES ~288B rows, ~10.4 TB)
-- Data volume estimates below come from EXPLAIN plan partition/byte assignments (worst case before runtime pruning).
-- Recommended warehouse: 2XL or larger to limit remote spilling.
-- ============================================================================


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


-- ============================================================================
-- Query 2: Customer Lifetime Value with Return Ratio Analysis
-- Estimated scan: ~27.7 TB (all 4 fact tables: STORE_SALES, CATALOG_SALES, WEB_SALES, STORE_RETURNS)
-- Computes cross-channel CLV, return rates, and percentile/rank standings per customer.
-- ============================================================================
WITH customer_purchases AS (
    SELECT c.c_customer_sk, c.c_customer_id,
           c.c_first_name, c.c_last_name,
           SUM(ss.ss_ext_sales_price) AS store_spend,
           COUNT(DISTINCT ss.ss_ticket_number) AS store_orders
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.CUSTOMER c
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss ON c.c_customer_sk = ss.ss_customer_sk
    GROUP BY c.c_customer_sk, c.c_customer_id, c.c_first_name, c.c_last_name
),
customer_returns AS (
    SELECT sr.sr_customer_sk,
           SUM(sr.sr_return_amt) AS store_returns,
           COUNT(*) AS return_count
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_RETURNS sr
    GROUP BY sr.sr_customer_sk
),
customer_web AS (
    SELECT ws.ws_bill_customer_sk AS customer_sk,
           SUM(ws.ws_ext_sales_price) AS web_spend,
           COUNT(DISTINCT ws.ws_order_number) AS web_orders
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.WEB_SALES ws
    GROUP BY ws.ws_bill_customer_sk
),
customer_catalog AS (
    SELECT cs.cs_bill_customer_sk AS customer_sk,
           SUM(cs.cs_ext_sales_price) AS catalog_spend,
           COUNT(DISTINCT cs.cs_order_number) AS catalog_orders
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.CATALOG_SALES cs
    GROUP BY cs.cs_bill_customer_sk
)
SELECT cp.c_customer_id,
       cp.c_first_name || ' ' || cp.c_last_name AS customer_name,
       cp.store_spend,
       COALESCE(cw.web_spend, 0) AS web_spend,
       COALESCE(cc.catalog_spend, 0) AS catalog_spend,
       cp.store_spend + COALESCE(cw.web_spend, 0) + COALESCE(cc.catalog_spend, 0) AS total_ltv,
       COALESCE(cr.store_returns, 0) AS total_returns,
       ROUND(COALESCE(cr.store_returns, 0) / NULLIF(cp.store_spend, 0) * 100, 2) AS return_rate_pct,
       NTILE(100) OVER (ORDER BY cp.store_spend + COALESCE(cw.web_spend, 0) + COALESCE(cc.catalog_spend, 0)) AS ltv_percentile,
       DENSE_RANK() OVER (ORDER BY cp.store_spend + COALESCE(cw.web_spend, 0) + COALESCE(cc.catalog_spend, 0) DESC) AS ltv_rank
FROM customer_purchases cp
LEFT JOIN customer_returns cr ON cp.c_customer_sk = cr.sr_customer_sk
LEFT JOIN customer_web cw ON cp.c_customer_sk = cw.customer_sk
LEFT JOIN customer_catalog cc ON cp.c_customer_sk = cc.customer_sk
QUALIFY ltv_percentile >= 95
ORDER BY total_ltv DESC
LIMIT 10000;


-- ============================================================================
-- Query 3: Inventory Turnover vs. Sales Velocity
-- Estimated scan: ~11.4 TB (STORE_SALES 11.4 TB + INVENTORY ~8 GB)
-- Cross-references weekly inventory levels with sales velocity, rolling 13-week
-- average sales, volatility, and a stock-status classification.
-- ============================================================================
WITH weekly_sales AS (
    SELECT ss.ss_item_sk, ss.ss_store_sk,
           d.d_week_seq,
           SUM(ss.ss_quantity) AS units_sold,
           SUM(ss.ss_ext_sales_price) AS revenue
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE d.d_year IN (2001, 2002)
    GROUP BY ss.ss_item_sk, ss.ss_store_sk, d.d_week_seq
),
weekly_inventory AS (
    SELECT inv.inv_item_sk, inv.inv_warehouse_sk,
           d.d_week_seq,
           AVG(inv.inv_quantity_on_hand) AS avg_inventory
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.INVENTORY inv
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON inv.inv_date_sk = d.d_date_sk
    WHERE d.d_year IN (2001, 2002)
    GROUP BY inv.inv_item_sk, inv.inv_warehouse_sk, d.d_week_seq
)
SELECT ws.ss_item_sk, i.i_item_desc, i.i_category, i.i_class,
       ws.d_week_seq,
       ws.units_sold,
       wi.avg_inventory,
       ROUND(ws.units_sold / NULLIF(wi.avg_inventory, 0), 4) AS turnover_ratio,
       AVG(ws.units_sold) OVER (PARTITION BY ws.ss_item_sk ORDER BY ws.d_week_seq ROWS BETWEEN 12 PRECEDING AND CURRENT ROW) AS rolling_13wk_avg_sales,
       STDDEV(ws.units_sold) OVER (PARTITION BY ws.ss_item_sk ORDER BY ws.d_week_seq ROWS BETWEEN 12 PRECEDING AND CURRENT ROW) AS sales_volatility,
       CASE
           WHEN wi.avg_inventory > 0 AND ws.units_sold / NULLIF(wi.avg_inventory, 0) > 2 THEN 'UNDERSTOCKED'
           WHEN wi.avg_inventory > 0 AND ws.units_sold / NULLIF(wi.avg_inventory, 0) < 0.1 THEN 'OVERSTOCKED'
           ELSE 'BALANCED'
       END AS stock_status
FROM weekly_sales ws
JOIN weekly_inventory wi ON ws.ss_item_sk = wi.inv_item_sk AND ws.d_week_seq = wi.d_week_seq
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON ws.ss_item_sk = i.i_item_sk
ORDER BY turnover_ratio DESC
LIMIT 10000;


-- ============================================================================
-- Query 4: Customer Cohort Retention
-- Estimated scan: ~22.8 TB (STORE_SALES scanned twice: first_purchase + monthly_activity)
-- Analyzes monthly cohort retention rates across the full customer base.
-- ============================================================================
WITH first_purchase AS (
    SELECT ss_customer_sk,
           MIN(d.d_month_seq) AS cohort_month
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    GROUP BY ss_customer_sk
),
monthly_activity AS (
    SELECT DISTINCT ss.ss_customer_sk, d.d_month_seq AS activity_month
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
)
SELECT fp.cohort_month,
       ma.activity_month - fp.cohort_month AS months_since_first,
       COUNT(DISTINCT ma.ss_customer_sk) AS active_customers,
       COUNT(DISTINCT ma.ss_customer_sk) * 100.0 / MAX(cohort_size.cnt) AS retention_pct
FROM first_purchase fp
JOIN monthly_activity ma ON fp.ss_customer_sk = ma.ss_customer_sk
JOIN (
    SELECT cohort_month, COUNT(*) AS cnt
    FROM first_purchase
    GROUP BY cohort_month
) cohort_size ON fp.cohort_month = cohort_size.cohort_month
WHERE ma.activity_month - fp.cohort_month BETWEEN 0 AND 24
GROUP BY fp.cohort_month, ma.activity_month - fp.cohort_month
ORDER BY fp.cohort_month, months_since_first
LIMIT 10000;


-- ============================================================================
-- Query 5: Market Basket Analysis (Self-Join on STORE_SALES)
-- Estimated scan: ~11.4 TB, but the same-transaction self-join causes large
-- intermediate row expansion (quadratic per ticket). Date filter prunes heavily.
-- Finds frequently co-purchased item pairs within the same store transaction.
-- ============================================================================
WITH basket_items AS (
    SELECT ss.ss_ticket_number, ss.ss_item_sk, i.i_item_id, i.i_category
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002 AND d.d_moy = 12
)
SELECT a.i_item_id AS item_a, a.i_category AS category_a,
       b.i_item_id AS item_b, b.i_category AS category_b,
       COUNT(*) AS co_occurrence,
       COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (PARTITION BY a.i_item_id) AS confidence
FROM basket_items a
JOIN basket_items b ON a.ss_ticket_number = b.ss_ticket_number AND a.ss_item_sk < b.ss_item_sk
GROUP BY a.i_item_id, a.i_category, b.i_item_id, b.i_category
HAVING COUNT(*) > 1000
ORDER BY co_occurrence DESC
LIMIT 5000;


-- ############################################################################
-- EXPANDED QUERY LIBRARY (Q6-Q21)
-- Categories: Heavy analytics | Aggregation stress | Join stress |
--             Set ops & recursion | Sort/spill stress
-- Scales mixed across TPCDS_SF10TCL (faster) and TPCDS_SF100TCL (heavier).
-- ############################################################################


-- ============================================================================
-- [HEAVY ANALYTICS]
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Query 6: Monthly category sales with running total, market share, MoM change
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
WITH monthly AS (
    SELECT d.d_year, d.d_moy, i.i_category,
           SUM(ss.ss_net_paid) AS net_sales
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
    WHERE d.d_year BETWEEN 2000 AND 2002
    GROUP BY d.d_year, d.d_moy, i.i_category
)
SELECT d_year, d_moy, i_category, net_sales,
       SUM(net_sales) OVER (PARTITION BY i_category ORDER BY d_year, d_moy ROWS UNBOUNDED PRECEDING) AS running_total,
       net_sales / SUM(net_sales) OVER (PARTITION BY d_year, d_moy) AS market_share,
       net_sales - LAG(net_sales) OVER (PARTITION BY i_category ORDER BY d_year, d_moy) AS mom_change
FROM monthly
ORDER BY i_category, d_year, d_moy;


-- ----------------------------------------------------------------------------
-- Query 7: Promotion lift analysis (promo vs non-promo) by category/class
-- Scale: TPCDS_SF100TCL
-- ----------------------------------------------------------------------------
SELECT i.i_category, i.i_class,
       CASE WHEN ss.ss_promo_sk IS NOT NULL THEN 'promo' ELSE 'non_promo' END AS promo_flag,
       COUNT(*) AS line_count,
       SUM(ss.ss_quantity) AS units,
       SUM(ss.ss_ext_sales_price) AS revenue,
       AVG(ss.ss_sales_price) AS avg_price
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
WHERE d.d_year = 2002
GROUP BY i.i_category, i.i_class,
         CASE WHEN ss.ss_promo_sk IS NOT NULL THEN 'promo' ELSE 'non_promo' END
ORDER BY revenue DESC
LIMIT 10000;


-- ----------------------------------------------------------------------------
-- Query 8: Customer RFM segmentation (Recency / Frequency / Monetary scores)
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
WITH cust AS (
    SELECT ss.ss_customer_sk,
           MAX(d.d_date) AS last_purchase,
           COUNT(DISTINCT ss.ss_ticket_number) AS frequency,
           SUM(ss.ss_net_paid) AS monetary
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE ss.ss_customer_sk IS NOT NULL
    GROUP BY ss.ss_customer_sk
)
SELECT ss_customer_sk, last_purchase, frequency, monetary,
       NTILE(5) OVER (ORDER BY last_purchase DESC) AS r_score,
       NTILE(5) OVER (ORDER BY frequency)          AS f_score,
       NTILE(5) OVER (ORDER BY monetary)           AS m_score
FROM cust
ORDER BY monetary DESC
LIMIT 10000;


-- ============================================================================
-- [AGGREGATION STRESS]
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Query 9: Approx distinct customers + continuous percentiles by category/state
-- Scale: TPCDS_SF100TCL
-- ----------------------------------------------------------------------------
SELECT i.i_category, ca.ca_state,
       APPROX_COUNT_DISTINCT(ss.ss_customer_sk) AS approx_customers,
       COUNT(*) AS line_count,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ss.ss_net_paid) AS median_net_paid,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY ss.ss_net_paid) AS p90_net_paid
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.CUSTOMER_ADDRESS ca ON ss.ss_addr_sk = ca.ca_address_sk
GROUP BY i.i_category, ca.ca_state
ORDER BY approx_customers DESC
LIMIT 10000;


-- ----------------------------------------------------------------------------
-- Query 10: Multi-dimensional CUBE aggregation (year x category x state)
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
SELECT d.d_year, i.i_category, ca.ca_state,
       SUM(ss.ss_net_paid) AS net_sales,
       COUNT(*) AS line_count,
       GROUPING(d.d_year)     AS g_year,
       GROUPING(i.i_category) AS g_category,
       GROUPING(ca.ca_state)  AS g_state
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER_ADDRESS ca ON ss.ss_addr_sk = ca.ca_address_sk
WHERE d.d_year BETWEEN 2000 AND 2002
GROUP BY CUBE (d.d_year, i.i_category, ca.ca_state)
ORDER BY net_sales DESC NULLS LAST
LIMIT 10000;


-- ----------------------------------------------------------------------------
-- Query 11: Approx unique customers per store per month
-- Scale: TPCDS_SF100TCL
-- ----------------------------------------------------------------------------
SELECT s.s_store_id, s.s_state, d.d_year, d.d_moy,
       APPROX_COUNT_DISTINCT(ss.ss_customer_sk) AS approx_unique_customers,
       SUM(ss.ss_net_paid) AS net_sales
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE s ON ss.ss_store_sk = s.s_store_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
GROUP BY s.s_store_id, s.s_state, d.d_year, d.d_moy
ORDER BY net_sales DESC
LIMIT 10000;


-- ============================================================================
-- [JOIN STRESS]
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Query 12: Wide star join across STORE_SALES + 6 dimension tables
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
SELECT d.d_year, d.d_qoy, i.i_category, i.i_brand,
       s.s_state, ca.ca_state AS cust_state,
       cd.cd_gender, cd.cd_marital_status,
       p.p_promo_name,
       SUM(ss.ss_net_paid) AS net_sales,
       SUM(ss.ss_quantity) AS units
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE s ON ss.ss_store_sk = s.s_store_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER_ADDRESS ca ON ss.ss_addr_sk = ca.ca_address_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER_DEMOGRAPHICS cd ON ss.ss_cdemo_sk = cd.cd_demo_sk
LEFT JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.PROMOTION p ON ss.ss_promo_sk = p.p_promo_sk
WHERE d.d_year = 2002
GROUP BY d.d_year, d.d_qoy, i.i_category, i.i_brand, s.s_state, ca.ca_state,
         cd.cd_gender, cd.cd_marital_status, p.p_promo_name
ORDER BY net_sales DESC
LIMIT 10000;


-- ----------------------------------------------------------------------------
-- Query 13: Anti-join - items sold via catalog but NEVER in store
-- Scale: TPCDS_SF100TCL
-- ----------------------------------------------------------------------------
SELECT i.i_item_id, i.i_item_desc, i.i_category,
       SUM(cs.cs_net_paid) AS catalog_net_sales
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.CATALOG_SALES cs
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON cs.cs_item_sk = i.i_item_sk
WHERE NOT EXISTS (
    SELECT 1 FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
    WHERE ss.ss_item_sk = cs.cs_item_sk
)
GROUP BY i.i_item_id, i.i_item_desc, i.i_category
ORDER BY catalog_net_sales DESC
LIMIT 10000;


-- ----------------------------------------------------------------------------
-- Query 14: Self-join via window - repeat purchase interval per customer
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
WITH cust_orders AS (
    SELECT DISTINCT ss.ss_customer_sk, d.d_date
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE ss.ss_customer_sk IS NOT NULL
)
SELECT ss_customer_sk,
       d_date AS purchase_date,
       LEAD(d_date) OVER (PARTITION BY ss_customer_sk ORDER BY d_date) AS next_purchase_date,
       DATEDIFF('day', d_date, LEAD(d_date) OVER (PARTITION BY ss_customer_sk ORDER BY d_date)) AS days_between
FROM cust_orders
QUALIFY next_purchase_date IS NOT NULL
ORDER BY ss_customer_sk, purchase_date
LIMIT 10000;


-- ============================================================================
-- [SET OPS & RECURSION]
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Query 15: Store-only customers (EXCEPT across catalog and web channels)
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
SELECT ss_customer_sk AS customer_sk
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES
WHERE ss_customer_sk IS NOT NULL
EXCEPT
SELECT cs_bill_customer_sk
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES
WHERE cs_bill_customer_sk IS NOT NULL
EXCEPT
SELECT ws_bill_customer_sk
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES
WHERE ws_bill_customer_sk IS NOT NULL
ORDER BY customer_sk
LIMIT 10000;


-- ----------------------------------------------------------------------------
-- Query 16: Recursive month spine joined to sales (detect zero-sales months)
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
WITH RECURSIVE month_bounds AS (
    SELECT MIN(d_month_seq) AS lo, MAX(d_month_seq) AS hi
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM
),
month_spine (month_seq, hi) AS (
    SELECT lo, hi FROM month_bounds
    UNION ALL
    SELECT month_seq + 1, hi FROM month_spine WHERE month_seq < hi
),
monthly_sales AS (
    SELECT d.d_month_seq, SUM(ss.ss_net_paid) AS net_sales
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    GROUP BY d.d_month_seq
)
SELECT sp.month_seq,
       COALESCE(ms.net_sales, 0) AS net_sales,
       CASE WHEN ms.net_sales IS NULL THEN 'NO_SALES' ELSE 'HAS_SALES' END AS status
FROM month_spine sp
LEFT JOIN monthly_sales ms ON sp.month_seq = ms.d_month_seq
ORDER BY sp.month_seq;


-- ----------------------------------------------------------------------------
-- Query 17: Omni-channel customers (INTERSECT of store and web buyers)
-- Scale: TPCDS_SF100TCL
-- ----------------------------------------------------------------------------
SELECT ss_customer_sk AS customer_sk
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES
WHERE ss_customer_sk IS NOT NULL
INTERSECT
SELECT ws_bill_customer_sk
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.WEB_SALES
WHERE ws_bill_customer_sk IS NOT NULL
ORDER BY customer_sk
LIMIT 10000;


-- ============================================================================
-- [SORT / SPILL STRESS]
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Query 18: Large line-level ORDER BY with no aggregation (top 100k by profit)
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
SELECT ss.ss_customer_sk, ss.ss_item_sk, ss.ss_ticket_number,
       ss.ss_net_paid, ss.ss_net_profit, d.d_date
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
WHERE d.d_year = 2002
ORDER BY ss.ss_net_profit DESC, ss.ss_net_paid DESC
LIMIT 100000;


-- ----------------------------------------------------------------------------
-- Query 19: Global ranking over the full STORE_SALES fact (massive sort)
-- Scale: TPCDS_SF100TCL
-- ----------------------------------------------------------------------------
SELECT ss_item_sk, ss_customer_sk, ss_ticket_number, ss_net_profit,
       RANK() OVER (ORDER BY ss_net_profit DESC)         AS profit_rank,
       PERCENT_RANK() OVER (ORDER BY ss_net_profit DESC) AS profit_pct_rank
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES
WHERE ss_net_profit IS NOT NULL
QUALIFY profit_rank <= 100000
ORDER BY profit_rank;


-- ----------------------------------------------------------------------------
-- Query 20: Distribution percentiles per category (median/quartiles)
-- Scale: TPCDS_SF10TCL
-- ----------------------------------------------------------------------------
SELECT i.i_category,
       COUNT(*) AS line_count,
       MEDIAN(ss.ss_sales_price) AS median_price,
       PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ss.ss_sales_price) AS p25,
       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ss.ss_sales_price) AS p75,
       PERCENTILE_DISC(0.5)  WITHIN GROUP (ORDER BY ss.ss_sales_price) AS p50_disc
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
GROUP BY i.i_category
ORDER BY line_count DESC;


-- ----------------------------------------------------------------------------
-- Query 21: Store returns rate by category (sales vs returns join)
-- Scale: TPCDS_SF100TCL
-- ----------------------------------------------------------------------------
WITH store_agg AS (
    SELECT i.i_category, SUM(ss.ss_net_paid) AS gross_sales
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
    GROUP BY i.i_category
),
return_agg AS (
    SELECT i.i_category, SUM(sr.sr_return_amt) AS returned_amt
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.STORE_RETURNS sr
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF100TCL.ITEM i ON sr.sr_item_sk = i.i_item_sk
    GROUP BY i.i_category
)
SELECT s.i_category, s.gross_sales, COALESCE(r.returned_amt, 0) AS returned_amt,
       ROUND(COALESCE(r.returned_amt, 0) / NULLIF(s.gross_sales, 0) * 100, 2) AS return_rate_pct
FROM store_agg s
LEFT JOIN return_agg r ON s.i_category = r.i_category
ORDER BY return_rate_pct DESC;


-- ############################################################################
-- MEDIUM QUERIES (Q22-Q31): 100 GB to 1 TB scan range
-- Target: TPCDS_SF10TCL with selective filters, or smaller fact tables.
-- STORE_SALES at SF10TCL is ~1.1 TB total; a single-year filter yields ~200 GB.
-- WEB_SALES at SF10TCL is ~520 GB total; CATALOG_SALES is ~1 TB total.
-- CATALOG_RETURNS is ~110 GB; WEB_RETURNS is ~65 GB; STORE_RETURNS is ~170 GB.
-- ############################################################################


-- ============================================================================
-- Query 22: Quarterly Revenue by Store and Category
-- Estimated scan: ~200 GB (STORE_SALES SF10TCL filtered to 1 year)
-- Breaks down quarterly revenue, units sold, and average ticket size per store
-- and product category for a single year.
-- ============================================================================
SELECT s.s_store_name, s.s_state,
       d.d_year, d.d_qoy,
       i.i_category,
       SUM(ss.ss_ext_sales_price) AS revenue,
       SUM(ss.ss_quantity) AS units_sold,
       AVG(ss.ss_ext_sales_price) AS avg_ticket,
       COUNT(DISTINCT ss.ss_ticket_number) AS num_transactions
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE s ON ss.ss_store_sk = s.s_store_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
WHERE d.d_year = 2001
GROUP BY s.s_store_name, s.s_state, d.d_year, d.d_qoy, i.i_category
ORDER BY revenue DESC
LIMIT 10000;


-- ============================================================================
-- Query 23: Web Sales Funnel by Demographics
-- Estimated scan: ~520 GB (full WEB_SALES SF10TCL + dimension joins)
-- Analyzes web sales revenue and order counts segmented by customer
-- demographics (gender, marital status, education) and household demographics.
-- ============================================================================
SELECT cd.cd_gender, cd.cd_marital_status, cd.cd_education_status,
       hd.hd_buy_potential,
       COUNT(*) AS line_items,
       COUNT(DISTINCT ws.ws_order_number) AS orders,
       SUM(ws.ws_ext_sales_price) AS revenue,
       SUM(ws.ws_net_profit) AS net_profit,
       AVG(ws.ws_quantity) AS avg_qty
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER_DEMOGRAPHICS cd ON ws.ws_bill_cdemo_sk = cd.cd_demo_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.HOUSEHOLD_DEMOGRAPHICS hd ON ws.ws_bill_hdemo_sk = hd.hd_demo_sk
GROUP BY cd.cd_gender, cd.cd_marital_status, cd.cd_education_status, hd.hd_buy_potential
ORDER BY revenue DESC
LIMIT 10000;


-- ============================================================================
-- Query 24: Catalog Sales Seasonal Patterns
-- Estimated scan: ~1 TB (CATALOG_SALES SF10TCL full scan)
-- Identifies seasonal peaks and troughs in catalog sales by month,
-- with year-over-year comparison and ranking of months by revenue.
-- ============================================================================
SELECT d.d_year, d.d_moy,
       SUM(cs.cs_ext_sales_price) AS revenue,
       SUM(cs.cs_quantity) AS units,
       COUNT(DISTINCT cs.cs_order_number) AS orders,
       SUM(cs.cs_ext_sales_price) - LAG(SUM(cs.cs_ext_sales_price))
           OVER (PARTITION BY d.d_moy ORDER BY d.d_year) AS yoy_revenue_change,
       RANK() OVER (PARTITION BY d.d_year ORDER BY SUM(cs.cs_ext_sales_price) DESC) AS month_rank
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES cs
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON cs.cs_sold_date_sk = d.d_date_sk
GROUP BY d.d_year, d.d_moy
ORDER BY d.d_year, d.d_moy;


-- ============================================================================
-- Query 25: Store Returns Analysis by Reason and Geography
-- Estimated scan: ~170 GB (STORE_RETURNS SF10TCL + dimensions)
-- Examines return patterns by return reason, customer state, and store,
-- computing return amount distribution and refund ratios.
-- ============================================================================
SELECT r.r_reason_desc,
       ca.ca_state,
       s.s_store_name,
       COUNT(*) AS return_count,
       SUM(sr.sr_return_amt) AS total_return_amt,
       AVG(sr.sr_return_amt) AS avg_return_amt,
       SUM(sr.sr_fee) AS total_fees,
       SUM(sr.sr_refunded_cash) AS total_refunds,
       ROUND(SUM(sr.sr_refunded_cash) / NULLIF(SUM(sr.sr_return_amt), 0) * 100, 2) AS refund_ratio_pct
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_RETURNS sr
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.REASON r ON sr.sr_reason_sk = r.r_reason_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER_ADDRESS ca ON sr.sr_addr_sk = ca.ca_address_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE s ON sr.sr_store_sk = s.s_store_sk
GROUP BY r.r_reason_desc, ca.ca_state, s.s_store_name
ORDER BY total_return_amt DESC
LIMIT 10000;


-- ============================================================================
-- Query 26: Web Returns vs Web Sales Conversion Analysis
-- Estimated scan: ~585 GB (WEB_SALES 520 GB + WEB_RETURNS 65 GB at SF10TCL)
-- Computes per-item web return rates and net revenue after returns,
-- flagging items with abnormally high return rates.
-- ============================================================================
WITH web_item_sales AS (
    SELECT ws.ws_item_sk,
           COUNT(*) AS sale_count,
           SUM(ws.ws_ext_sales_price) AS gross_revenue,
           SUM(ws.ws_net_profit) AS net_profit
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    GROUP BY ws.ws_item_sk
),
web_item_returns AS (
    SELECT wr.wr_item_sk,
           COUNT(*) AS return_count,
           SUM(wr.wr_return_amt) AS return_amt
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_RETURNS wr
    GROUP BY wr.wr_item_sk
)
SELECT i.i_item_id, i.i_item_desc, i.i_category, i.i_class,
       ws.sale_count,
       COALESCE(wr.return_count, 0) AS return_count,
       ROUND(COALESCE(wr.return_count, 0) * 100.0 / NULLIF(ws.sale_count, 0), 2) AS return_rate_pct,
       ws.gross_revenue,
       COALESCE(wr.return_amt, 0) AS return_amt,
       ws.gross_revenue - COALESCE(wr.return_amt, 0) AS net_revenue,
       CASE
           WHEN COALESCE(wr.return_count, 0) * 100.0 / NULLIF(ws.sale_count, 0) > 20 THEN 'HIGH_RETURN'
           WHEN COALESCE(wr.return_count, 0) * 100.0 / NULLIF(ws.sale_count, 0) > 10 THEN 'MEDIUM_RETURN'
           ELSE 'NORMAL'
       END AS return_flag
FROM web_item_sales ws
LEFT JOIN web_item_returns wr ON ws.ws_item_sk = wr.wr_item_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ws.ws_item_sk = i.i_item_sk
ORDER BY return_rate_pct DESC
LIMIT 10000;


-- ============================================================================
-- Query 27: Catalog Returns by Ship Mode and Warehouse
-- Estimated scan: ~110 GB (CATALOG_RETURNS SF10TCL + dimensions)
-- Analyzes catalog return volumes and costs by shipping mode and warehouse,
-- helping identify fulfillment-related return issues.
-- ============================================================================
SELECT w.w_warehouse_name, w.w_state,
       sm.sm_type AS ship_mode,
       COUNT(*) AS return_count,
       SUM(cr.cr_return_amount) AS total_return_amt,
       SUM(cr.cr_return_quantity) AS total_return_qty,
       AVG(cr.cr_return_amount) AS avg_return_amt,
       SUM(cr.cr_net_loss) AS total_net_loss,
       ROUND(SUM(cr.cr_net_loss) / NULLIF(SUM(cr.cr_return_amount), 0) * 100, 2) AS loss_ratio_pct
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_RETURNS cr
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WAREHOUSE w ON cr.cr_warehouse_sk = w.w_warehouse_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.SHIP_MODE sm ON cr.cr_ship_mode_sk = sm.sm_ship_mode_sk
GROUP BY w.w_warehouse_name, w.w_state, sm.sm_type
ORDER BY total_net_loss DESC
LIMIT 10000;


-- ============================================================================
-- Query 28: Store Sales Top Items by State (Single Quarter)
-- Estimated scan: ~55 GB (STORE_SALES SF10TCL pruned to 1 quarter)
-- Identifies top-selling items per state for a single quarter, with
-- revenue share and cumulative ranking within each state.
-- ============================================================================
SELECT ca.ca_state,
       i.i_item_id, i.i_item_desc, i.i_category,
       SUM(ss.ss_ext_sales_price) AS revenue,
       SUM(ss.ss_quantity) AS units,
       SUM(ss.ss_ext_sales_price) / SUM(SUM(ss.ss_ext_sales_price)) OVER (PARTITION BY ca.ca_state) AS revenue_share,
       ROW_NUMBER() OVER (PARTITION BY ca.ca_state ORDER BY SUM(ss.ss_ext_sales_price) DESC) AS state_rank
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER_ADDRESS ca ON ss.ss_addr_sk = ca.ca_address_sk
WHERE d.d_year = 2002 AND d.d_qoy = 1
GROUP BY ca.ca_state, i.i_item_id, i.i_item_desc, i.i_category
QUALIFY state_rank <= 100
ORDER BY ca.ca_state, state_rank;


-- ============================================================================
-- Query 29: Web Sales Hour-of-Day Analysis
-- Estimated scan: ~520 GB (WEB_SALES SF10TCL + TIME_DIM)
-- Analyzes web purchasing patterns by hour of day, computing conversion
-- metrics, average order value, and peak vs off-peak ratios.
-- ============================================================================
SELECT t.t_hour,
       COUNT(*) AS line_items,
       COUNT(DISTINCT ws.ws_order_number) AS orders,
       SUM(ws.ws_ext_sales_price) AS revenue,
       AVG(ws.ws_ext_sales_price) AS avg_item_price,
       SUM(ws.ws_ext_sales_price) / COUNT(DISTINCT ws.ws_order_number) AS avg_order_value,
       SUM(ws.ws_quantity) AS total_units,
       SUM(ws.ws_net_profit) AS net_profit,
       SUM(ws.ws_ext_sales_price) / SUM(SUM(ws.ws_ext_sales_price)) OVER () AS hour_revenue_share
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.TIME_DIM t ON ws.ws_sold_time_sk = t.t_time_sk
GROUP BY t.t_hour
ORDER BY t.t_hour;


-- ============================================================================
-- Query 30: Catalog Sales Profit Margin by Item Class and Year
-- Estimated scan: ~1 TB (CATALOG_SALES SF10TCL full scan + ITEM)
-- Computes gross margin, profit ranking, and year-over-year margin shift
-- per product class across the catalog channel.
-- ============================================================================
SELECT d.d_year, i.i_category, i.i_class,
       SUM(cs.cs_ext_sales_price) AS gross_revenue,
       SUM(cs.cs_net_profit) AS net_profit,
       ROUND(SUM(cs.cs_net_profit) / NULLIF(SUM(cs.cs_ext_sales_price), 0) * 100, 2) AS margin_pct,
       RANK() OVER (PARTITION BY d.d_year ORDER BY SUM(cs.cs_net_profit) DESC) AS profit_rank,
       SUM(cs.cs_net_profit) - LAG(SUM(cs.cs_net_profit))
           OVER (PARTITION BY i.i_category, i.i_class ORDER BY d.d_year) AS yoy_profit_change
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES cs
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON cs.cs_sold_date_sk = d.d_date_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON cs.cs_item_sk = i.i_item_sk
GROUP BY d.d_year, i.i_category, i.i_class
ORDER BY d.d_year, profit_rank
LIMIT 10000;


-- ============================================================================
-- Query 31: Cross-Channel Customer Overlap (Single Year, SF10TCL)
-- Estimated scan: ~750 GB (STORE_SALES ~200GB + CATALOG_SALES ~200GB +
--                          WEB_SALES ~100GB, all pruned to d_year=2002)
-- Identifies customers active across multiple channels in a given year,
-- computing per-channel spend and a channel diversity score.
-- ============================================================================
WITH store_cust AS (
    SELECT ss.ss_customer_sk AS customer_sk,
           SUM(ss.ss_ext_sales_price) AS store_spend
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002 AND ss.ss_customer_sk IS NOT NULL
    GROUP BY ss.ss_customer_sk
),
catalog_cust AS (
    SELECT cs.cs_bill_customer_sk AS customer_sk,
           SUM(cs.cs_ext_sales_price) AS catalog_spend
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES cs
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON cs.cs_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002 AND cs.cs_bill_customer_sk IS NOT NULL
    GROUP BY cs.cs_bill_customer_sk
),
web_cust AS (
    SELECT ws.ws_bill_customer_sk AS customer_sk,
           SUM(ws.ws_ext_sales_price) AS web_spend
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002 AND ws.ws_bill_customer_sk IS NOT NULL
    GROUP BY ws.ws_bill_customer_sk
)
SELECT c.c_customer_id,
       c.c_first_name || ' ' || c.c_last_name AS customer_name,
       COALESCE(sc.store_spend, 0) AS store_spend,
       COALESCE(cc.catalog_spend, 0) AS catalog_spend,
       COALESCE(wc.web_spend, 0) AS web_spend,
       COALESCE(sc.store_spend, 0) + COALESCE(cc.catalog_spend, 0) + COALESCE(wc.web_spend, 0) AS total_spend,
       (CASE WHEN sc.store_spend IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN cc.catalog_spend IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN wc.web_spend IS NOT NULL THEN 1 ELSE 0 END) AS channels_active,
       NTILE(10) OVER (ORDER BY COALESCE(sc.store_spend, 0) + COALESCE(cc.catalog_spend, 0) + COALESCE(wc.web_spend, 0) DESC) AS spend_decile
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER c
LEFT JOIN store_cust sc ON c.c_customer_sk = sc.customer_sk
LEFT JOIN catalog_cust cc ON c.c_customer_sk = cc.customer_sk
LEFT JOIN web_cust wc ON c.c_customer_sk = wc.customer_sk
WHERE sc.customer_sk IS NOT NULL OR cc.customer_sk IS NOT NULL OR wc.customer_sk IS NOT NULL
QUALIFY channels_active >= 2
ORDER BY total_spend DESC
LIMIT 10000;


-- ============================================================================
-- Query 32: Promotion Effectiveness on Store Sales
-- Estimated scan: ~200 GB (STORE_SALES SF10TCL filtered to 1 year + PROMOTION)
-- Compares revenue and units during promoted vs non-promoted sales for a year,
-- computing lift as the ratio of promo to non-promo average ticket.
-- ============================================================================
SELECT p.p_channel_event, p.p_channel_dmail, p.p_channel_tv,
       p.p_promo_name,
       COUNT(*) AS promo_line_items,
       SUM(ss.ss_ext_sales_price) AS promo_revenue,
       AVG(ss.ss_ext_sales_price) AS avg_promo_ticket,
       SUM(ss.ss_quantity) AS promo_units,
       SUM(ss.ss_coupon_amt) AS total_coupon_discount,
       SUM(ss.ss_net_profit) AS promo_net_profit
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.PROMOTION p ON ss.ss_promo_sk = p.p_promo_sk
WHERE d.d_year = 2001
GROUP BY p.p_channel_event, p.p_channel_dmail, p.p_channel_tv, p.p_promo_name
ORDER BY promo_revenue DESC
LIMIT 10000;


-- ============================================================================
-- Query 33: Web Sales Customer Recency Segmentation
-- Estimated scan: ~520 GB (WEB_SALES SF10TCL full scan + DATE_DIM)
-- Segments customers by their most recent web purchase date into recency
-- buckets and computes lifetime metrics per bucket.
-- ============================================================================
WITH customer_metrics AS (
    SELECT ws.ws_bill_customer_sk AS customer_sk,
           MAX(d.d_date) AS last_purchase_date,
           MIN(d.d_date) AS first_purchase_date,
           COUNT(DISTINCT ws.ws_order_number) AS lifetime_orders,
           SUM(ws.ws_ext_sales_price) AS lifetime_revenue,
           AVG(ws.ws_ext_sales_price) AS avg_item_spend
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    WHERE ws.ws_bill_customer_sk IS NOT NULL
    GROUP BY ws.ws_bill_customer_sk
)
SELECT CASE
           WHEN DATEDIFF('day', last_purchase_date, '2003-01-02') <= 90 THEN 'Active (0-90d)'
           WHEN DATEDIFF('day', last_purchase_date, '2003-01-02') <= 180 THEN 'Warm (91-180d)'
           WHEN DATEDIFF('day', last_purchase_date, '2003-01-02') <= 365 THEN 'Cooling (181-365d)'
           ELSE 'Dormant (365d+)'
       END AS recency_segment,
       COUNT(*) AS customer_count,
       AVG(lifetime_orders) AS avg_orders,
       AVG(lifetime_revenue) AS avg_lifetime_revenue,
       SUM(lifetime_revenue) AS segment_total_revenue,
       AVG(DATEDIFF('day', first_purchase_date, last_purchase_date)) AS avg_customer_lifespan_days
FROM customer_metrics
GROUP BY recency_segment
ORDER BY segment_total_revenue DESC;


-- ============================================================================
-- Query 34: Catalog Sales by Income Band and Item Price Tier
-- Estimated scan: ~1 TB (CATALOG_SALES SF10TCL + INCOME_BAND + ITEM)
-- Analyzes how customer income bands correlate with item price tiers,
-- computing average basket composition and profitability by segment.
-- ============================================================================
SELECT ib.ib_lower_bound || '-' || ib.ib_upper_bound AS income_range,
       CASE
           WHEN i.i_current_price < 20 THEN 'Budget (<$20)'
           WHEN i.i_current_price < 60 THEN 'Mid-range ($20-$60)'
           WHEN i.i_current_price < 150 THEN 'Premium ($60-$150)'
           ELSE 'Luxury ($150+)'
       END AS price_tier,
       COUNT(*) AS line_items,
       COUNT(DISTINCT cs.cs_order_number) AS orders,
       SUM(cs.cs_ext_sales_price) AS revenue,
       AVG(cs.cs_quantity) AS avg_qty,
       SUM(cs.cs_net_profit) AS net_profit,
       ROUND(SUM(cs.cs_net_profit) / NULLIF(SUM(cs.cs_ext_sales_price), 0) * 100, 2) AS margin_pct
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES cs
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.HOUSEHOLD_DEMOGRAPHICS hd ON cs.cs_bill_hdemo_sk = hd.hd_demo_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.INCOME_BAND ib ON hd.hd_income_band_sk = ib.ib_income_band_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON cs.cs_item_sk = i.i_item_sk
GROUP BY income_range, price_tier
ORDER BY income_range, revenue DESC;


-- ============================================================================
-- Query 35: Store Sales Year-over-Year Growth by Manager
-- Estimated scan: ~400 GB (STORE_SALES SF10TCL filtered to 2 years)
-- Computes per-store-manager revenue growth, comparing consecutive fiscal years,
-- ranking managers by growth percentage.
-- ============================================================================
WITH yearly_store_sales AS (
    SELECT s.s_store_sk, s.s_store_name, s.s_manager,
           d.d_year,
           SUM(ss.ss_ext_sales_price) AS annual_revenue,
           COUNT(DISTINCT ss.ss_ticket_number) AS annual_transactions
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE s ON ss.ss_store_sk = s.s_store_sk
    WHERE d.d_year IN (2001, 2002)
    GROUP BY s.s_store_sk, s.s_store_name, s.s_manager, d.d_year
)
SELECT s_store_name, s_manager,
       MAX(CASE WHEN d_year = 2001 THEN annual_revenue END) AS revenue_2001,
       MAX(CASE WHEN d_year = 2002 THEN annual_revenue END) AS revenue_2002,
       MAX(CASE WHEN d_year = 2001 THEN annual_transactions END) AS txns_2001,
       MAX(CASE WHEN d_year = 2002 THEN annual_transactions END) AS txns_2002,
       ROUND((MAX(CASE WHEN d_year = 2002 THEN annual_revenue END) -
              MAX(CASE WHEN d_year = 2001 THEN annual_revenue END)) /
             NULLIF(MAX(CASE WHEN d_year = 2001 THEN annual_revenue END), 0) * 100, 2) AS revenue_growth_pct
FROM yearly_store_sales
GROUP BY s_store_sk, s_store_name, s_manager
HAVING revenue_2001 IS NOT NULL AND revenue_2002 IS NOT NULL
ORDER BY revenue_growth_pct DESC
LIMIT 10000;


-- ============================================================================
-- Query 36: Inventory Turnover by Warehouse and Product Category
-- Estimated scan: ~130 GB (INVENTORY SF10TCL + ITEM + WAREHOUSE + DATE_DIM)
-- Measures inventory turnover by computing average on-hand quantity relative
-- to sales velocity, identifying slow-moving and fast-moving categories.
-- ============================================================================
WITH avg_inventory AS (
    SELECT inv.inv_warehouse_sk, inv.inv_item_sk,
           AVG(inv.inv_quantity_on_hand) AS avg_qty_on_hand
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.INVENTORY inv
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON inv.inv_date_sk = d.d_date_sk
    WHERE d.d_year = 2002
    GROUP BY inv.inv_warehouse_sk, inv.inv_item_sk
),
item_sales AS (
    SELECT ss.ss_item_sk,
           SUM(ss.ss_quantity) AS total_qty_sold
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002
    GROUP BY ss.ss_item_sk
)
SELECT w.w_warehouse_name, w.w_state,
       i.i_category, i.i_class,
       SUM(ai.avg_qty_on_hand) AS total_avg_on_hand,
       COALESCE(SUM(isales.total_qty_sold), 0) AS total_qty_sold,
       ROUND(COALESCE(SUM(isales.total_qty_sold), 0) / NULLIF(SUM(ai.avg_qty_on_hand), 0), 2) AS turnover_ratio,
       CASE
           WHEN COALESCE(SUM(isales.total_qty_sold), 0) / NULLIF(SUM(ai.avg_qty_on_hand), 0) > 10 THEN 'FAST_MOVER'
           WHEN COALESCE(SUM(isales.total_qty_sold), 0) / NULLIF(SUM(ai.avg_qty_on_hand), 0) > 3 THEN 'NORMAL'
           ELSE 'SLOW_MOVER'
       END AS turnover_category
FROM avg_inventory ai
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WAREHOUSE w ON ai.inv_warehouse_sk = w.w_warehouse_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ai.inv_item_sk = i.i_item_sk
LEFT JOIN item_sales isales ON ai.inv_item_sk = isales.ss_item_sk
GROUP BY w.w_warehouse_name, w.w_state, i.i_category, i.i_class
ORDER BY turnover_ratio DESC
LIMIT 10000;


-- ############################################################################
-- MISSING PATTERN QUERIES (Q37-Q48): Patterns not covered above.
-- ############################################################################


-- ============================================================================
-- Query 37: SCD Type-2 Simulation (Detecting Dimension Changes)
-- Pattern: Slowly Changing Dimension — building valid_from/valid_to ranges
-- Estimated scan: ~520 GB (WEB_SALES SF10TCL + CUSTOMER)
-- Simulates detecting changes in customer address over time by examining
-- their purchase history across different ship-to addresses.
-- ============================================================================
WITH customer_address_history AS (
    SELECT ws.ws_bill_customer_sk AS customer_sk,
           ca.ca_state,
           ca.ca_city,
           ca.ca_zip,
           MIN(d.d_date) AS first_seen_date,
           MAX(d.d_date) AS last_seen_date,
           ROW_NUMBER() OVER (PARTITION BY ws.ws_bill_customer_sk ORDER BY MIN(d.d_date)) AS version_num
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER_ADDRESS ca ON ws.ws_ship_addr_sk = ca.ca_address_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    WHERE ws.ws_bill_customer_sk IS NOT NULL
    GROUP BY ws.ws_bill_customer_sk, ca.ca_state, ca.ca_city, ca.ca_zip
)
SELECT customer_sk,
       ca_state, ca_city, ca_zip,
       version_num,
       first_seen_date AS valid_from,
       LEAD(first_seen_date) OVER (PARTITION BY customer_sk ORDER BY version_num) AS valid_to,
       CASE
           WHEN LEAD(first_seen_date) OVER (PARTITION BY customer_sk ORDER BY version_num) IS NULL THEN TRUE
           ELSE FALSE
       END AS is_current,
       DATEDIFF('day', first_seen_date, last_seen_date) AS days_at_address
FROM customer_address_history
QUALIFY version_num > 1 OR LEAD(version_num) OVER (PARTITION BY customer_sk ORDER BY version_num) IS NOT NULL
ORDER BY customer_sk, version_num
LIMIT 10000;


-- ============================================================================
-- Query 38: Sessionization (Gap-Based Session Stitching)
-- Pattern: Assigning session IDs using LAG + conditional SUM over time gaps
-- Estimated scan: ~520 GB (WEB_SALES SF10TCL + TIME_DIM + DATE_DIM)
-- Stitches web sales into sessions: a new session starts when more than
-- 30 minutes elapses between consecutive actions by the same customer.
-- ============================================================================
WITH web_events AS (
    SELECT ws.ws_bill_customer_sk AS customer_sk,
           d.d_date,
           t.t_time AS event_time_seconds,
           ws.ws_order_number,
           ws.ws_ext_sales_price,
           LAG(t.t_time) OVER (PARTITION BY ws.ws_bill_customer_sk, d.d_date ORDER BY t.t_time) AS prev_event_time
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.TIME_DIM t ON ws.ws_sold_time_sk = t.t_time_sk
    WHERE ws.ws_bill_customer_sk IS NOT NULL AND d.d_year = 2002
),
session_boundaries AS (
    SELECT *,
           CASE WHEN prev_event_time IS NULL
                     OR (event_time_seconds - prev_event_time) > 1800
                THEN 1 ELSE 0
           END AS new_session_flag
    FROM web_events
),
sessions AS (
    SELECT *,
           SUM(new_session_flag) OVER (PARTITION BY customer_sk, d_date ORDER BY event_time_seconds
                                       ROWS UNBOUNDED PRECEDING) AS session_id
    FROM session_boundaries
)
SELECT customer_sk, d_date, session_id,
       COUNT(*) AS events_in_session,
       SUM(ws_ext_sales_price) AS session_revenue,
       MIN(event_time_seconds) AS session_start,
       MAX(event_time_seconds) AS session_end,
       MAX(event_time_seconds) - MIN(event_time_seconds) AS session_duration_sec,
       COUNT(DISTINCT ws_order_number) AS orders_in_session
FROM sessions
GROUP BY customer_sk, d_date, session_id
ORDER BY session_revenue DESC
LIMIT 10000;


-- ============================================================================
-- Query 39: Funnel / Sequential Event Analysis
-- Pattern: Ordered conversion steps with drop-off rates between stages
-- Estimated scan: ~720 GB (STORE_SALES + CATALOG_SALES + WEB_SALES SF10TCL, year-filtered)
-- Models a 3-step funnel: Store browse (store purchase) → Catalog follow-up
-- → Web purchase. Measures conversion and drop-off at each stage.
-- ============================================================================
WITH stage1_store AS (
    SELECT DISTINCT ss.ss_customer_sk AS customer_sk,
           MIN(d.d_date) OVER (PARTITION BY ss.ss_customer_sk) AS first_store_date
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002 AND ss.ss_customer_sk IS NOT NULL
),
stage2_catalog AS (
    SELECT DISTINCT cs.cs_bill_customer_sk AS customer_sk,
           MIN(d.d_date) OVER (PARTITION BY cs.cs_bill_customer_sk) AS first_catalog_date
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES cs
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON cs.cs_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002 AND cs.cs_bill_customer_sk IS NOT NULL
),
stage3_web AS (
    SELECT DISTINCT ws.ws_bill_customer_sk AS customer_sk,
           MIN(d.d_date) OVER (PARTITION BY ws.ws_bill_customer_sk) AS first_web_date
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002 AND ws.ws_bill_customer_sk IS NOT NULL
),
funnel AS (
    SELECT s1.customer_sk,
           s1.first_store_date,
           s2.first_catalog_date,
           s3.first_web_date,
           CASE WHEN s2.customer_sk IS NOT NULL AND s2.first_catalog_date > s1.first_store_date THEN 1 ELSE 0 END AS reached_stage2,
           CASE WHEN s3.customer_sk IS NOT NULL AND s3.first_web_date > s2.first_catalog_date THEN 1 ELSE 0 END AS reached_stage3
    FROM stage1_store s1
    LEFT JOIN stage2_catalog s2 ON s1.customer_sk = s2.customer_sk
    LEFT JOIN stage3_web s3 ON s2.customer_sk = s3.customer_sk
)
SELECT COUNT(DISTINCT customer_sk) AS stage1_store_buyers,
       SUM(reached_stage2) AS stage2_catalog_converts,
       SUM(reached_stage3) AS stage3_web_converts,
       ROUND(SUM(reached_stage2) * 100.0 / COUNT(DISTINCT customer_sk), 2) AS stage1_to_2_pct,
       ROUND(SUM(reached_stage3) * 100.0 / NULLIF(SUM(reached_stage2), 0), 2) AS stage2_to_3_pct,
       ROUND(SUM(reached_stage3) * 100.0 / COUNT(DISTINCT customer_sk), 2) AS full_funnel_pct
FROM funnel;


-- ============================================================================
-- Query 40: PIVOT / Crosstab — Monthly Revenue by Channel
-- Pattern: PIVOT turning row values into columns for reporting
-- Estimated scan: ~730 GB (STORE_SALES + WEB_SALES + CATALOG_SALES SF10TCL, year-filtered)
-- Produces a crosstab of monthly revenue by channel using Snowflake PIVOT.
-- ============================================================================
WITH channel_monthly AS (
    SELECT 'Store' AS channel, d.d_moy AS month_num,
           SUM(ss.ss_ext_sales_price) AS revenue
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002
    GROUP BY d.d_moy
    UNION ALL
    SELECT 'Catalog', d.d_moy,
           SUM(cs.cs_ext_sales_price)
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES cs
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON cs.cs_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002
    GROUP BY d.d_moy
    UNION ALL
    SELECT 'Web', d.d_moy,
           SUM(ws.ws_ext_sales_price)
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    WHERE d.d_year = 2002
    GROUP BY d.d_moy
)
SELECT *
FROM channel_monthly
    PIVOT (SUM(revenue) FOR month_num IN (1,2,3,4,5,6,7,8,9,10,11,12))
        AS p (channel, jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec)
ORDER BY channel;


-- ============================================================================
-- Query 41: Semi-Additive Fact — End-of-Week Inventory Snapshots
-- Pattern: Point-in-time snapshot logic (last value per period, not SUM)
-- Estimated scan: ~130 GB (INVENTORY SF10TCL + DATE_DIM)
-- Computes end-of-week inventory positions using LAST_VALUE per warehouse/item,
-- avoiding incorrect summation of snapshot data across time.
-- ============================================================================
WITH weekly_snapshots AS (
    SELECT inv.inv_warehouse_sk,
           inv.inv_item_sk,
           d.d_week_seq,
           d.d_date,
           inv.inv_quantity_on_hand,
           ROW_NUMBER() OVER (
               PARTITION BY inv.inv_warehouse_sk, inv.inv_item_sk, d.d_week_seq
               ORDER BY d.d_date DESC
           ) AS rn
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.INVENTORY inv
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON inv.inv_date_sk = d.d_date_sk
    WHERE d.d_year = 2002
)
SELECT w.w_warehouse_name, i.i_category, i.i_class,
       ws.d_week_seq,
       SUM(ws.inv_quantity_on_hand) AS eow_total_on_hand,
       AVG(ws.inv_quantity_on_hand) AS eow_avg_per_item,
       COUNT(DISTINCT ws.inv_item_sk) AS items_in_stock
FROM weekly_snapshots ws
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WAREHOUSE w ON ws.inv_warehouse_sk = w.w_warehouse_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.ITEM i ON ws.inv_item_sk = i.i_item_sk
WHERE ws.rn = 1
GROUP BY w.w_warehouse_name, i.i_category, i.i_class, ws.d_week_seq
ORDER BY w.w_warehouse_name, ws.d_week_seq, eow_total_on_hand DESC
LIMIT 10000;


-- ============================================================================
-- Query 42: Data Quality / Anomaly Detection (Z-Score Outliers)
-- Pattern: Statistical outlier flagging using Z-scores on metrics
-- Estimated scan: ~200 GB (STORE_SALES SF10TCL filtered to 1 year)
-- Flags stores with daily revenue that deviates more than 3 standard
-- deviations from their own historical mean — a data observability pattern.
-- ============================================================================
WITH daily_store_revenue AS (
    SELECT s.s_store_sk, s.s_store_name,
           d.d_date,
           SUM(ss.ss_ext_sales_price) AS daily_revenue
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE s ON ss.ss_store_sk = s.s_store_sk
    WHERE d.d_year = 2002
    GROUP BY s.s_store_sk, s.s_store_name, d.d_date
),
store_stats AS (
    SELECT *,
           AVG(daily_revenue) OVER (PARTITION BY s_store_sk) AS mean_revenue,
           STDDEV(daily_revenue) OVER (PARTITION BY s_store_sk) AS stddev_revenue
    FROM daily_store_revenue
)
SELECT s_store_name, d_date, daily_revenue,
       mean_revenue, stddev_revenue,
       ROUND((daily_revenue - mean_revenue) / NULLIF(stddev_revenue, 0), 2) AS z_score,
       CASE
           WHEN ABS((daily_revenue - mean_revenue) / NULLIF(stddev_revenue, 0)) > 3 THEN 'ANOMALY'
           WHEN ABS((daily_revenue - mean_revenue) / NULLIF(stddev_revenue, 0)) > 2 THEN 'WARNING'
           ELSE 'NORMAL'
       END AS anomaly_flag
FROM store_stats
WHERE ABS((daily_revenue - mean_revenue) / NULLIF(stddev_revenue, 0)) > 2
ORDER BY ABS(z_score) DESC
LIMIT 10000;


-- ============================================================================
-- Query 43: Incremental Dedup Pattern (QUALIFY ROW_NUMBER)
-- Pattern: The most common ELT/dbt incremental dedup — latest record per key
-- Estimated scan: ~520 GB (WEB_SALES SF10TCL + DATE_DIM)
-- Simulates extracting the most recent web sale per customer-item pair,
-- as would be done in an incremental merge/upsert load.
-- ============================================================================
SELECT ws_bill_customer_sk, ws_item_sk,
       ws_order_number, ws_ext_sales_price, ws_net_profit,
       ws_quantity, d_date AS latest_sale_date
FROM (
    SELECT ws.ws_bill_customer_sk, ws.ws_item_sk,
           ws.ws_order_number, ws.ws_ext_sales_price, ws.ws_net_profit,
           ws.ws_quantity, d.d_date,
           ROW_NUMBER() OVER (
               PARTITION BY ws.ws_bill_customer_sk, ws.ws_item_sk
               ORDER BY d.d_date DESC, ws.ws_sold_time_sk DESC
           ) AS rn
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    WHERE ws.ws_bill_customer_sk IS NOT NULL
)
WHERE rn = 1
ORDER BY latest_sale_date DESC
LIMIT 10000;


-- ============================================================================
-- Query 44: Moving Percentile / SLA Distribution Window
-- Pattern: PERCENTILE_CONT over grouped windows for latency/SLA monitoring
-- Estimated scan: ~200 GB (STORE_SALES SF10TCL filtered to 1 year)
-- Computes monthly P50, P90, P95 of transaction size per store —
-- the pattern used in SLA monitoring and performance baselining.
-- ============================================================================
SELECT s.s_store_name, d.d_year, d.d_moy,
       COUNT(*) AS transaction_count,
       PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ss.ss_ext_sales_price) AS p50_ticket_size,
       PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY ss.ss_ext_sales_price) AS p90_ticket_size,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ss.ss_ext_sales_price) AS p95_ticket_size,
       PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY ss.ss_ext_sales_price) AS p99_ticket_size,
       AVG(ss.ss_ext_sales_price) AS mean_ticket_size,
       ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ss.ss_ext_sales_price) /
             NULLIF(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ss.ss_ext_sales_price), 0), 2) AS p95_p50_ratio
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE s ON ss.ss_store_sk = s.s_store_sk
WHERE d.d_year = 2002
GROUP BY s.s_store_name, d.d_year, d.d_moy
ORDER BY s.s_store_name, d.d_moy;


-- ============================================================================
-- Query 45: Recursive CTE — Customer Referral Chain (Graph Traversal)
-- Pattern: Recursive self-join with depth tracking (org hierarchy / BOM)
-- Estimated scan: ~150 GB (STORE_SALES SF10TCL sampled + CUSTOMER)
-- Models a referral chain: finds customers linked by shared store/date
-- transactions and traverses up to 5 levels deep.
-- ============================================================================
WITH RECURSIVE seed_customers AS (
    SELECT DISTINCT ss_customer_sk AS customer_sk
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES
    WHERE ss_store_sk = 1 AND ss_customer_sk IS NOT NULL
    LIMIT 100
),
referral_links AS (
    SELECT DISTINCT a.ss_customer_sk AS referrer_sk,
           b.ss_customer_sk AS referred_sk
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES a
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES b
        ON a.ss_sold_date_sk = b.ss_sold_date_sk
        AND a.ss_store_sk = b.ss_store_sk
        AND a.ss_customer_sk <> b.ss_customer_sk
        AND a.ss_customer_sk IS NOT NULL
        AND b.ss_customer_sk IS NOT NULL
    WHERE a.ss_store_sk = 1
),
chain AS (
    SELECT customer_sk AS root_sk, customer_sk AS current_sk, 0 AS depth
    FROM seed_customers
    UNION ALL
    SELECT c.root_sk, rl.referred_sk, c.depth + 1
    FROM chain c
    JOIN referral_links rl ON c.current_sk = rl.referrer_sk
    WHERE c.depth < 4
)
SELECT root_sk, depth,
       COUNT(DISTINCT current_sk) AS reachable_customers
FROM chain
GROUP BY root_sk, depth
ORDER BY root_sk, depth;


-- ============================================================================
-- Query 46: UNPIVOT — Normalize Wide Metrics into Long Form
-- Pattern: UNPIVOT turning columns into rows for downstream modeling
-- Estimated scan: ~200 GB (STORE_SALES SF10TCL filtered to 1 year + STORE)
-- Takes multiple revenue/cost metrics per store and unpivots them into a
-- normalized metric_name/metric_value structure.
-- ============================================================================
WITH store_metrics AS (
    SELECT s.s_store_sk, s.s_store_name,
           SUM(ss.ss_ext_sales_price) AS total_revenue,
           SUM(ss.ss_net_profit) AS total_profit,
           SUM(ss.ss_ext_discount_amt) AS total_discounts,
           SUM(ss.ss_coupon_amt) AS total_coupons,
           SUM(ss.ss_ext_wholesale_cost) AS total_wholesale_cost,
           SUM(ss.ss_ext_tax) AS total_tax
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE_SALES ss
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.STORE s ON ss.ss_store_sk = s.s_store_sk
    WHERE d.d_year = 2002
    GROUP BY s.s_store_sk, s.s_store_name
)
SELECT s_store_name, metric_name, metric_value
FROM store_metrics
    UNPIVOT (metric_value FOR metric_name IN (
        total_revenue, total_profit, total_discounts,
        total_coupons, total_wholesale_cost, total_tax
    ))
ORDER BY s_store_name, metric_name;


-- ============================================================================
-- Query 47: Gap-and-Island Detection (Consecutive Activity Ranges)
-- Pattern: Identifying contiguous activity periods and gaps — churn/SLA use case
-- Estimated scan: ~520 GB (WEB_SALES SF10TCL + DATE_DIM)
-- Detects consecutive purchase "islands" and dormant "gaps" per customer,
-- computing streak lengths and gap durations for churn analysis.
-- ============================================================================
WITH customer_active_weeks AS (
    SELECT ws.ws_bill_customer_sk AS customer_sk,
           d.d_week_seq,
           d.d_week_seq - DENSE_RANK() OVER (
               PARTITION BY ws.ws_bill_customer_sk ORDER BY d.d_week_seq
           ) AS island_group
    FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.WEB_SALES ws
    JOIN SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.DATE_DIM d ON ws.ws_sold_date_sk = d.d_date_sk
    WHERE ws.ws_bill_customer_sk IS NOT NULL
),
islands AS (
    SELECT customer_sk,
           island_group,
           MIN(d_week_seq) AS island_start_week,
           MAX(d_week_seq) AS island_end_week,
           COUNT(DISTINCT d_week_seq) AS consecutive_active_weeks
    FROM customer_active_weeks
    GROUP BY customer_sk, island_group
),
with_gaps AS (
    SELECT customer_sk,
           island_start_week, island_end_week, consecutive_active_weeks,
           island_start_week - LAG(island_end_week) OVER (
               PARTITION BY customer_sk ORDER BY island_start_week
           ) AS gap_weeks_before,
           ROW_NUMBER() OVER (PARTITION BY customer_sk ORDER BY island_start_week) AS island_num
    FROM islands
)
SELECT customer_sk, island_num,
       island_start_week, island_end_week,
       consecutive_active_weeks,
       COALESCE(gap_weeks_before, 0) AS gap_weeks_before_island,
       CASE
           WHEN gap_weeks_before > 12 THEN 'CHURNED_RETURNED'
           WHEN gap_weeks_before > 4 THEN 'LAPSED'
           ELSE 'CONTINUOUS'
       END AS activity_pattern
FROM with_gaps
WHERE consecutive_active_weeks >= 3 OR gap_weeks_before > 4
ORDER BY customer_sk, island_num
LIMIT 10000;


-- ============================================================================
-- Query 48: Approximate Top-K / Heavy Hitters (APPROX_TOP_K)
-- Pattern: Scalable cardinality analytics for high-volume streams
-- Estimated scan: ~1 TB (CATALOG_SALES SF10TCL full scan)
-- Uses APPROX_TOP_K to find the most frequently purchased items and most
-- active customers in the catalog channel without exact GROUP BY overhead.
-- ============================================================================
SELECT 'Top Items by Frequency' AS analysis,
       APPROX_TOP_K(cs_item_sk, 100) AS top_100_items
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES;

SELECT 'Top Customers by Order Count' AS analysis,
       APPROX_TOP_K(cs_bill_customer_sk, 100) AS top_100_customers
FROM SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CATALOG_SALES
WHERE cs_bill_customer_sk IS NOT NULL;
