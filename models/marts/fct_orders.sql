{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

-- Order fact. Incremental on updated_at (the later of the order's own update and its last payment),
-- so late status changes and refunds for old orders are picked up, not just new orders.
-- A small look-back window absorbs records that land slightly out of order.

select
    order_id,
    customer_id,
    order_ts,
    order_date,
    status,
    channel,
    is_revenue,
    line_count,
    units,
    gross_revenue,
    discount_amount,
    net_revenue,
    shipping_amount,
    cost,
    gross_margin,
    paid_amount,
    refunded_amount,
    failed_payment_attempts,
    payment_methods,
    customer_order_number,
    case when customer_order_number = 1 then 1 else 0 end   as is_first_order,
    updated_at
from {{ ref('int_orders') }}

{% if is_incremental() %}
where updated_at >= (
    select {{ xdb_add_days('max(updated_at)', -var('incremental_lookback_days')) }} from {{ this }}
)
{% endif %}
