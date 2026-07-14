select
    a.id as payment_id,
    a.orderid as order_id,
    a.paymentmethod || ' ' as payment_method,
    a.amount / 100.0 as amount
from {{ source('stripe', 'raw_payments') }} 

