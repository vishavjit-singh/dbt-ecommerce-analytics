with source as (
    select * from {{ source('shop', 'products') }}
)

select
    product_id,
    trim(product_name)                                   as product_name,
    {{ clean_text('category') }}                         as category,
    cast(unit_cost as double)                            as unit_cost,
    cast(list_price as double)                           as list_price,
    case when lower(trim(is_active)) in ('true', '1', 'yes') then 1 else 0 end as is_active
from source
