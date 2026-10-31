import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import razorpay
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json

from .affiliates import create_commission, get_referring_affiliate
from .emails import send_order_confirmation
from .payments import finalize_paid_order, webhook_signature_ok
from .geo import INDIAN_STATES
from .models import *


logger = logging.getLogger(__name__)

PRODUCTS_PER_PAGE = 12
LOGIN_MAX_FAILURES = 8
LOGIN_LOCK_SECONDS = 600


def get_razorpay_client():
    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
    client.enable_retry(True)
    return client


def with_ratings(queryset):
    """Annotate products with avg_rating and review_count."""
    return queryset.annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews', distinct=True),
    )


def safe_next_url(request, default='home'):
    target = request.POST.get('next') or request.GET.get('next')

    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target

    return default


# =========================================================
# HOME / PRODUCTS
# =========================================================

def home(request):
    products = with_ratings(
        Product.objects.filter(is_available=True).select_related('category')
    )

    deals = [p for p in products if p.discount_percent > 0]
    deals.sort(key=lambda p: p.discount_percent, reverse=True)

    context = {
        'products': products,
        'categories': Category.objects.prefetch_related('products'),
        'deals': deals[:6],
    }

    return render(request, 'home.html', context)


def product_detail(request, slug):
    product = get_object_or_404(
        with_ratings(Product.objects.select_related('category')),
        slug=slug,
        is_available=True
    )

    reviews = list(product.reviews.select_related('user'))

    buyer_ids = set(
        OrderItem.objects
        .filter(product=product)
        .exclude(order__status='Cancelled')
        .values_list('order__user_id', flat=True)
    )

    for review in reviews:
        review.verified = review.user_id in buyer_ids

    breakdown = {star: 0 for star in range(5, 0, -1)}
    for review in reviews:
        breakdown[review.rating] += 1

    total_reviews = len(reviews)

    breakdown_rows = [
        {
            'star': star,
            'count': count,
            'percent': int(count * 100 / total_reviews) if total_reviews else 0,
        }
        for star, count in breakdown.items()
    ]

    user_review = None
    in_wishlist = False

    if request.user.is_authenticated:
        user_review = next(
            (r for r in reviews if r.user_id == request.user.id),
            None
        )
        in_wishlist = Wishlist.objects.filter(
            user=request.user,
            product=product
        ).exists()

    related = with_ratings(
        Product.objects.filter(
            category=product.category,
            is_available=True
        ).exclude(id=product.id)
    )[:6]

    images = []
    if product.image:
        images.append(product.image.url)
    images += [g.image.url for g in product.gallery.all()]

    context = {
        'product': product,
        'images': images,
        'reviews': reviews,
        'breakdown_rows': breakdown_rows,
        'user_review': user_review,
        'in_wishlist': in_wishlist,
        'related_products': related,
        'user_email': request.user.email if request.user.is_authenticated else '',
    }

    return render(request, 'product_detail.html', context)


def products(request):
    products = with_ratings(
        Product.objects.filter(is_available=True).select_related('category')
    )
    categories = Category.objects.all()

    query = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '')

    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )

    if category_slug:
        products = products.filter(category__slug=category_slug)

    # price range of all available products (used for placeholders)
    price_bounds = Product.objects.filter(is_available=True).aggregate(
        lowest=Min('price'),
        highest=Max('price'),
    )

    def parse_price(value):
        try:
            price = Decimal(value)
        except (InvalidOperation, TypeError):
            return None
        return price if price >= 0 else None

    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()

    if parse_price(min_price) is not None:
        products = products.filter(price__gte=parse_price(min_price))

    if parse_price(max_price) is not None:
        products = products.filter(price__lte=parse_price(max_price))

    if request.GET.get('in_stock'):
        products = products.filter(stock__gt=0)

    if request.GET.get('deals'):
        products = products.filter(mrp__gt=0)

    sort = request.GET.get('sort', '')

    if sort == 'price_asc':
        products = products.order_by('price', 'id')
    elif sort == 'price_desc':
        products = products.order_by('-price', 'id')
    elif sort == 'rating':
        products = products.order_by('-avg_rating', '-review_count', 'id')
    elif sort == 'newest':
        products = products.order_by('-created_at', 'id')
    else:
        products = products.order_by('-id')

    paginator = Paginator(products, PRODUCTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))

    params = request.GET.copy()
    params.pop('page', None)

    context = {
        'products': page_obj,
        'page_obj': page_obj,
        'total_results': paginator.count,
        'querystring': params.urlencode(),
        'categories': categories,
        'query': query,
        'selected_category': category_slug,
        'min_price': min_price,
        'max_price': max_price,
        'sort': sort,
        'in_stock_only': bool(request.GET.get('in_stock')),
        'deals_only': bool(request.GET.get('deals')),
        'price_lowest': int(price_bounds['lowest'] or 0),
        'price_highest': int(price_bounds['highest'] or 0),
    }

    return render(request, 'products.html', context)


