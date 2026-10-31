"""
Store management panel (/panel/...): products, categories, orders,
customers, coupons, reviews, returns and stock alerts in one place.
Everything here is staff-only.
"""

import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CategoryForm, CouponForm, OrderUpdateForm, ProductForm
from .models import (
    Address,
    Category,
    Coupon,
    Order,
    OrderItem,
    Product,
    ProductImage,
    ReturnRequest,
    Review,
    StockAlert,
    Wishlist,
)

PER_PAGE = 20
LOW_STOCK_LIMIT = 5


def paginate(request, queryset, per_page=PER_PAGE):
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))

    params = request.GET.copy()
    params.pop('page', None)

    return page_obj, params.urlencode()


def back_to(request, default):
    """Return to the page the action came from (only on this site)."""
    target = request.POST.get('next', '')

    if target.startswith('/panel/') or target.startswith('/admin/dashboard/'):
        return redirect(target)

    return redirect(default)


def to_decimal(value):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError):
        return None
    return number if number >= 0 else None


# =========================================================
# HOME
# =========================================================

@staff_member_required
def panel_home(request):
    return redirect('admin_dashboard')


# =========================================================
# PRODUCTS
# =========================================================

@staff_member_required
def panel_products(request):

    products = Product.objects.select_related('category')

    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    stock = request.GET.get('stock', '')
    sort = request.GET.get('sort', 'newest')

    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(slug__icontains=query)
        )

    if category.isdigit():
        products = products.filter(category_id=category)

    if stock == 'low':
        products = products.filter(stock__gt=0, stock__lte=LOW_STOCK_LIMIT)
    elif stock == 'out':
        products = products.filter(stock=0)
    elif stock == 'hidden':
        products = products.filter(is_available=False)

    order_map = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'name': 'name',
        'price_asc': 'price',
        'price_desc': '-price',
        'stock_asc': 'stock',
        'stock_desc': '-stock',
    }

    products = products.order_by(order_map.get(sort, '-created_at'), 'id')

    page_obj, querystring = paginate(request, products)

    everything = Product.objects.all()

    context = {
        'panel_active': 'products',
        'page_title': 'Products',
        'page_obj': page_obj,
        'querystring': querystring,
        'categories': Category.objects.all(),
        'query': query,
        'selected_category': category,
        'stock': stock,
        'sort': sort,
        'counts': {
            'all': everything.count(),
            'low': everything.filter(stock__gt=0, stock__lte=LOW_STOCK_LIMIT).count(),
            'out': everything.filter(stock=0).count(),
            'hidden': everything.filter(is_available=False).count(),
        },
        'low_limit': LOW_STOCK_LIMIT,
    }

    return render(request, 'panel/products.html', context)


@staff_member_required
def panel_product_form(request, product_id=None):

    product = get_object_or_404(Product, id=product_id) if product_id else None

    form = ProductForm(
        request.POST or None,
        request.FILES or None,
        instance=product
    )

    if request.method == 'POST' and form.is_valid():

        with transaction.atomic():

            product = form.save()

            ids = [i for i in request.POST.getlist('delete_gallery') if i.isdigit()]
            if ids:
                product.gallery.filter(id__in=ids).delete()

            position = product.gallery.count()

            for uploaded in form.cleaned_data.get('gallery', []):
                position += 1
                ProductImage.objects.create(
                    product=product,
                    image=uploaded,
                    position=position,
                )

        messages.success(request, f'Product "{product.name}" saved.')

        if request.POST.get('save_and_add'):
            return redirect('panel_product_add')

        return redirect('panel_products')

    context = {
        'panel_active': 'products',
        'page_title': 'Edit product' if product else 'Add product',
        'form': form,
        'product': product,
        'gallery': product.gallery.all() if product else [],
    }

    return render(request, 'panel/product_form.html', context)


