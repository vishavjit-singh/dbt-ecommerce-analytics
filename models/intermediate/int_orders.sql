-- Every valid order with its totals. Valid = placed by a known, non-test customer.
-- Customer order numbering is computed here, over full history, so the incremental fct_orders
-- never has to see old orders to get it right.
with orders as (
    select * from {{ ref('stg_orders') }}
),

customers as (
    select customer_id from {{ ref('stg_customers') }} where is_test_account = 0
),

lines as (
    select
        order_id,
        count(*)               as line_count,
        sum(quantity)          as units,
        sum(line_revenue)      as gross_revenue,
        sum(line_cost)         as cost
    from {{ ref('int_order_lines') }}
    group by order_id
),

payments as (
    select * from {{ ref('int_order_payments') }}
)

select
    orders.order_id,
    orders.customer_id,
    orders.order_ts,
    orders.order_date,
    orders.status,
    orders.channel,
    case when orders.status in {{ revenue_status_list() }} then 1 else 0 end    as is_revenue,
    coalesce(lines.line_count, 0)                                              as line_count,
    coalesce(lines.units, 0)                                                   as units,
    round(coalesce(lines.gross_revenue, 0), 2)                                 as gross_revenue,
    orders.discount_amount,
    round(coalesce(lines.gross_revenue, 0) - orders.discount_amount, 2)        as net_revenue,
    orders.shipping_amount,
    round(coalesce(lines.cost, 0), 2)                                          as cost,
    round(coalesce(lines.gross_revenue, 0) - orders.discount_amount
          - coalesce(lines.cost, 0), 2)                                        as gross_margin,
    round(coalesce(payments.paid_amount, 0), 2)                                as paid_amount,
    round(coalesce(payments.refunded_amount, 0), 2)                            as refunded_amount,
    coalesce(payments.failed_attempts, 0)                                      as failed_payment_attempts,
    payments.payment_methods,
    row_number() over (
        partition by orders.customer_id order by orders.order_ts, orders.order_id
    )                                                                          as customer_order_number,
    case
        when payments.last_payment_at is not null and payments.last_payment_at > orders.updated_at
            then payments.last_payment_at
        else orders.updated_at
    end                                                                        as updated_at
from orders
inner join customers on orders.customer_id = customers.customer_id
left join lines on orders.order_id = lines.order_id
left join payments on orders.order_id = payments.order_id
