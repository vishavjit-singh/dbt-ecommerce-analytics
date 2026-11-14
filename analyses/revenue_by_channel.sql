-- Ad-hoc analysis (compiled by `dbt compile`, not materialised): revenue mix by channel and month.
select
    {{ xdb_month('order_date') }} as month,
    channel,
    count(*)                      as orders,
    round(sum(net_revenue), 2)    as net_revenue
from {{ ref('fct_orders') }}
where is_revenue = 1
group by 1, 2
order by 1, 2
