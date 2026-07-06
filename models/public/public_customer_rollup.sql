select
    customer_tier,
    count(*) as customer_count,
    avg(lifetime_value) as avg_lifetime_value,
    avg(number_of_orders) as avg_orders_per_customer,
    1 as temp
from {{ ref('public_customer_tiers') }}
group by 1

