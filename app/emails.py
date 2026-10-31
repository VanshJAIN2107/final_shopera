import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse

logger = logging.getLogger(__name__)


def _absolute(path):
    return settings.SITE_URL.rstrip('/') + path


def _send(subject, text, to):
    """Send an email and never let a mail failure break the shop."""
    if not to:
        return False

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to] if isinstance(to, str) else list(to),
        )
        message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('Could not send email "%s"', subject)
        return False


def send_order_confirmation(order):
    """Email the customer after an order is placed."""
    lines = [
        f'Hi {order.full_name},',
        '',
        f'Thank you for shopping with {settings.SITE_NAME}! Your order #{order.id} is confirmed.',
        '',
        'Items:',
    ]

    for item in order.items.select_related('product'):
        lines.append(
            f'  - {item.product.name} x {item.quantity}  (Rs. {item.total_price})'
        )

    lines.append('')

    if order.discount_amount:
        lines.append(f'Coupon {order.coupon_code}: -Rs. {order.discount_amount}')

    lines += [
        f'Order total: Rs. {order.total_amount}',
        f'Payment: {order.get_payment_method_display()} ({order.payment_status})',
        '',
        'Delivering to:',
        f'{order.full_name}, {order.phone}',
        order.full_address,
        '',
        'Track your order here:',
        _absolute(reverse('order_detail', args=[order.id])),
        '',
        settings.SITE_NAME,
    ]

    return _send(
        f'Order #{order.id} confirmed - {settings.SITE_NAME}',
        '\n'.join(lines),
        order.user.email,
    )


def send_order_status_update(order):
    """Email the customer when the status of an order changes."""
    messages_by_status = {
        'Processing': 'We are now preparing your order.',
        'Shipped': 'Good news, your order has been shipped and is on its way.',
        'Delivered': 'Your order has been delivered. We hope you love it!',
        'Cancelled': 'Your order has been cancelled.',
    }

    note = messages_by_status.get(order.status)

    if not note:
        return False

    text = '\n'.join([
        f'Hi {order.full_name},',
        '',
        f'Update for order #{order.id}: {order.status}.',
        note,
        '',
        'View your order:',
        _absolute(reverse('order_detail', args=[order.id])),
        '',
        settings.SITE_NAME,
    ])

    return _send(
        f'Order #{order.id} is {order.status.lower()} - {settings.SITE_NAME}',
        text,
        order.user.email,
    )


def send_back_in_stock(alert):
    product = alert.product

    text = '\n'.join([
        'Good news!',
        '',
        f'{product.name} is back in stock.',
        _absolute(reverse('product_detail', args=[product.slug])),
        '',
        settings.SITE_NAME,
    ])

    return _send(
        f'{product.name} is back in stock',
        text,
        alert.email,
    )

def send_affiliate_approved(affiliate):
    text = '\n'.join([
        f'Hi {affiliate.user.first_name or affiliate.user.username},',
        '',
        f'Good news! Your {settings.SITE_NAME} affiliate account is approved.',
        f'Your referral code: {affiliate.code}',
        f'Commission: {affiliate.commission_percent}% of every order you refer.',
        '',
        'Open your affiliate dashboard to get your links:',
        _absolute(reverse('affiliate_dashboard')),
        '',
        settings.SITE_NAME,
    ])

    return _send(f'Your {settings.SITE_NAME} affiliate account is approved', text, affiliate.user.email)


def send_payout_paid(payout):
    text = '\n'.join([
        f'Hi {payout.affiliate.user.first_name or payout.affiliate.user.username},',
        '',
        f'We have paid your affiliate payout of Rs. {payout.amount}.',
        f'Sent to: {payout.method_summary}',
        f'Reference: {payout.reference or "-"}',
        '',
        f'Thank you for promoting {settings.SITE_NAME}!',
    ])

    return _send(f'Your {settings.SITE_NAME} affiliate payout was sent', text, payout.affiliate.user.email)