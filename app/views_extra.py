"""
Extra storefront views: reviews, coupons, order actions, account pages,
static pages, search suggestions and error handlers.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import (
    Address,
    Category,
    Coupon,
    Order,
    Product,
    Review,
    ReturnRequest,
    StockAlert,
    Wishlist,
)
from .geo import INDIAN_STATES
from .views import build_cart


# =========================================================
# REVIEWS
# =========================================================

@login_required
@require_POST
def submit_review(request, product_id):

    product = get_object_or_404(Product, id=product_id, is_available=True)

    try:
        rating = int(request.POST.get('rating', 0))
    except (TypeError, ValueError):
        rating = 0

    if rating < 1 or rating > 5:
        messages.error(request, 'Please choose a rating from 1 to 5 stars.')
        return redirect(f"{product.get_absolute_url()}#reviews")

    Review.objects.update_or_create(
        product=product,
        user=request.user,
        defaults={
            'rating': rating,
            'title': request.POST.get('title', '').strip()[:120],
            'comment': request.POST.get('comment', '').strip()[:2000],
        }
    )

    messages.success(request, 'Thanks! Your review has been saved.')

    return redirect(f"{product.get_absolute_url()}#reviews")


@login_required
@require_POST
def delete_review(request, product_id):

    deleted, _ = Review.objects.filter(
        product_id=product_id,
        user=request.user
    ).delete()

    if deleted:
        messages.success(request, 'Your review was deleted.')

    product = get_object_or_404(Product, id=product_id)

    return redirect(f"{product.get_absolute_url()}#reviews")


# =========================================================
# COUPONS
# =========================================================

@require_POST
def apply_coupon(request):

    code = request.POST.get('code', '').strip().upper()

    coupon = Coupon.objects.filter(code__iexact=code).first()

    if not code:
        messages.error(request, 'Please enter a coupon code.')
        return redirect(request.POST.get('next') or 'cart')

    if coupon is None:
        messages.error(request, 'Invalid coupon code.')
        return redirect(request.POST.get('next') or 'cart')

    _, subtotal, _, _, _ = build_cart(request)

    discount, error = coupon.evaluate(subtotal)

    if error:
        messages.error(request, error)
    else:
        request.session['coupon'] = coupon.code
        messages.success(
            request,
            f'Coupon {coupon.code} applied. You saved Rs. {discount}.'
        )

    return redirect('cart')


@require_POST
def remove_coupon(request):

    request.session.pop('coupon', None)

    messages.success(request, 'Coupon removed.')

    return redirect('cart')


# =========================================================
# ORDER ACTIONS
# =========================================================

@login_required
@require_POST
def cancel_order(request, order_id):

    order = get_object_or_404(Order, id=order_id, user=request.user)

    if not order.can_cancel:
        messages.error(
            request,
            'This order can no longer be cancelled.'
        )
        return redirect('order_detail', order_id=order.id)

    with transaction.atomic():

        # put the stock back
        for item in order.items.select_related('product'):
            product = Product.objects.select_for_update().get(id=item.product_id)
            product.stock += item.quantity
            product.save(update_fields=['stock'])

        order.status = 'Cancelled'
        order.save(update_fields=['status'])

    if order.payment_status == 'Paid':
        messages.success(
            request,
            'Order cancelled. Your payment will be refunded to the original '
            'payment method within 5 to 7 working days.'
        )
    else:
        messages.success(request, 'Your order has been cancelled.')

    return redirect('order_detail', order_id=order.id)


@login_required
@require_POST
def request_return(request, order_id):

    order = get_object_or_404(Order, id=order_id, user=request.user)

    reason = request.POST.get('reason', '').strip()

    if order.status != 'Delivered':
        messages.error(request, 'Only delivered orders can be returned.')
    elif not reason:
        messages.error(request, 'Please tell us why you want to return this order.')
    elif order.return_requests.filter(status__in=['Requested', 'Approved']).exists():
        messages.info(request, 'A return request is already open for this order.')
    else:
        ReturnRequest.objects.create(order=order, reason=reason[:1000])
        messages.success(
            request,
            'Return request submitted. We will contact you shortly.'
        )

    return redirect('order_detail', order_id=order.id)


@login_required
def invoice(request, order_id):

    order = get_object_or_404(
        Order.objects.prefetch_related('items__product'),
        id=order_id,
        user=request.user
    )

    return render(request, 'invoice.html', {'order': order})


# =========================================================
# WISHLIST -> CART
# =========================================================

@login_required
@require_POST
def wishlist_move_to_cart(request, product_id):

    product = get_object_or_404(Product, id=product_id, is_available=True)

    if product.stock < 1:
        messages.error(request, f'{product.name} is out of stock.')
        return redirect('wishlist')

    cart = request.session.get('cart', {})
    key = str(product.id)

    if cart.get(key, 0) + 1 > product.stock:
        messages.warning(
            request,
            f'Only {product.stock} item(s) available in stock.'
        )
        return redirect('wishlist')

    cart[key] = cart.get(key, 0) + 1
    request.session['cart'] = cart
    request.session.modified = True

    Wishlist.objects.filter(user=request.user, product=product).delete()

    messages.success(request, f'{product.name} moved to your cart.')

    return redirect('wishlist')


# =========================================================
# ACCOUNT: PROFILE + ADDRESSES
# =========================================================

@login_required
def profile(request):

    user = request.user
    password_form = PasswordChangeForm(user)

    if request.method == 'POST':

        action = request.POST.get('action')

        if action == 'details':

            email = request.POST.get('email', '').strip().lower()

            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, 'Please enter a valid email address.')
                return redirect('profile')

            if user.__class__.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                messages.error(request, 'That email is already used by another account.')
                return redirect('profile')

            user.first_name = request.POST.get('first_name', '').strip()[:150]
            user.last_name = request.POST.get('last_name', '').strip()[:150]
            user.email = email
            user.save()

            messages.success(request, 'Your details were updated.')

            return redirect('profile')

        if action == 'password':

            password_form = PasswordChangeForm(user, request.POST)

            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password was changed.')
                return redirect('profile')

            messages.error(request, 'Could not change password. Please check the form.')

    context = {
        'password_form': password_form,
        'order_count': Order.objects.filter(user=user).count(),
        'wishlist_count': Wishlist.objects.filter(user=user).count(),
        'address_count': Address.objects.filter(user=user).count(),
    }

    return render(request, 'profile.html', context)


def _address_data(request):
    data = {
        'full_name': request.POST.get('full_name', '').strip(),
        'phone': request.POST.get('phone', '').strip(),
        'line': request.POST.get('line', '').strip(),
        'city': request.POST.get('city', '').strip(),
        'state': request.POST.get('state', '').strip(),
        'pincode': request.POST.get('pincode', '').strip(),
    }

    errors = []

    if not all(data.values()):
        errors.append('Please fill in every address field.')

    if data['pincode'] and not (data['pincode'].isdigit() and len(data['pincode']) == 6):
        errors.append('Pincode must be 6 digits.')

    if data['state'] and data['state'] not in INDIAN_STATES:
        errors.append('Please choose a state from the list.')

    if data['phone'] and not (data['phone'].lstrip('+').isdigit() and 10 <= len(data['phone']) <= 15):
        errors.append('Enter a valid phone number.')

    return data, errors


@login_required
def address_list(request):

    return render(
        request,
        'addresses.html',
        {'addresses': request.user.addresses.all()}
    )


@login_required
def address_form(request, address_id=None):

    address = None

    if address_id:
        address = get_object_or_404(Address, id=address_id, user=request.user)

    if request.method == 'POST':

        data, errors = _address_data(request)

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(
                request,
                'address_form.html',
                {'address': address, 'form': data, 'states': INDIAN_STATES}
            )

        make_default = bool(request.POST.get('is_default')) \
            or not request.user.addresses.exists()

        with transaction.atomic():

            if address is None:
                address = Address(user=request.user)

            for field, value in data.items():
                setattr(address, field, value)

            if make_default:
                request.user.addresses.update(is_default=False)

            address.is_default = make_default or address.is_default
            address.save()

        messages.success(request, 'Address saved.')

        return redirect('address_list')

    return render(
        request,
        'address_form.html',
        {'address': address, 'form': None, 'states': INDIAN_STATES}
    )


@login_required
@require_POST
def address_delete(request, address_id):

    address = get_object_or_404(Address, id=address_id, user=request.user)
    was_default = address.is_default
    address.delete()

    if was_default:
        first = request.user.addresses.first()
        if first:
            first.is_default = True
            first.save(update_fields=['is_default'])

    messages.success(request, 'Address deleted.')

    return redirect('address_list')


@login_required
@require_POST
def address_make_default(request, address_id):

    address = get_object_or_404(Address, id=address_id, user=request.user)

    request.user.addresses.update(is_default=False)
    address.is_default = True
    address.save(update_fields=['is_default'])

    messages.success(request, 'Default address updated.')

    return redirect('address_list')


# =========================================================
# SEARCH SUGGESTIONS + BACK-IN-STOCK
# =========================================================

@require_GET
def search_suggest(request):

    query = request.GET.get('q', '').strip()

    if len(query) < 2:
        return JsonResponse({'results': []})

    products = (
        Product.objects
        .filter(is_available=True)
        .filter(Q(name__icontains=query) | Q(category__name__icontains=query))
        .select_related('category')[:6]
    )

    results = [
        {
            'name': p.name,
            'url': p.get_absolute_url(),
            'price': str(int(p.price)),
            'category': p.category.name,
            'image': p.image.url if p.image else '',
        }
        for p in products
    ]

    return JsonResponse({'results': results})


@require_POST
def notify_me(request, product_id):

    product = get_object_or_404(Product, id=product_id, is_available=True)

    email = request.POST.get('email', '').strip().lower()

    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Please enter a valid email address.')
        return redirect(product.get_absolute_url())

    if product.stock > 0:
        messages.info(request, 'Good news, this product is already in stock.')
        return redirect(product.get_absolute_url())

    StockAlert.objects.get_or_create(product=product, email=email)

    messages.success(
        request,
        "Done! We'll email you when this product is back in stock."
    )

    return redirect(product.get_absolute_url())


# =========================================================
# STATIC PAGES
# =========================================================

STATIC_PAGES = {
    'about': {
        'title': f'About {settings.SITE_NAME}',
        'description': f'{settings.SITE_NAME} is an online store with carefully selected products at fair prices.',
    },
    'privacy': {
        'title': 'Privacy Policy',
        'description': f'How {settings.SITE_NAME} collects, uses and protects your personal information.',
    },
    'terms': {
        'title': 'Terms & Conditions',
        'description': f'The terms that apply when you shop at {settings.SITE_NAME}.',
    },
    'returns': {
        'title': 'Returns & Refunds',
        'description': 'Our return, cancellation and refund policy.',
    },
}


def static_page(request, slug):
    page = STATIC_PAGES[slug]

    return render(
        request,
        'pages/static_page.html',
        {
            'slug': slug,
            'page_title': page['title'],
            'meta_description': page['description'],
            'content_template': f'pages/{slug}.html',
        }
    )


def about(request):

    categories = Category.objects.order_by('id')

    showcase_all = []

    for category in categories:
        product = (
            category.products
            .filter(is_available=True)
            .exclude(image='')
            .order_by('id')
            .first()
        )
        showcase_all.append({
            'name': category.name,
            'slug': category.slug,
            'image': product.image.url if product else '',
        })

    # the hero collage shows four categories that have a picture
    showcase = [c for c in showcase_all if c['image']][:4]

    return render(request, 'pages/about_page.html', {
        'product_count': Product.objects.filter(is_available=True).count(),
        'category_count': categories.count(),
        'showcase': showcase,
        'showcase_all': showcase_all,
    })

def privacy(request):
    return static_page(request, 'privacy')


def terms(request):
    return static_page(request, 'terms')


def returns_policy(request):
    return static_page(request, 'returns')


def contact(request):

    if request.method == 'POST':

        if request.POST.get('website'):  # honeypot field, humans leave it empty
            return redirect('contact')

        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        message = request.POST.get('message', '').strip()

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Please enter a valid email address.')
            return render(request, 'pages/contact.html', {'form': request.POST})

        if not name or not message:
            messages.error(request, 'Please fill in your name and message.')
            return render(request, 'pages/contact.html', {'form': request.POST})

        send_mail(
            subject=f'[{settings.SITE_NAME} contact] Message from {name}',
            message=f'From: {name} <{email}>\n\n{message}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.DEFAULT_FROM_EMAIL],
            fail_silently=True,
        )

        messages.success(
            request,
            "Thanks for reaching out! We'll reply to you soon."
        )

        return redirect('contact')

    return render(request, 'pages/contact.html', {'form': None})


# =========================================================
# SEO + ERRORS
# =========================================================

def robots_txt(request):

    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /cart/',
        'Disallow: /checkout/',
        'Disallow: /my-orders/',
        'Disallow: /account/',
        'Disallow: /panel/',
        'Disallow: /affiliate/dashboard/',
        'Disallow: /razorpay/',
        f"Sitemap: {settings.SITE_URL.rstrip('/')}/sitemap.xml",
    ]

    return HttpResponse('\n'.join(lines), content_type='text/plain')


def error_404(request, exception=None):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)


def error_403(request, exception=None):
    return render(request, '403.html', status=403)
