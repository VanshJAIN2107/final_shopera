"""Management panel pages for the affiliate program (staff only)."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .affiliates import mark_payout_paid, reject_payout
from .emails import send_affiliate_approved, send_payout_paid
from .models import Affiliate, Commission, Payout


def _paginate(request, queryset, per_page=20):
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return page_obj, params.urlencode()


@staff_member_required
def panel_affiliates(request):

    affiliates = Affiliate.objects.select_related('user').annotate(
        click_count=Count('clicks', distinct=True),
        order_count=Count('commissions', filter=~Q(commissions__status='Cancelled'), distinct=True),
        earned=Sum('commissions__amount', filter=~Q(commissions__status='Cancelled')),
    )

    status = request.GET.get('status', '')
    query = request.GET.get('q', '').strip()

    if status in dict(Affiliate.STATUS_CHOICES):
        affiliates = affiliates.filter(status=status)

    if query:
        affiliates = affiliates.filter(
            Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
            | Q(code__icontains=query)
        )

    page_obj, querystring = _paginate(request, affiliates.order_by('-created_at'))

    counts = {
        row['status']: row['n']
        for row in Affiliate.objects.values('status').annotate(n=Count('id'))
    }

    return render(request, 'panel/affiliates.html', {
        'panel_active': 'affiliates',
        'page_title': 'Affiliates',
        'page_obj': page_obj,
        'querystring': querystring,
        'status': status,
        'query': query,
        'status_choices': Affiliate.STATUS_CHOICES,
        'counts': counts,
        'total': sum(counts.values()),
    })


@staff_member_required
def panel_affiliate_detail(request, affiliate_id):

    affiliate = get_object_or_404(
        Affiliate.objects.select_related('user'),
        id=affiliate_id
    )

    return render(request, 'panel/affiliate_detail.html', {
        'panel_active': 'affiliates',
        'page_title': affiliate.user.username,
        'affiliate': affiliate,
        'status_choices': Affiliate.STATUS_CHOICES,
        'clicks_total': affiliate.clicks.count(),
        'orders_total': affiliate.commissions.exclude(status='Cancelled').count(),
        'commissions': affiliate.commissions.select_related('order')[:30],
        'payouts': affiliate.payouts.all()[:20],
        'recent_clicks': affiliate.clicks.all()[:15],
    })


@staff_member_required
@require_POST
def panel_affiliate_update(request, affiliate_id):

    affiliate = get_object_or_404(Affiliate, id=affiliate_id)

    status = request.POST.get('status', affiliate.status)

    try:
        percent = Decimal(request.POST.get('commission_percent', affiliate.commission_percent))
    except InvalidOperation:
        percent = None

    if status not in dict(Affiliate.STATUS_CHOICES):
        messages.error(request, 'Invalid status.')
        return redirect('panel_affiliate_detail', affiliate_id=affiliate.id)

    if percent is None or percent < 0 or percent > 100:
        messages.error(request, 'Commission must be between 0 and 100 percent.')
        return redirect('panel_affiliate_detail', affiliate_id=affiliate.id)

    newly_approved = status == 'Approved' and affiliate.status != 'Approved'

    affiliate.status = status
    affiliate.commission_percent = percent

    if newly_approved:
        affiliate.approved_at = timezone.now()

    affiliate.save()

    if newly_approved:
        send_affiliate_approved(affiliate)
        messages.success(request, f'{affiliate.user.username} approved. They were emailed.')
    else:
        messages.success(request, 'Affiliate updated. The new rate applies to future orders only.')

    return redirect('panel_affiliate_detail', affiliate_id=affiliate.id)


@staff_member_required
@require_POST
def panel_affiliate_quick(request, affiliate_id):
    """Approve / suspend / reactivate straight from the list."""

    affiliate = get_object_or_404(Affiliate, id=affiliate_id)
    action = request.POST.get('action')

    if action == 'approve' and affiliate.status != 'Approved':
        affiliate.status = 'Approved'
        affiliate.approved_at = timezone.now()
        affiliate.save(update_fields=['status', 'approved_at'])
        send_affiliate_approved(affiliate)
        messages.success(request, f'{affiliate.user.username} approved. They were emailed.')
    elif action == 'suspend':
        affiliate.status = 'Suspended'
        affiliate.save(update_fields=['status'])
        messages.success(request, f'{affiliate.user.username} suspended. Their link stops earning.')

    return redirect(request.POST.get('next') or 'panel_affiliates')


@staff_member_required
def panel_commissions(request):

    commissions = Commission.objects.select_related('affiliate__user', 'order')

    status = request.GET.get('status', '')

    if status in dict(Commission.STATUS_CHOICES):
        commissions = commissions.filter(status=status)

    page_obj, querystring = _paginate(request, commissions.order_by('-created_at'))

    totals = {
        row['status']: row['t']
        for row in Commission.objects.values('status').annotate(t=Sum('amount'))
    }

    return render(request, 'panel/commissions.html', {
        'panel_active': 'commissions',
        'page_title': 'Commissions',
        'page_obj': page_obj,
        'querystring': querystring,
        'status': status,
        'status_choices': Commission.STATUS_CHOICES,
        'totals': totals,
    })


@staff_member_required
def panel_payouts(request):

    payouts = Payout.objects.select_related('affiliate__user')

    status = request.GET.get('status', '')

    if status in dict(Payout.STATUS_CHOICES):
        payouts = payouts.filter(status=status)

    page_obj, querystring = _paginate(request, payouts.order_by('-requested_at'))

    counts = {
        row['status']: row['n']
        for row in Payout.objects.values('status').annotate(n=Count('id'))
    }

    return render(request, 'panel/payouts.html', {
        'panel_active': 'payouts',
        'page_title': 'Payouts',
        'page_obj': page_obj,
        'querystring': querystring,
        'status': status,
        'status_choices': Payout.STATUS_CHOICES,
        'counts': counts,
        'total': sum(counts.values()),
        'owed': Payout.objects.filter(status='Requested').aggregate(t=Sum('amount'))['t'] or 0,
    })


@staff_member_required
@require_POST
def panel_payout_paid(request, payout_id):

    payout = get_object_or_404(Payout, id=payout_id)

    reference = request.POST.get('reference', '').strip()

    if not reference:
        messages.error(request, 'Enter the UPI / bank reference number so there is a record.')
        return redirect('panel_payouts')

    if mark_payout_paid(payout, reference, request.POST.get('note', '').strip()):
        send_payout_paid(payout)
        messages.success(request, f'Payout #{payout.id} marked as paid. The affiliate was emailed.')
    else:
        messages.error(request, 'This payout was already handled.')

    return redirect('panel_payouts')


@staff_member_required
@require_POST
def panel_payout_reject(request, payout_id):

    payout = get_object_or_404(Payout, id=payout_id)

    if reject_payout(payout, request.POST.get('note', '').strip()):
        messages.success(request, f'Payout #{payout.id} rejected. The money is back in their balance.')
    else:
        messages.error(request, 'This payout was already handled.')

    return redirect('panel_payouts')
