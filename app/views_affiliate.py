"""Affiliate program pages for customers: join, dashboard, payout details."""

import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .affiliates import default_rate, make_code, min_payout, request_payout
from .emails import send_affiliate_approved
from .forms import AffiliateApplyForm, PayoutDetailsForm
from .models import Affiliate, Product


def landing_context():
    return {
        'rate': format(default_rate().normalize(), 'f'),
        'cookie_days': settings.AFFILIATE_COOKIE_DAYS,
        'min_payout': min_payout().quantize(Decimal('1')),
    }


def affiliate_landing(request):

    affiliate = None

    if request.user.is_authenticated:
        affiliate = Affiliate.objects.filter(user=request.user).first()

    return render(request, 'affiliate/landing.html', {
        **landing_context(),
        'affiliate': affiliate,
    })


@login_required
def affiliate_join(request):

    if Affiliate.objects.filter(user=request.user).exists():
        return redirect('affiliate_dashboard')

    form = AffiliateApplyForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():

        auto = settings.AFFILIATE_AUTO_APPROVE

        affiliate = Affiliate.objects.create(
            user=request.user,
            code=make_code(request.user),
            commission_percent=default_rate(),
            promo_description=form.cleaned_data['promo_description'],
            status='Approved' if auto else 'Pending',
            approved_at=timezone.now() if auto else None,
        )

        if auto:
            send_affiliate_approved(affiliate)
            messages.success(request, 'Welcome to the affiliate program! Your links are ready.')
        else:
            messages.success(
                request,
                'Application received. We will review it and email you once it is approved.'
            )

        return redirect('affiliate_dashboard')

    return render(request, 'affiliate/join.html', {
        **landing_context(),
        'form': form,
    })


def _chart(affiliate, days=14):
    start = timezone.localdate() - timedelta(days=days - 1)

    clicks = {
        row['d']: row['n']
        for row in affiliate.clicks.filter(created_at__date__gte=start)
        .annotate(d=TruncDate('created_at')).values('d').annotate(n=Count('id'))
    }

    orders = {
        row['d']: row['n']
        for row in affiliate.commissions.exclude(status='Cancelled')
        .filter(created_at__date__gte=start)
        .annotate(d=TruncDate('created_at')).values('d').annotate(n=Count('id'))
    }

    labels, click_data, order_data = [], [], []

    for i in range(days):
        day = start + timedelta(days=i)
        labels.append(day.strftime('%d %b'))
        click_data.append(clicks.get(day, 0))
        order_data.append(orders.get(day, 0))

    return labels, click_data, order_data


@login_required
def affiliate_dashboard(request):

    affiliate = Affiliate.objects.filter(user=request.user).first()

    if affiliate is None:
        return redirect('affiliate_landing')

    clicks_total = affiliate.clicks.count()
    clicks_30 = affiliate.clicks.filter(
        created_at__gte=timezone.now() - timedelta(days=30)
    ).count()

    commissions = affiliate.commissions.select_related('order')
    orders_total = commissions.exclude(status='Cancelled').count()

    available = affiliate.available_balance

    labels, click_data, order_data = _chart(affiliate)

    base = request.build_absolute_uri('/').rstrip('/')

    products = [
        {'name': p.name, 'url': base + p.get_absolute_url()}
        for p in Product.objects.filter(is_available=True).order_by('name')
    ]

    context = {
        'affiliate': affiliate,
        'ref_link': f'{base}/?ref={affiliate.code}',
        'base_url': base,
        'products': products,
        'clicks_total': clicks_total,
        'clicks_30': clicks_30,
        'orders_total': orders_total,
        'conversion': round(orders_total * 100 / clicks_total, 1) if clicks_total else 0,
        'pending': affiliate.pending_amount,
        'available': available,
        'requested': affiliate.requested_amount,
        'paid': affiliate.paid_amount,
        'lifetime': affiliate.lifetime_earnings,
        'min_payout': min_payout().quantize(Decimal('1')),
        'can_request': (
            affiliate.is_approved
            and affiliate.has_payout_details
            and available >= min_payout()
        ),
        'commissions': commissions[:25],
        'payouts': affiliate.payouts.all()[:15],
        'details_form': PayoutDetailsForm(initial={
            'payout_method': affiliate.payout_method or 'UPI',
            'upi_id': affiliate.upi_id,
            'account_holder': affiliate.account_holder,
            'bank_name': affiliate.bank_name,
            'account_number': affiliate.account_number,
            'ifsc': affiliate.ifsc,
        }),
        'chart_labels': json.dumps(labels),
        'chart_clicks': json.dumps(click_data),
        'chart_orders': json.dumps(order_data),
        'cookie_days': settings.AFFILIATE_COOKIE_DAYS,
    }

    return render(request, 'affiliate/dashboard.html', context)


@login_required
@require_POST
def affiliate_settings(request):

    affiliate = Affiliate.objects.filter(user=request.user).first()

    if affiliate is None:
        return redirect('affiliate_landing')

    form = PayoutDetailsForm(request.POST)

    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(f"{reverse('affiliate_dashboard')}#payout-details")

    data = form.cleaned_data

    affiliate.payout_method = data['payout_method']
    affiliate.upi_id = data.get('upi_id', '') if data['payout_method'] == 'UPI' else ''
    affiliate.account_holder = data.get('account_holder', '') if data['payout_method'] == 'BANK' else ''
    affiliate.bank_name = data.get('bank_name', '') if data['payout_method'] == 'BANK' else ''
    affiliate.account_number = data.get('account_number', '') if data['payout_method'] == 'BANK' else ''
    affiliate.ifsc = data.get('ifsc', '') if data['payout_method'] == 'BANK' else ''
    affiliate.save()

    messages.success(request, 'Payout details saved.')

    return redirect('affiliate_dashboard')


@login_required
@require_POST
def affiliate_payout_request(request):

    affiliate = Affiliate.objects.filter(user=request.user).first()

    if affiliate is None:
        return redirect('affiliate_landing')

    payout, error = request_payout(affiliate)

    if error:
        messages.error(request, error)
    else:
        messages.success(
            request,
            f'Payout of Rs. {payout.amount} requested. We will pay it to {payout.method_summary}.'
        )

    return redirect('affiliate_dashboard')