@staff_member_required
@require_POST
def panel_product_quick(request, product_id):
    """Quick edit of price, stock and visibility from the product list."""

    product = get_object_or_404(Product, id=product_id)

    action = request.POST.get('action', 'save')

    if action == 'toggle':
        product.is_available = not product.is_available
        product.save(update_fields=['is_available'])
        messages.success(
            request,
            f'"{product.name}" is now {"visible" if product.is_available else "hidden"} in the store.'
        )
        return back_to(request, 'panel_products')

    price = to_decimal(request.POST.get('price'))
    stock = request.POST.get('stock', '')

    if price is None or not stock.isdigit():
        messages.error(request, 'Enter a valid price and stock number.')
        return back_to(request, 'panel_products')

    product.price = price
    product.stock = int(stock)
    product.save(update_fields=['price', 'stock'])

    messages.success(request, f'"{product.name}" updated.')

    return back_to(request, 'panel_products')


@staff_member_required
@require_POST
def panel_product_delete(request, product_id):

    product = get_object_or_404(Product, id=product_id)

    # Deleting a product would also delete the order lines that contain it
    # and break past orders, so products that were ordered can only be hidden.
    if OrderItem.objects.filter(product=product).exists():
        product.is_available = False
        product.save(update_fields=['is_available'])
        messages.warning(
            request,
            f'"{product.name}" is part of past orders, so it was hidden from the store instead of deleted.'
        )
    else:
        name = product.name
        product.delete()
        messages.success(request, f'Product "{name}" deleted.')

    return redirect('panel_products')


# =========================================================
# CATEGORIES
# =========================================================

@staff_member_required
def panel_categories(request):

    categories = Category.objects.annotate(
        product_count=Count('products', distinct=True)
    ).order_by('name')

    return render(request, 'panel/categories.html', {
        'panel_active': 'categories',
        'page_title': 'Categories',
        'categories': categories,
    })


@staff_member_required
def panel_category_form(request, category_id=None):

    category = get_object_or_404(Category, id=category_id) if category_id else None

    form = CategoryForm(request.POST or None, instance=category)

    if request.method == 'POST' and form.is_valid():
        category = form.save()
        messages.success(request, f'Category "{category.name}" saved.')
        return redirect('panel_categories')

    return render(request, 'panel/category_form.html', {
        'panel_active': 'categories',
        'page_title': 'Edit category' if category else 'Add category',
        'form': form,
        'category': category,
    })


@staff_member_required
@require_POST
def panel_category_delete(request, category_id):

    category = get_object_or_404(Category, id=category_id)

    # Deleting a category would also delete every product inside it.
    if category.products.exists():
        messages.error(
            request,
            f'"{category.name}" still has {category.products.count()} product(s). '
            'Move or delete them first.'
        )
    else:
        name = category.name
        category.delete()
        messages.success(request, f'Category "{name}" deleted.')

    return redirect('panel_categories')


# =========================================================
# ORDERS
# =========================================================

def filtered_orders(request):

    orders = Order.objects.select_related('user').annotate(
        item_count=Count('items')
    )

    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    payment = request.GET.get('payment', '')
    method = request.GET.get('method', '')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')

    if query:
        condition = (
            Q(full_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
        )
        if query.lstrip('#').isdigit():
            condition |= Q(id=int(query.lstrip('#')))
        orders = orders.filter(condition)

    if status in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status)

    if payment in dict(Order.PAYMENT_STATUS_CHOICES):
        orders = orders.filter(payment_status=payment)

    if method in dict(Order.PAYMENT_METHOD_CHOICES):
        orders = orders.filter(payment_method=method)

    if date_from:
        orders = orders.filter(created_at__date__gte=date_from)

    if date_to:
        orders = orders.filter(created_at__date__lte=date_to)

    return orders.order_by('-created_at', '-id')


