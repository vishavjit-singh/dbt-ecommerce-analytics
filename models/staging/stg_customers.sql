-- One row per customer: the latest version wins, emails and countries normalised, test accounts flagged.
with source as (
    select * from {{ source('shop', 'customers') }}
),

ranked as (
    select
        customer_id,
        lower(trim(email))                         as email,
        trim(first_name)                           as first_name,
        trim(last_name)                            as last_name,
        upper(trim(country))                       as country,
        {{ xdb_to_date('signup_date') }}           as signup_date,
        {{ xdb_to_timestamp('updated_at') }}       as updated_at,
        row_number() over (
            partition by customer_id
            order by {{ xdb_to_timestamp('updated_at') }} desc
        )                                          as version_rank
    from source
    where customer_id is not null
)

select
    customer_id,
    email,
    first_name,
    last_name,
    country,
    signup_date,
    updated_at,
    case when email like '%@test.example.com' then 1 else 0 end as is_test_account
from ranked
where version_rank = 1