# =========================================================
# AUTHENTICATION
# =========================================================

def register(request):

    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':

        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not username or not email or not password:
            messages.error(request, 'Please fill in all fields.')
            return redirect('register')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match!')
            return redirect('register')

        if User.objects.filter(username__iexact=username).exists():
            messages.error(request, 'Username already exists!')
            return redirect('register')

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'An account with this email already exists.')
            return redirect('register')

        try:
            validate_password(
                password,
                User(username=username, email=email)
            )
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
            return redirect('register')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        login(request, user)

        messages.success(request, 'Account created successfully!')

        return redirect('home')

    return render(request, 'register.html')


def user_login(request):

    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # allow signing in with email as well as username
        if '@' in username:
            match = User.objects.filter(email__iexact=username).first()
            if match:
                username = match.username

        # slow down password guessing: 8 wrong tries per username + address, then a 10 minute pause
        ip = request.META.get('REMOTE_ADDR', '')
        throttle_key = f'login-fail:{ip}:{username.lower()}'

        if cache.get(throttle_key, 0) >= LOGIN_MAX_FAILURES:
            messages.error(
                request,
                'Too many failed attempts. Please wait 10 minutes or reset your password.'
            )
            return redirect('login')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is None:
            cache.set(throttle_key, cache.get(throttle_key, 0) + 1, LOGIN_LOCK_SECONDS)

        if user is not None:

            cache.delete(throttle_key)

            login(request, user)

            messages.success(request, 'Login successful!')

            return redirect(safe_next_url(request))

        messages.error(
            request,
            'Invalid username or password!'
        )

        target = redirect('login')
        next_url = request.POST.get('next')
        if next_url:
            target['Location'] += f'?next={next_url}'
        return target

    return render(
        request,
        'login.html',
        {'next': request.GET.get('next', '')}
    )


@require_POST
def user_logout(request):

    logout(request)

    messages.success(
        request,
        'You have been logged out.'
    )

    return redirect('home')


# =========================================================
# CART
# =========================================================

def add_to_cart(request, product_id):
    product = get_object_or_404(
        Product,
        id=product_id,
        is_available=True
    )

    cart = request.session.get('cart', {})

    product_id = str(product_id)

    quantity = 1

    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1

    if quantity < 1:
        quantity = 1

    current_quantity = cart.get(product_id, 0)
    new_quantity = current_quantity + quantity

    if new_quantity > product.stock:
        messages.warning(
            request,
            f'Only {product.stock} item(s) available in stock.'
        )
        return redirect('product_detail', slug=product.slug)

    cart[product_id] = new_quantity

    request.session['cart'] = cart
    request.session.modified = True

    messages.success(
        request,
        f'{product.name} added to cart.'
    )

    return redirect('cart')


def build_cart(request):
    """
    Read the session cart. Products that were deleted or are no longer
    available are dropped from the cart instead of crashing the page.

    Returns (items, subtotal, discount, total, coupon).
    """
    cart_data = request.session.get('cart', {})

    items = []
    subtotal = Decimal('0')
    cleaned = {}

    products = Product.objects.filter(
        id__in=[pid for pid in cart_data if str(pid).isdigit()]
    ).in_bulk()

    for product_id, quantity in cart_data.items():

        product = products.get(int(product_id)) if str(product_id).isdigit() else None

        if product is None or not product.is_available:
            continue

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            continue

        if quantity < 1:
            continue

        cleaned[str(product_id)] = quantity

        item_total = product.price * quantity

        subtotal += item_total

        items.append({
            'product': product,
            'quantity': quantity,
            'item_total': item_total,
        })

    if cleaned != cart_data:
        request.session['cart'] = cleaned
        request.session.modified = True

    coupon = None
    discount = Decimal('0')

    code = request.session.get('coupon')

    if code and items:
        coupon = Coupon.objects.filter(code__iexact=code).first()

        if coupon:
            discount, error = coupon.evaluate(subtotal)

            if error:
                messages.warning(request, error)
                request.session.pop('coupon', None)
                coupon = None
                discount = Decimal('0')
        else:
            request.session.pop('coupon', None)

    total = subtotal - Decimal(discount)

    return items, subtotal, Decimal(discount), total, coupon


