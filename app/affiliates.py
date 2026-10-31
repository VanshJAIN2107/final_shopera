"""Affiliate program rules: referral tracking, commissions and payouts."""

import random
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Affiliate, Commission, Payout

COOKIE_NAME = 'vsh_ref'


def default_rate():
    return Decimal(str(settings.AFFILIATE_DEFAULT_COMMISSION))


def min_payout():
    return Decimal(str(settings.AFFILIATE_MIN_PAYOUT))


def make_code(user):
    """Short unique referral code built from the username."""
    base = slugify(user.username).replace('-', '').upper()[:10] or 'AFF'
    code = base

    while Affiliate.objects.filter(code=code).exists():
        code = f'{base}{random.randint(10, 999)}'

    return code


def referral_url(affiliate, path='/'):
    separator = '&' if '?' in path else '?'
    return f"{settings.SITE_URL.rstrip('/')}{path}{separator}ref={affiliate.code}"


def get_referring_affiliate(request, buyer):
    """The approved affiliate whose link brought this visitor, if any.

    An affiliate never earns on their own purchases.
    """
    code = request.COOKIES.get(COOKIE_NAME, '').strip()

    if not code:
        return None

    affiliate = Affiliate.objects.filter(
        code__iexact=code,
        status='Approved'
    ).first()

    if affiliate and affiliate.user_id != buyer.id:
        return affiliate

    return None


def create_commission(order):
    """Create the (pending) commission for an order that came from a referral."""
    if not order.affiliate_id:
        return None

    if Commission.objects.filter(order=order).exists():
        return None

    affiliate = order.affiliate

    if affiliate.status != 'Approved':
        return None

    base = Decimal(order.total_amount)
    rate = Decimal(affiliate.commission_percent)
    amount = (base * rate / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if amount <= 0:
        return None

    return Commission.objects.create(
        affiliate=affiliate,
        order=order,
        order_amount=base,
        rate=rate,
        amount=amount,
    )


def cancel_commission(commission, note='Order was cancelled or refunded.'):
    """Cancel a commission that has not been paid yet."""
    with transaction.atomic():

        if commission.status == 'Paid':
            # money already sent: keep the record, flag it for the admin
            commission.note = 'Order refunded after payout. Deduct from the next payout.'
            commission.save(update_fields=['note'])
            return

        if commission.status == 'Cancelled':
            return

        payout = commission.payout

        if payout and payout.status == 'Requested':
            payout.amount = payout.amount - commission.amount
            if payout.amount <= 0:
                payout.amount = Decimal('0')
                payout.status = 'Rejected'
                payout.note = 'All commissions in this request were cancelled.'
            payout.save(update_fields=['amount', 'status', 'note'])

        commission.status = 'Cancelled'
        commission.payout = None
        commission.note = note
        commission.save(update_fields=['status', 'payout', 'note'])


def sync_commission(order):
    """Keep the commission in step with the order (delivered / cancelled)."""
    commission = Commission.objects.filter(order=order).first()

    if commission is None:
        return

    if order.status == 'Delivered' and commission.status == 'Pending':
        commission.status = 'Approved'
        commission.approved_at = timezone.now()
        commission.save(update_fields=['status', 'approved_at'])

    elif order.status == 'Cancelled':
        cancel_commission(commission)


def request_payout(affiliate):
    """Move every available commission into one payout request.

    Returns (payout, error_message).
    """
    if not affiliate.is_approved:
        return None, 'Your affiliate account is not active.'

    if not affiliate.has_payout_details:
        return None, 'Add your UPI or bank details first.'

    with transaction.atomic():

        commissions = list(
            Commission.objects.select_for_update().filter(
                affiliate=affiliate,
                status='Approved',
                payout__isnull=True,
            )
        )

        total = sum((c.amount for c in commissions), Decimal('0'))

        if total < min_payout():
            return None, f'You need at least Rs. {min_payout()} of approved earnings to request a payout.'

        payout = Payout.objects.create(
            affiliate=affiliate,
            amount=total,
            method_summary=affiliate.payout_summary,
        )

        Commission.objects.filter(id__in=[c.id for c in commissions]).update(payout=payout)

    return payout, ''


def mark_payout_paid(payout, reference='', note=''):
    if payout.status != 'Requested':
        return False

    with transaction.atomic():
        payout.status = 'Paid'
        payout.reference = reference[:120]
        payout.note = note[:255]
        payout.paid_at = timezone.now()
        payout.save(update_fields=['status', 'reference', 'note', 'paid_at'])

        payout.commissions.filter(status='Approved').update(status='Paid')

    return True


def reject_payout(payout, note=''):
    if payout.status != 'Requested':
        return False

    with transaction.atomic():
        payout.status = 'Rejected'
        payout.note = note[:255]
        payout.save(update_fields=['status', 'note'])

        payout.commissions.update(payout=None)       # money goes back to the balance

    return True
