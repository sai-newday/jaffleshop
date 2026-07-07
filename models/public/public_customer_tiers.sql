select
    customer_id,
    case
        when lifetime_value >= 100 then 'vip'
    
        when lifetime_value >= 40 then 'regular'
        else 'new'
    end as customer_tier,
    lifetime_value,
    number_of_orders
from {{ ref('public_customers') }}

