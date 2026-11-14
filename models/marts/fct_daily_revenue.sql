-- Revenue per day from revenue-bearing orders (completed or shipped), with a trailing 7-day average.
with orders as (
    select * from {{ ref('fct_orders') }} where is_revenue = 1
),

daily as (
    select
        order_date,
        count(*)                                        as orders,
        count(distinct customer_id)                     as customers,
        sum(is_first_order)                             as first_orders,
        round(sum(net_revenue), 2)                      as net_revenue,
        round(sum(gross_margin), 2)                     as gross_margin
    from orders
    group by order_date
)

select
    order_date,
    orders,
    customers,
    first_orders,
    net_revenue,
    gross_margin,
    round({{ safe_divide('net_revenue', 'orders') }}, 2)        as avg_order_value,
    round(avg(net_revenue) over (
        order by order_date rows between 6 preceding and current row
    ), 2)                                                        as net_revenue_7d_avg
from daily
