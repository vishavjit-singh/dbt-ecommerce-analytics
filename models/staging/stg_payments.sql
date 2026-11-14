with source as (
    select * from {{ source('shop', 'payments') }}
)

select
    payment_id,
    order_id,
    {{ clean_text('payment_method') }}          as payment_method,
    cast(amount as double)                      as amount,
    {{ clean_text('status') }}                  as status,
    {{ xdb_to_timestamp('created_at') }}        as created_at
from source
