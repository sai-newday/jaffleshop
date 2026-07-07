select
    id as customer_id,
    first_name,
    null as new_col
from {{ source('jaffle_shop', 'raw_customers') }}

