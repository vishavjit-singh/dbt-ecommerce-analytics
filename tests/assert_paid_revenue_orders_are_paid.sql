-- Completed orders must have captured at least their net revenue plus shipping.
select order_id, net_revenue, shipping_amount, paid_amount
from {{ ref('fct_orders') }}
where status = 'completed'
  and paid_amount + 0.01 < net_revenue + shipping_amount
