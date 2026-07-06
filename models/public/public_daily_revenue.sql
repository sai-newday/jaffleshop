select
    order_date,
    orders_count,
    customers_count,
    gross_revenue,
    avg_order_value
from {{ ref('daily_revenue') }}