@staff_member_required
def panel_orders(request):

    try:
        orders = filtered_orders(request)
        page_obj, querystring = paginate(request, orders)
    except Exception:
        # bad date in the URL etc. falls back to the unfiltered list
        page_obj, querystring = paginate(
            request,
            Order.objects.select_related('user').annotate(item_count=Count('items')).order_by('-created_at')
        )

    status_counts = {
        row['status']: row['n']
        for row in Order.objects.values('status').annotate(n=Count('id'))
    }

    context = {
        'panel_active': 'orders',
        'page_title': 'Orders',
        'page_obj': page_obj,
        'querystring': querystring,
        'query': request.GET.get('q', ''),
        'status': request.GET.get('status', ''),
        'payment': request.GET.get('payment', ''),
        'method': request.GET.get('method', ''),
        'date_from': request.GET.get('from', ''),
        'date_to': request.GET.get('to', ''),
        'status_choices': Order.STATUS_CHOICES,
        'payment_choices': Order.PAYMENT_STATUS_CHOICES,
        'method_choices': Order.PAYMENT_METHOD_CHOICES,
        'status_counts': status_counts,
        'total_orders': sum(status_counts.values()),
    }

    return render(request, 'panel/orders.html', context)


@staff_member_required
def panel_orders_export(request):
    """Download the (filtered) orders as a CSV file."""

    try:
        orders = filtered_orders(request)
        list(orders[:1])
    except Exception:
        orders = Order.objects.select_related('user').annotate(item_count=Count('items'))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="orders-{timezone.localdate()}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        'Order', 'Date', 'Customer', 'Username', 'Email', 'Phone', 'Address',
        'Items', 'Subtotal', 'Discount', 'Coupon', 'Total',
        'Payment method', 'Payment status', 'Status',
    ])

    for order in orders:
        writer.writerow([
            order.id,
            timezone.localtime(order.created_at).strftime('%Y-%m-%d %H:%M'),
            order.full_name,
            order.user.username,
            order.user.email,
            order.phone,
            order.full_address.replace('\n', ' '),
            order.item_count,
            order.subtotal,
            order.discount_amount,
            order.coupon_code,
            order.total_amount,
            order.get_payment_method_display(),
            order.payment_status,
            order.status,
        ])

    return response


@staff_member_required
def panel_order_detail(request, order_id):

    order = get_object_or_404(
        Order.objects.select_related('user').prefetch_related('items__product'),
        id=order_id
    )

    steps = ['Pending', 'Processing', 'Shipped', 'Delivered']

    if order.status == 'Cancelled':
        timeline = [
            {'label': 'Order placed', 'done': True, 'current': False},
            {'label': 'Cancelled', 'done': True, 'current': True},
        ]
    else:
        index = steps.index(order.status)
        timeline = [
            {
                'label': 'Order placed' if step == 'Pending' else step,
                'done': i <= index,
                'current': i == index,
            }
            for i, step in enumerate(steps)
        ]

    return render(request, 'panel/order_detail.html', {
        'panel_active': 'orders',
        'page_title': f'Order #{order.id}',
        'order': order,
        'timeline': timeline,
        'form': OrderUpdateForm(instance=order),
        'status_choices': Order.STATUS_CHOICES,
        'payment_choices': Order.PAYMENT_STATUS_CHOICES,
        'return_requests': order.return_requests.all(),
        'customer_order_count': Order.objects.filter(user=order.user).count(),
    })


@staff_member_required
@require_POST
def panel_order_update(request, order_id):

    order = get_object_or_404(Order, id=order_id)

    old_status = order.status

    form = OrderUpdateForm(request.POST, instance=order)

    if not form.is_valid():
        messages.error(request, 'Please choose a valid status.')
        return redirect('panel_order_detail', order_id=order.id)

    new_status = form.cleaned_data['status']

    if old_status == 'Cancelled' and new_status != 'Cancelled':
        messages.error(request, 'A cancelled order cannot be reopened.')
        return redirect('panel_order_detail', order_id=order.id)

    with transaction.atomic():

        # cancelling from the panel puts the stock back, same as a customer cancel
        if new_status == 'Cancelled' and old_status != 'Cancelled':
            for item in order.items.select_related('product'):
                product = Product.objects.select_for_update().get(id=item.product_id)
                product.stock += item.quantity
                product.save(update_fields=['stock'])

        form.save()

    if old_status != new_status:
        messages.success(
            request,
            f'Order #{order.id} is now {new_status}. The customer was emailed.'
        )
    else:
        messages.success(request, f'Order #{order.id} updated.')

    return back_to(request, reverse('panel_order_detail', args=[order.id]))


