{% snapshot customers_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='customer_id',
        strategy='timestamp',
        updated_at='updated_at'
    )
}}

-- SCD type 2 history of customer attributes (country, email, ...). Built on the de-duplicated
-- staging view: the raw extract can hold several rows per customer, which a snapshot cannot take.
select customer_id, email, country, signup_date, updated_at, is_test_account
from {{ ref('stg_customers') }}

{% endsnapshot %}
