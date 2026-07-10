select
    id as customer_id,
    first_name,
    last_name,
    email  -- Added email field for blast radius validation
from {{ source('jaffle_shop', 'raw_customers') }}