# =========================================================
# CUSTOMERS
# =========================================================

@staff_member_required
def panel_customers(request):

    customers = User.objects.filter(is_staff=False).annotate(
        order_count=Count('order', distinct=True),
        total_spent=Sum('order__total_amount', filter=~Q(order__status='Cancelled')),
        last_order=Max('order__created_at'),
    )

    query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'newest')
    state = request.GET.get('state', '')

    if query:
        customers = customers.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )

    if state == 'inactive':
        customers = customers.filter(is_active=False)
    elif state == 'buyers':
        customers = customers.filter(order_count__gt=0)
    elif state == 'never':
        customers = customers.filter(order_count=0)

    order_map = {
        'newest': '-date_joined',
        'oldest': 'date_joined',
        'name': 'username',
        'orders': '-order_count',
        'spent': '-total_spent',
    }

    customers = customers.order_by(order_map.get(sort, '-date_joined'), 'id')

    page_obj, querystring = paginate(request, customers)

    return render(request, 'panel/customers.html', {
        'panel_active': 'customers',
        'page_title': 'Customers',
        'page_obj': page_obj,
        'querystring': querystring,
        'query': query,
        'sort': sort,
        'state': state,
        'total_customers': User.objects.filter(is_staff=False).count(),
    })


@staff_member_required
def panel_customer_detail(request, user_id):

    customer = get_object_or_404(User, id=user_id)

    orders = customer.order_set.annotate(item_count=Count('items')).order_by('-created_at')

    spent = orders.exclude(status='Cancelled').aggregate(t=Sum('total_amount'))['t'] or 0

    return render(request, 'panel/customer_detail.html', {
        'panel_active': 'customers',
        'page_title': customer.get_full_name() or customer.username,
        'customer': customer,
        'orders': orders,
        'order_count': orders.count(),
        'total_spent': spent,
        'addresses': customer.addresses.all(),
        'reviews': customer.reviews.select_related('product'),
        'wishlist_count': Wishlist.objects.filter(user=customer).count(),
    })


@staff_member_required
@require_POST
def panel_customer_toggle(request, user_id):

    customer = get_object_or_404(User, id=user_id)

    if customer.is_staff or customer.pk == request.user.pk:
        messages.error(request, 'Staff accounts can only be changed in Django admin.')
        return redirect('panel_customer_detail', user_id=customer.id)

    customer.is_active = not customer.is_active
    customer.save(update_fields=['is_active'])

    messages.success(
        request,
        f'{customer.username} is now {"active" if customer.is_active else "blocked"}.'
    )

    return redirect('panel_customer_detail', user_id=customer.id)


# =========================================================
# COUPONS
# =========================================================

@staff_member_required
def panel_coupons(request):

    now = timezone.now()

    coupons = list(Coupon.objects.order_by('-active', '-id'))

    for coupon in coupons:
        if not coupon.active:
            coupon.state = 'Inactive'
        elif coupon.valid_to and coupon.valid_to < now:
            coupon.state = 'Expired'
        elif coupon.valid_from and coupon.valid_from > now:
            coupon.state = 'Scheduled'
        elif coupon.usage_limit is not None and coupon.times_used >= coupon.usage_limit:
            coupon.state = 'Used up'
        else:
            coupon.state = 'Active'

    return render(request, 'panel/coupons.html', {
        'panel_active': 'coupons',
        'page_title': 'Coupons',
        'coupons': coupons,
    })


@staff_member_required
def panel_coupon_form(request, coupon_id=None):

    coupon = get_object_or_404(Coupon, id=coupon_id) if coupon_id else None

    form = CouponForm(request.POST or None, instance=coupon)

    if request.method == 'POST' and form.is_valid():
        coupon = form.save()
        messages.success(request, f'Coupon {coupon.code} saved.')
        return redirect('panel_coupons')

    return render(request, 'panel/coupon_form.html', {
        'panel_active': 'coupons',
        'page_title': 'Edit coupon' if coupon else 'Add coupon',
        'form': form,
        'coupon': coupon,
    })


