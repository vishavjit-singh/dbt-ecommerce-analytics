-- One row per order: duplicate deliveries collapsed (latest update wins), status normalised.
with source as (
    select * from {{ source('shop', 'orders') }}
),

ranked as (
    select
        order_id,
        customer_id,
        {{ xdb_to_timestamp('order_ts') }}                   as order_ts,
        {{ xdb_to_date('order_ts') }}                        as order_date,
        {{ clean_text('status') }}                           as status,
        {{ clean_text('channel') }}                          as channel,
        coalesce(cast(discount_amount as double), 0)         as discount_amount,
        coalesce(cast(shipping_amount as double), 0)         as shipping_amount,
        {{ xdb_to_timestamp('updated_at') }}                 as updated_at,
        row_number() over (
            partition by order_id
            order by {{ xdb_to_timestamp('updated_at') }} desc
        )                                                    as version_rank
    from source
    where order_id is not null
)

select
    order_id,
    customer_id,
    order_ts,
    order_date,
    status,
    channel,
    discount_amount,
    shipping_amount,
    updated_at
from ranked
where version_rank = 1
