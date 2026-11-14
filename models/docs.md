{% docs order_status %}
Normalised order status (lower case, trimmed).

| status | meaning | counts as revenue |
|---|---|---|
| completed | delivered and kept | yes |
| shipped | on its way | yes |
| pending | placed, not yet paid or packed | no |
| cancelled | cancelled before shipping | no |
| returned | delivered, then returned and refunded | no |

The revenue statuses live in `var('revenue_statuses')`.
{% enddocs %}

{% docs stg_customers %}
One row per customer. The raw extract re-delivers rows and sometimes sends an older version of a
customer next to the current one; the latest `updated_at` wins. Emails are lower-cased and trimmed,
countries upper-cased. Internal QA accounts are kept but flagged with `is_test_account`.
{% enddocs %}

{% docs stg_orders %}
One row per order. Duplicate deliveries are collapsed (latest `updated_at` wins) and status values
such as `"Completed "` or `SHIPPED` are normalised.
{% enddocs %}

{% docs int_orders %}
Valid orders with their line totals and payments. Orders from test accounts and orders that point
at an unknown customer are excluded here; the source tests report how many there were.
{% enddocs %}

{% docs fct_orders %}
The order fact. Incremental (`delete+insert` on `order_id`), filtered on `updated_at`, which is the
later of the order's own update and its last payment. Late status changes and refunds for old
orders are therefore re-processed, and an incremental run gives the same table as a full refresh
(checked by the repo's test suite).
{% enddocs %}

{% docs dim_customers %}
One row per real customer with lifetime metrics from revenue orders and RFM scores (1–5, quintiles,
ties broken by `customer_id` so the result is deterministic) as of `var('as_of_date')`.
{% enddocs %}

{% docs rfm_segment %}
Rule-based segment from the recency (R), frequency (F) and monetary (M) quintile scores, evaluated in this order:

| segment | rule |
|---|---|
| prospect | no revenue orders yet |
| champions | R ≥ 4, F ≥ 4, M ≥ 4 |
| new | exactly one order and R ≥ 4 |
| loyal | F ≥ 4 and R ≥ 3 |
| at_risk | R ≤ 2 and F ≥ 3 |
| hibernating | R ≤ 2 |
| needs_attention | everything else |
{% enddocs %}
