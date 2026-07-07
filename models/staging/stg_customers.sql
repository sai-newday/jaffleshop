select
    cast(id as bigint) as customer_id,
    first_name,
    last_name
from {{ source('jaffle_shop', 'raw_customers') }}

