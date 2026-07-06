with orders as (
    select * from {{ ref('orders') }}
),

final as (
    select
        status,
        count(order_id) as orders_count,
        count(distinct customer_id) as customers_count,
        sum(amount) as total_amount,
        avg(amount) as avg_order_value
    from orders
    group by 1
)

select * from final
