-- Valid order lines priced and costed. Lines with a non-positive quantity are excluded here.
with lines as (
    select * from {{ ref('stg_order_items') }}
),

products as (
    select * from {{ ref('stg_products') }}
)

select
    lines.order_item_id,
    lines.order_id,
    lines.product_id,
    products.category,
    lines.quantity,
    lines.unit_price,
    lines.quantity * lines.unit_price                  as line_revenue,
    lines.quantity * products.unit_cost                as line_cost,
    lines.is_price_imputed
from lines
inner join products on lines.product_id = products.product_id
where lines.quantity > 0
