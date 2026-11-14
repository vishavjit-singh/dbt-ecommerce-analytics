-- Units, revenue and margin per product from revenue-bearing orders, ranked within the category.
with lines as (
    select * from {{ ref('int_order_lines') }}
),

orders as (
    select order_id from {{ ref('fct_orders') }} where is_revenue = 1
),

products as (
    select * from {{ ref('stg_products') }}
),

agg as (
    select
        lines.product_id,
        count(distinct lines.order_id)            as orders,
        sum(lines.quantity)                       as units,
        round(sum(lines.line_revenue), 2)         as revenue,
        round(sum(lines.line_cost), 2)            as cost
    from lines
    inner join orders on lines.order_id = orders.order_id
    group by lines.product_id
)

select
    products.product_id,
    products.product_name,
    products.category,
    products.is_active,
    coalesce(agg.orders, 0)                                          as orders,
    coalesce(agg.units, 0)                                           as units,
    coalesce(agg.revenue, 0)                                         as revenue,
    coalesce(agg.cost, 0)                                            as cost,
    round(coalesce(agg.revenue, 0) - coalesce(agg.cost, 0), 2)       as margin,
    round({{ safe_divide('coalesce(agg.revenue, 0) - coalesce(agg.cost, 0)', 'agg.revenue') }}, 4) as margin_pct,
    rank() over (partition by products.category order by coalesce(agg.revenue, 0) desc) as category_rank
from products
left join agg on products.product_id = agg.product_id