@staff_member_required
@require_POST
def panel_coupon_toggle(request, coupon_id):

    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon.active = not coupon.active
    coupon.save(update_fields=['active'])

    messages.success(
        request,
        f'Coupon {coupon.code} is now {"active" if coupon.active else "inactive"}.'
    )

    return redirect('panel_coupons')


@staff_member_required
@require_POST
def panel_coupon_delete(request, coupon_id):

    coupon = get_object_or_404(Coupon, id=coupon_id)
    code = coupon.code
    coupon.delete()

    messages.success(request, f'Coupon {code} deleted.')

    return redirect('panel_coupons')


# =========================================================
# REVIEWS
# =========================================================

@staff_member_required
def panel_reviews(request):

    reviews = Review.objects.select_related('product', 'user')

    query = request.GET.get('q', '').strip()
    rating = request.GET.get('rating', '')

    if query:
        reviews = reviews.filter(
            Q(product__name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(title__icontains=query)
            | Q(comment__icontains=query)
        )

    if rating.isdigit() and 1 <= int(rating) <= 5:
        reviews = reviews.filter(rating=int(rating))

    page_obj, querystring = paginate(request, reviews.order_by('-created_at'))

    average = Review.objects.aggregate(a=Sum('rating'), n=Count('id'))

    return render(request, 'panel/reviews.html', {
        'panel_active': 'reviews',
        'page_title': 'Reviews',
        'page_obj': page_obj,
        'querystring': querystring,
        'query': query,
        'rating': rating,
        'total_reviews': average['n'],
        'average_rating': round(average['a'] / average['n'], 1) if average['n'] else None,
    })


@staff_member_required
@require_POST
def panel_review_delete(request, review_id):

    review = get_object_or_404(Review, id=review_id)
    review.delete()

    messages.success(request, 'Review deleted.')

    return back_to(request, 'panel_reviews')


# =========================================================
# RETURNS
# =========================================================

@staff_member_required
def panel_returns(request):

    returns = ReturnRequest.objects.select_related('order', 'order__user')

    status = request.GET.get('status', '')

    if status in dict(ReturnRequest.STATUS_CHOICES):
        returns = returns.filter(status=status)

    page_obj, querystring = paginate(request, returns.order_by('-created_at'))

    counts = {
        row['status']: row['n']
        for row in ReturnRequest.objects.values('status').annotate(n=Count('id'))
    }

    return render(request, 'panel/returns.html', {
        'panel_active': 'returns',
        'page_title': 'Returns',
        'page_obj': page_obj,
        'querystring': querystring,
        'status': status,
        'status_choices': ReturnRequest.STATUS_CHOICES,
        'counts': counts,
        'total': sum(counts.values()),
    })


@staff_member_required
@require_POST
def panel_return_update(request, return_id):

    item = get_object_or_404(ReturnRequest, id=return_id)

    status = request.POST.get('status', '')

    if status not in dict(ReturnRequest.STATUS_CHOICES):
        messages.error(request, 'Invalid status.')
    else:
        item.status = status
        item.save(update_fields=['status'])
        messages.success(request, f'Return for order #{item.order_id} marked {status}.')

    return back_to(request, 'panel_returns')


# =========================================================
# BACK-IN-STOCK REQUESTS
# =========================================================

@staff_member_required
def panel_alerts(request):

    waiting = (
        StockAlert.objects
        .filter(notified=False)
        .values('product_id', 'product__name', 'product__stock')
        .annotate(people=Count('id'))
        .order_by('-people')
    )

    recent = StockAlert.objects.select_related('product').order_by('-created_at')[:50]

    return render(request, 'panel/alerts.html', {
        'panel_active': 'alerts',
        'page_title': 'Stock requests',
        'waiting': waiting,
        'recent': recent,
    })


@staff_member_required
@require_POST
def panel_alert_delete(request, alert_id):

    get_object_or_404(StockAlert, id=alert_id).delete()

    messages.success(request, 'Request removed.')

    return redirect('panel_alerts')