def cart(request):

    items, subtotal, discount, total, coupon = build_cart(request)

    context = {
        'cart_items': items,
        'subtotal': subtotal,
        'discount': discount,
        'coupon': coupon,
        'total': total,
    }

    return render(
        request,
        'cart.html',
        context
    )


def remove_from_cart(request, product_id):
    if request.method != 'POST':
        return redirect('cart')

    cart = request.session.get('cart', {})

    product_id = str(product_id)

    if product_id in cart:
        del cart[product_id]

    request.session['cart'] = cart
    request.session.modified = True

    messages.success(request, 'Product removed from cart.')

    return redirect('cart')


def update_cart(request, product_id):

    if request.method == 'POST':

        try:
            quantity = int(request.POST.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1

        product = get_object_or_404(
            Product,
            id=product_id
        )

        cart = request.session.get('cart', {})

        product_id = str(product_id)

        if quantity <= 0:

            cart.pop(product_id, None)

        elif quantity <= product.stock:

            cart[product_id] = quantity

        else:

            cart[product_id] = product.stock

            messages.warning(
                request,
                f'Only {product.stock} item(s) available in stock.'
            )

        request.session['cart'] = cart
        request.session.modified = True

    return redirect('cart')


# =========================================================
# CHECKOUT
# =========================================================

def checkout(request):

    if not request.user.is_authenticated:
        messages.warning(
            request,
            'Please login before checkout.'
        )
        return redirect(f"{reverse('login')}?next={reverse('checkout')}")

    cart_items, subtotal, discount, total, coupon = build_cart(request)

    if not cart_items:
        messages.warning(
            request,
            'Your cart is empty.'
        )
        return redirect('cart')

    # =========================
    # CART VALIDATION
    # =========================

    for item in cart_items:

        product = item['product']

        if item['quantity'] > product.stock:
            messages.error(
                request,
                f'Only {product.stock} item(s) of {product.name} are available.'
            )
            return redirect('cart')

    saved_addresses = list(request.user.addresses.all())

    default_address = next(
        (a for a in saved_addresses if a.is_default),
        saved_addresses[0] if saved_addresses else None
    )

    page_context = {
        'cart_items': cart_items,
        'subtotal': subtotal,
        'discount': discount,
        'coupon': coupon,
        'total': total,
        'saved_addresses': saved_addresses,
        'default_address': default_address,
        'states': INDIAN_STATES,
        'form': {},
    }

    # =========================
    # POST
    # =========================

    if request.method == 'POST':

        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()
        pincode = request.POST.get('pincode', '').strip()
        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', '').strip()
        payment_method = request.POST.get('payment_method', 'COD')

        errors = []

        if not full_name or not phone or not address:
            errors.append('Please fill your name, phone and address.')

        if phone and not (
            phone.lstrip('+').isdigit() and 10 <= len(phone.lstrip('+')) <= 15
        ):
            errors.append('Enter a valid phone number.')

        if not (pincode.isdigit() and len(pincode) == 6 and pincode[0] != '0'):
            errors.append('Enter a valid 6 digit PIN code.')

        if not city:
            errors.append('Please enter your city.')

        if state not in INDIAN_STATES:
            errors.append('Please choose your state.')

        if payment_method not in ['COD', 'RAZORPAY']:
            errors.append('Invalid payment method.')

        if errors:

            for error in errors:
                messages.error(request, error)

            # show the form again with what the customer already typed
            page_context['form'] = request.POST

            return render(request, 'checkout.html', page_context)

        # remember the address for next time
        if request.POST.get('save_address'):

            exists = request.user.addresses.filter(
                line__iexact=address,
                pincode=pincode,
            ).exists()

            if not exists:
                Address.objects.create(
                    user=request.user,
                    full_name=full_name,
                    phone=phone,
                    line=address[:255],
                    city=city,
                    state=state,
                    pincode=pincode,
                    is_default=not saved_addresses,
                )

        order_fields = dict(
            user=request.user,
            full_name=full_name,
            phone=phone,
            address=address,
            city=city,
            state=state,
            pincode=pincode,
            total_amount=total,
            discount_amount=discount,
            coupon_code=coupon.code if coupon else '',
            affiliate=get_referring_affiliate(request, request.user),
            status='Pending',
            payment_status='Pending',
        )

        # ==================================================
        # CASH ON DELIVERY
        # ==================================================

        if payment_method == 'COD':

            try:

                with transaction.atomic():

                    order = Order.objects.create(
                        payment_method='COD',
                        **order_fields
                    )

                    for item in cart_items:

                        product = Product.objects.select_for_update().get(
                            id=item['product'].id
                        )

                        if (
                            not product.is_available
                            or product.stock < item['quantity']
                        ):
                            raise ValueError(
                                f'Insufficient stock for {product.name}.'
                            )

                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            quantity=item['quantity'],
                            price=product.price,
                        )

                        product.stock -= item['quantity']

                        product.save(update_fields=['stock'])

                    if coupon:
                        Coupon.objects.filter(id=coupon.id).update(
                            times_used=F('times_used') + 1
                        )

            except ValueError as error:

                messages.error(request, str(error))

                return redirect('cart')

            request.session['cart'] = {}
            request.session.pop('coupon', None)
            request.session.modified = True

            create_commission(order)
            send_order_confirmation(order)

            messages.success(
                request,
                f'Order #{order.id} placed successfully with Cash on Delivery!'
            )

            return redirect(
                'order_success',
                order_id=order.id
            )

        # ==================================================
        # RAZORPAY / UPI
        # ==================================================

        try:

            razorpay_order = get_razorpay_client().order.create({
                'amount': int(total * 100),
                'currency': 'INR',
                'payment_capture': 1,
            })

        except Exception:

            messages.error(
                request,
                'Unable to start Razorpay payment. Please try again.'
            )

            return redirect('checkout')

        with transaction.atomic():

            order = Order.objects.create(
                payment_method='RAZORPAY',
                razorpay_order_id=razorpay_order['id'],
                **order_fields
            )

            # keep the items on the order now; stock is taken when payment succeeds
            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    quantity=item['quantity'],
                    price=item['product'].price,
                )
        request.session['razorpay_order_id'] = razorpay_order['id']
        request.session['pending_order_id'] = order.id
        request.session.modified = True

        page_context.update({
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'razorpay_amount': int(total * 100),
            'pending_order_id': order.id,
        })

        return render(request, 'checkout.html', page_context)

    # =========================
    # GET
    # =========================

    return render(request, 'checkout.html', page_context)


