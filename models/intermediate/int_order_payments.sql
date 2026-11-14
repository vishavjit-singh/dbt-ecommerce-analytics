-- Payments rolled up to the order: what was captured, what was refunded, which methods were used.
with payments as (
    select * from {{ ref('stg_payments') }}
)

select
    order_id,
    sum(case when status = 'success' then amount else 0 end)      as paid_amount,
    sum(case when status = 'refunded' then amount else 0 end)     as refunded_amount,
    sum(case when status = 'failed' then 1 else 0 end)            as failed_attempts,
    {{ xdb_listagg_distinct('payment_method') }}                  as payment_methods,
    max(created_at)                                               as last_payment_at
from payments
group by order_id
