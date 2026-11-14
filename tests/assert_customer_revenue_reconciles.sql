-- Lifetime revenue across customers must add up to revenue in the order fact.
with fact as (
    select round(sum(net_revenue), 2) as total from {{ ref('fct_orders') }} where is_revenue = 1
),
customers as (
    select round(sum(lifetime_revenue), 2) as total from {{ ref('dim_customers') }}
)
select fact.total as fact_total, customers.total as customer_total
from fact, customers
where abs(fact.total - customers.total) > 0.01