def razorpay_verify(request):

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method.'
        })

    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'message': 'Please login first.'
        })

    client = get_razorpay_client()

    try:

        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_signature = request.POST.get('razorpay_signature')
        order_id = request.POST.get('order_id')

        if not all([
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature,
            order_id
        ]):
            return JsonResponse({
                'success': False,
                'message': 'Payment information is incomplete.'
            })

        order = get_object_or_404(
            Order,
            id=order_id,
            user=request.user
        )

        if order.razorpay_order_id != razorpay_order_id:
            return JsonResponse({
                'success': False,
                'message': 'Invalid Razorpay order.'
            })

        if order.payment_status == 'Paid':
            return JsonResponse({
                'success': True,
                'order_id': order.id,
            })

        # =========================
        # VERIFY SIGNATURE
        # =========================

        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
        })

        # =========================
        # PAYMENT VERIFIED
        # =========================

        # orders created before items were stored with the order: rebuild from the cart
        if not order.items.exists():
            for product_id, quantity in request.session.get('cart', {}).items():
                product = Product.objects.filter(id=product_id).first()
                if product:
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=int(quantity),
                        price=product.price,
                    )

        finalize_paid_order(order.id, razorpay_payment_id, razorpay_signature)

        request.session['cart'] = {}
        request.session.pop('coupon', None)
        request.session.pop('razorpay_order_id', None)
        request.session.pop('pending_order_id', None)
        request.session.modified = True

        return JsonResponse({
            'success': True,
            'order_id': order.id,
        })

    except razorpay.errors.SignatureVerificationError:

        order = Order.objects.filter(
            id=request.POST.get('order_id'),
            user=request.user
        ).exclude(payment_status='Paid').first()

        if order:
            order.payment_status = 'Failed'
            order.save(update_fields=['payment_status'])

        return JsonResponse({
            'success': False,
            'message': 'Payment verification failed.'
        })

    except Exception:

        logger.exception('Razorpay verification crashed')

        return JsonResponse({
            'success': False,
            'message': 'Something went wrong while confirming your payment. '
                       'If money was deducted, your order will be confirmed automatically.'
        })


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """Razorpay tells us about payments even if the customer closed the browser."""

    if not webhook_signature_ok(
        request.body,
        request.headers.get('X-Razorpay-Signature', '')
    ):
        return HttpResponse(status=400)

    try:
        event = json.loads(request.body)
        name = event.get('event', '')
        payload = event.get('payload', {})
        payment = (payload.get('payment') or {}).get('entity') or {}
        order_entity = (payload.get('order') or {}).get('entity') or {}
        rzp_order_id = payment.get('order_id') or order_entity.get('id')
    except (ValueError, AttributeError):
        return HttpResponse(status=400)

    order = Order.objects.filter(razorpay_order_id=rzp_order_id).first() if rzp_order_id else None

    if order is None:
        return HttpResponse(status=200)           # not one of ours, nothing to retry

    if name in ('payment.captured', 'order.paid'):

        try:
            finalize_paid_order(order.id, payment.get('id', ''))
        except Exception:
            logger.exception('Webhook could not finish order %s', order.id)
            return HttpResponse(status=500)       # Razorpay will retry later

    elif name == 'payment.failed' and order.payment_status != 'Paid':

        Order.objects.filter(pk=order.pk).update(payment_status='Failed')

    return HttpResponse(status=200)

