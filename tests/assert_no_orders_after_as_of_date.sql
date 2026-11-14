-- No order may be dated after the as-of date used for recency metrics.
select order_id, order_date
from {{ ref('fct_orders') }}
where order_date > {{ as_of_date() }}
