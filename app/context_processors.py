from django.conf import settings

from .models import Affiliate, Category, Order, Payout, Product, ReturnRequest, StockAlert, Wishlist


def nav_counts(request):
    """Cart and wishlist counts for the site navbar."""

    cart = request.session.get('cart', {}) if hasattr(request, 'session') else {}

    cart_count = 0
    for qty in cart.values():
        try:
            cart_count += int(qty)
        except (TypeError, ValueError):
            pass

    user = getattr(request, 'user', None)

    wishlist_ids = (
        list(Wishlist.objects.filter(user=user).values_list('product_id', flat=True))
        if user is not None and user.is_authenticated
        else []
    )

    wishlist_count = len(wishlist_ids)

    return {
        'nav_cart_count': cart_count,
        'nav_wishlist_count': wishlist_count,
        'wishlist_ids': wishlist_ids,
        'nav_categories': Category.objects.all(),
    }


def panel_counts(request):
    """Badge numbers for the management panel sidebar (staff pages only)."""

    path = request.path

    if not (path.startswith('/panel/') or path.startswith('/admin/dashboard')):
        return {}

    user = getattr(request, 'user', None)

    if user is None or not user.is_staff:
        return {}

    return {
        'panel_pending_orders': Order.objects.filter(status='Pending').count(),
        'panel_open_returns': ReturnRequest.objects.filter(status='Requested').count(),
        'panel_low_stock': Product.objects.filter(stock__lte=5, is_available=True).count(),
        'panel_alerts': StockAlert.objects.filter(notified=False).count(),
        'panel_pending_affiliates': Affiliate.objects.filter(status='Pending').count(),
        'panel_payout_requests': Payout.objects.filter(status='Requested').count(),
    }


def site_info(request):
    """Store name for every template as {{ site_name }}."""
    return {'site_name': settings.SITE_NAME}
