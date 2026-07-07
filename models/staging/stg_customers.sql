select
    id as customer_id,
    first_name
from {{ source('jaffle_shop', 'raw_customers') }}
