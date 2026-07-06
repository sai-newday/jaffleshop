with orders as (
    select * from {{ ref('stg_orders') }}
),

payments as (
    select
        order_id,
        sum(case when payment_method = 'bank_transfer' then amount else 0 end) as bank_transfer_amount,
        sum(case when payment_method = 'credit_card' then amount else 0 end) as credit_card_amount,
        sum(case when payment_method = 'coupon' then amount else 0 end) as coupon_amount,
        sum(case when payment_method = 'gift_card' then amount else 0 end) as gift_card_amount,
        sum(amount) as amount
    from {{ ref('stg_payments') }}
    group by 1
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        orders.order_date,
        orders.status,
        coalesce(payments.amount, 0) as amount,
        payments.bank_transfer_amount,
        payments.credit_card_amount,
        payments.coupon_amount,
        payments.gift_card_amount
    from orders
    left join payments on orders.order_id = payments.order_id
)

select * from final