# =========================================================
# ORDERS
# =========================================================

@login_required
def order_success(request, order_id):

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user
    )

    return render(
        request,
        'order_success.html',
        {'order': order}
    )


@login_required
def my_orders(request):

    orders = Order.objects.filter(
        user=request.user
    ).prefetch_related(
        'items__product'
    ).order_by('-created_at')

    return render(
        request,
        'my_orders.html',
        {'orders': orders}
    )


ORDER_STEPS = ['Pending', 'Processing', 'Shipped', 'Delivered']


@login_required
def order_detail(request, order_id):

    order = get_object_or_404(
        Order.objects.prefetch_related('items__product'),
        id=order_id,
        user=request.user
    )

    # Tracking timeline: Ordered > Processing > Shipped > Delivered
    labels = {
        'Pending': 'Order placed',
        'Processing': 'Processing',
        'Shipped': 'Shipped',
        'Delivered': 'Delivered',
    }

    if order.status == 'Cancelled':
        timeline = [{'label': 'Order placed', 'done': True, 'current': False}]
        timeline.append({'label': 'Cancelled', 'done': True, 'current': True})
    else:
        current_index = ORDER_STEPS.index(order.status)
        timeline = [
            {
                'label': labels[step],
                'done': index <= current_index,
                'current': index == current_index,
            }
            for index, step in enumerate(ORDER_STEPS)
        ]

    open_return = order.return_requests.filter(
        status__in=['Requested', 'Approved']
    ).exists()

    context = {
        'order': order,
        'timeline': timeline,
        'return_requests': order.return_requests.all(),
        'can_return': order.status == 'Delivered' and not open_return,
    }

    return render(request, 'order_detail.html', context)


# =========================================================
# WISHLIST
# =========================================================

@require_POST
def add_to_wishlist(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id,
        is_available=True
    )

    if not request.user.is_authenticated:
        messages.warning(
            request,
            'Please login to add products to your wishlist.'
        )
        return redirect(
            f"{reverse('login')}?next={product.get_absolute_url()}"
        )

    Wishlist.objects.get_or_create(
        user=request.user,
        product=product
    )

    messages.success(
        request,
        f'{product.name} added to your wishlist.'
    )

    return redirect(safe_next_url(request, default=product.get_absolute_url()))


@require_POST
def remove_from_wishlist(request, product_id):

    if not request.user.is_authenticated:
        return redirect('login')

    Wishlist.objects.filter(
        user=request.user,
        product_id=product_id
    ).delete()

    messages.success(
        request,
        'Product removed from wishlist.'
    )

    return redirect('wishlist')


