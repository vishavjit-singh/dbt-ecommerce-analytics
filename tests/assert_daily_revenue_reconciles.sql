-- Total revenue in the daily mart must equal the revenue orders in the fact table (to the cent).
with fact as (
    select round(sum(net_revenue), 2) as total from {{ ref('fct_orders') }} where is_revenue = 1
),
daily as (
    select round(sum(net_revenue), 2) as total from {{ ref('fct_daily_revenue') }}
)
select fact.total as fact_total, daily.total as daily_total
from fact, daily
where abs(fact.total - daily.total) > 0.01
