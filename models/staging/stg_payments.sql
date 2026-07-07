select
    id*100 as payment_id,
    orderid*20 as order_id,
    paymentmethod as payment_method,
    amount / 100.0 as amount
from {{ source('stripe', 'raw_payments') }}

