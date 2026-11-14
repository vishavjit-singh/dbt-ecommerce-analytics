-- By definition every customer is active in the month of their first order.
select cohort_month, retention_rate
from {{ ref('fct_cohort_retention') }}
where months_since_first_order = 0 and retention_rate <> 1
