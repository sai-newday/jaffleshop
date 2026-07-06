with orders as (
    select * from {{ ref('orders') }}
),

final as (
    select
        order_date,
        count(order_id) as orders_count,
        count(distinct customer_id) as customers_count,
        sum(amount) as gross_revenue,
        avg(amount) as avg_order_value
    from orders
    group by 1
)

select * from final
