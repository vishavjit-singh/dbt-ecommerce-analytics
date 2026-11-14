-- One row per real customer with lifetime value and an RFM segment as of var('as_of_date').
with customers as (
    select * from {{ ref('stg_customers') }} where is_test_account = 0
),

revenue_orders as (
    select * from {{ ref('fct_orders') }} where is_revenue = 1
),

stats as (
    select
        customer_id,
        count(*)                        as lifetime_orders,
        round(sum(net_revenue), 2)      as lifetime_revenue,
        min(order_date)                 as first_order_date,
        max(order_date)                 as last_order_date
    from revenue_orders
    group by customer_id
),

scored as (
    select
        stats.*,
        {{ xdb_days_between('stats.last_order_date', as_of_date()) }}                    as days_since_last_order,
        ntile(5) over (order by {{ xdb_days_between('stats.last_order_date', as_of_date()) }} desc,
                                 stats.customer_id)                                       as recency_score,
        ntile(5) over (order by stats.lifetime_orders, stats.customer_id)                 as frequency_score,
        ntile(5) over (order by stats.lifetime_revenue, stats.customer_id)                as monetary_score
    from stats
)

select
    customers.customer_id,
    customers.email,
    customers.country,
    customers.signup_date,
    {{ xdb_month('customers.signup_date') }}                          as signup_month,
    scored.first_order_date,
    {{ xdb_month('scored.first_order_date') }}                        as cohort_month,
    scored.last_order_date,
    coalesce(scored.lifetime_orders, 0)                               as lifetime_orders,
    coalesce(scored.lifetime_revenue, 0)                              as lifetime_revenue,
    round({{ safe_divide('scored.lifetime_revenue', 'scored.lifetime_orders') }}, 2) as avg_order_value,
    scored.days_since_last_order,
    scored.recency_score,
    scored.frequency_score,
    scored.monetary_score,
    case
        when scored.customer_id is null then 'prospect'
        when scored.recency_score >= 4 and scored.frequency_score >= 4 and scored.monetary_score >= 4 then 'champions'
        when scored.lifetime_orders = 1 and scored.recency_score >= 4 then 'new'
        when scored.frequency_score >= 4 and scored.recency_score >= 3 then 'loyal'
        when scored.recency_score <= 2 and scored.frequency_score >= 3 then 'at_risk'
        when scored.recency_score <= 2 then 'hibernating'
        else 'needs_attention'
    end                                                               as segment
from customers
left join scored on customers.customer_id = scored.customer_id
