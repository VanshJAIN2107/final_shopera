"""Razorpay payment completion, shared by the browser callback and the webhook."""

import hashlib
import hmac
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F

from .affiliates import create_commission
from .emails import send_order_confirmation
from .models import Coupon, Order, Product

logger = logging.getLogger(__name__)


def finalize_paid_order(order_id, payment_id='', signature=''):
    """Mark a Razorpay order as paid and take the stock.

    Safe to call more than once (browser callback and webhook can both arrive):
    only the first call does the work. Returns True when this call finished it.
    """
    short = []

    with transaction.atomic():

        order = Order.objects.select_for_update().get(pk=order_id)

        if order.payment_status == 'Paid':
            return False

        for item in order.items.select_related('product'):

            product = Product.objects.select_for_update().get(pk=item.product_id)

            take = min(item.quantity, product.stock)

            if take < item.quantity:
                short.append(f'{product.name} (wanted {item.quantity}, had {product.stock})')

            if take:
                product.stock -= take
                product.save(update_fields=['stock'])

        note = ''
        status = 'Processing'

        if short:
            # the customer already paid, so keep the order and flag it for the admin
            note = ('PAID BUT STOCK SHORT: ' + '; '.join(short))[:255]
            status = 'Pending'
            logger.warning('Order %s paid but stock short: %s', order.pk, short)

        Order.objects.filter(pk=order.pk).update(
            payment_status='Paid',
            razorpay_payment_id=payment_id or order.razorpay_payment_id,
            razorpay_signature=signature or order.razorpay_signature,
            status=status,
            admin_note=note or order.admin_note,
        )

        if order.coupon_code:
            Coupon.objects.filter(code=order.coupon_code).update(
                times_used=F('times_used') + 1
            )

    order.refresh_from_db()

    create_commission(order)
    send_order_confirmation(order)

    return True


def webhook_signature_ok(body: bytes, signature: str) -> bool:
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    if not secret or not signature:
        return False

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected, signature)
