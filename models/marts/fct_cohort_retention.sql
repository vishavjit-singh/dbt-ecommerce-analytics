-- Monthly cohort retention: of the customers whose first revenue order fell in a month, how many
-- ordered again N months later.
with activity as (
    select distinct
        customer_id,
        {{ xdb_month('order_date') }} as order_month
    from {{ ref('fct_orders') }}
    where is_revenue = 1
),

cohorts as (
    select customer_id, min(order_month) as cohort_month
    from activity
    group by customer_id
),

sizes as (
    select cohort_month, count(*) as cohort_size
    from cohorts
    group by cohort_month
),

cohort_activity as (
    select
        cohorts.cohort_month,
        {{ xdb_months_between('cohorts.cohort_month', 'activity.order_month') }} as months_since_first_order,
        activity.customer_id
    from activity
    inner join cohorts on activity.customer_id = cohorts.customer_id
)

select
    cohort_activity.cohort_month,
    cohort_activity.months_since_first_order,
    sizes.cohort_size,
    count(*)                                                                 as active_customers,
    round({{ safe_divide('count(*)', 'sizes.cohort_size') }}, 4)             as retention_rate
from cohort_activity
inner join sizes on cohort_activity.cohort_month = sizes.cohort_month
group by cohort_activity.cohort_month, cohort_activity.months_since_first_order, sizes.cohort_size
