select
    status,
    orders_count,
    customers_count,
    total_amount,
    avg_order_value
from {{ ref('order_status_summary') }}