@login_required
def wishlist(request):

    wishlist_items = Wishlist.objects.filter(
        user=request.user
    ).select_related(
        'product',
        'product__category'
    )

    return render(
        request,
        'wishlist.html',
        {
            'wishlist_items': wishlist_items,
        }
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@staff_member_required
def admin_dashboard(request):

    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    paid = Q(payment_status='Paid')

    # ---------------------------------------------
    # Totals, revenue, payment and status counts
    # (one query instead of ~20)
    # ---------------------------------------------

    stats = Order.objects.aggregate(
        total_orders=Count('id'),
        total_revenue=Sum('total_amount', filter=paid),

        today_orders=Count('id', filter=Q(created_at__date=today)),
        today_revenue=Sum(
            'total_amount',
            filter=paid & Q(created_at__date=today)
        ),

        week_orders=Count('id', filter=Q(created_at__date__gte=week_start)),
        week_revenue=Sum(
            'total_amount',
            filter=paid & Q(created_at__date__gte=week_start)
        ),

        month_orders=Count('id', filter=Q(created_at__date__gte=month_start)),
        month_revenue=Sum(
            'total_amount',
            filter=paid & Q(created_at__date__gte=month_start)
        ),

        pending_orders=Count('id', filter=Q(status='Pending')),
        processing_orders=Count('id', filter=Q(status='Processing')),
        shipped_orders=Count('id', filter=Q(status='Shipped')),
        delivered_orders=Count('id', filter=Q(status='Delivered')),
        cancelled_orders=Count('id', filter=Q(status='Cancelled')),

        paid_orders=Count('id', filter=paid),
        pending_payments=Count('id', filter=Q(payment_status='Pending')),
        failed_payments=Count('id', filter=Q(payment_status='Failed')),
    )

    for key in ('total_revenue', 'today_revenue', 'week_revenue', 'month_revenue'):
        stats[key] = stats[key] or 0


    # ---------------------------------------------
    # Last 7 days analytics
    # ---------------------------------------------

    first_day = today - timedelta(days=6)

    daily = {
        row['day']: row
        for row in (
            Order.objects
            .filter(created_at__date__gte=first_day, created_at__date__lte=today)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(
                orders=Count('id'),
                revenue=Sum('total_amount', filter=paid)
            )
        )
    }

    sales_labels = []
    sales_revenue = []
    sales_orders = []

    for i in range(7):
        day = first_day + timedelta(days=i)
        row = daily.get(day)
        sales_labels.append(day.strftime('%d %b'))
        sales_revenue.append(float(row['revenue'] or 0) if row else 0)
        sales_orders.append(row['orders'] if row else 0)


    # ---------------------------------------------
    # Lists
    # ---------------------------------------------

    low_stock_products = (
        Product.objects
        .filter(stock__lte=5)
        .select_related('category')
        .order_by('stock')[:8]
    )

    recent_orders = Order.objects.order_by('-created_at')[:8]

    top_products = (
        OrderItem.objects
        .values('product__name')
        .annotate(total_sold=Sum('quantity'))
        .order_by('-total_sold')[:5]
    )


    context = {
        'panel_active': 'dashboard',
        'page_title': 'Dashboard',
        'total_products': Product.objects.count(),
        'total_categories': Category.objects.count(),
        'total_customers': User.objects.filter(is_staff=False).count(),
        'total_wishlist': Wishlist.objects.count(),

        **stats,

        'sales_labels': json.dumps(sales_labels),
        'sales_revenue': json.dumps(sales_revenue),
        'sales_orders': json.dumps(sales_orders),

        'status_labels': json.dumps(
            ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']
        ),
        'status_data': json.dumps([
            stats['pending_orders'],
            stats['processing_orders'],
            stats['shipped_orders'],
            stats['delivered_orders'],
            stats['cancelled_orders'],
        ]),

        'payment_labels': json.dumps(['Paid', 'Pending', 'Failed']),
        'payment_data': json.dumps([
            stats['paid_orders'],
            stats['pending_payments'],
            stats['failed_payments'],
        ]),

        'low_stock_products': low_stock_products,
        'recent_orders': recent_orders,
        'top_products': top_products,
    }

    return render(request, 'admin/dashboard.html', context)
