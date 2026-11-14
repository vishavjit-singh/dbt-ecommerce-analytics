-- Order lines. A missing unit price falls back to the product's list price; quantities <= 0 are
-- kept here (so they can be counted) and dropped in the intermediate layer.
with items as (
    select * from {{ source('shop', 'order_items') }}
),

products as (
    select product_id, list_price from {{ ref('stg_products') }}
)

select
    items.order_item_id,
    items.order_id,
    items.product_id,
    cast(items.quantity as integer)                                    as quantity,
    coalesce(cast(items.unit_price as double), products.list_price)    as unit_price,
    case when items.unit_price is null then 1 else 0 end               as is_price_imputed
from items
left join products on items.product_id = products.product_id
