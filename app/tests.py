from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Address,
    Category,
    Coupon,
    Order,
    OrderItem,
    Product,
    ReturnRequest,
    Review,
    StockAlert,
)


def make_product(name='Test Shirt', price='500', stock=10, mrp=None, category=None):
    category = category or Category.objects.get_or_create(
        slug='tests', defaults={'name': 'Tests'}
    )[0]

    return Product.objects.create(
        category=category,
        name=name,
        slug=name.lower().replace(' ', '-'),
        description='A test product',
        price=Decimal(price),
        mrp=Decimal(mrp) if mrp else None,
        image='products/test.jpg',
        stock=stock,
    )


class BaseCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            'shopper', 'shopper@example.com', 'Str0ng-pass-123'
        )
        self.product = make_product()

    def login(self):
        self.client.login(username='shopper', password='Str0ng-pass-123')

    def add_to_cart(self, product=None, quantity=1):
        product = product or self.product
        session = self.client.session
        session['cart'] = {str(product.id): quantity}
        session.save()


class ModelTests(BaseCase):

    def test_discount_percent(self):
        product = make_product('Sale Item', price='750', mrp='1000')
        self.assertEqual(product.discount_percent, 25)
        self.assertEqual(product.savings, Decimal('250'))
        self.assertEqual(self.product.discount_percent, 0)

    def test_coupon_rules(self):
        coupon = Coupon.objects.create(
            code=' save10 ', discount_percent=10,
            max_discount=Decimal('40'), min_order_amount=Decimal('300')
        )
        self.assertEqual(coupon.code, 'SAVE10')

        self.assertIn('Add items', coupon.evaluate(Decimal('100'))[1])
        self.assertEqual(coupon.evaluate(Decimal('300'))[0], Decimal('30.00'))
        self.assertEqual(coupon.evaluate(Decimal('2000'))[0], Decimal('40'))  # capped

        coupon.valid_to = timezone.now() - timedelta(days=1)
        self.assertIn('expired', coupon.evaluate(Decimal('500'))[1])

        coupon.valid_to = None
        coupon.usage_limit = 1
        coupon.times_used = 1
        self.assertIn('usage limit', coupon.evaluate(Decimal('500'))[1])

        coupon.usage_limit = None
        coupon.active = False
        self.assertIn('not active', coupon.evaluate(Decimal('500'))[1])


class CartAndCheckoutTests(BaseCase):

    def checkout_data(self, **extra):
        data = {
            'full_name': 'Test Shopper',
            'phone': '9876543210',
            'address': '12 Test Street, Karol Bagh',
            'pincode': '110005',
            'city': 'New Delhi',
            'state': 'Delhi',
            'payment_method': 'COD',
        }
        data.update(extra)
        return data

    def test_cart_drops_deleted_products(self):
        session = self.client.session
        session['cart'] = {'99999': 2, str(self.product.id): 1}
        session.save()

        response = self.client.get(reverse('cart'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['cart'], {str(self.product.id): 1})

    def test_coupon_applies_and_discounts_total(self):
        Coupon.objects.create(code='TEN', discount_percent=10)
        self.add_to_cart(quantity=2)  # subtotal 1000

        self.client.post(reverse('apply_coupon'), {'code': 'ten'})

        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['subtotal'], Decimal('1000'))
        self.assertEqual(response.context['discount'], Decimal('100.00'))
        self.assertEqual(response.context['total'], Decimal('900.00'))

    def test_invalid_coupon_is_rejected(self):
        self.add_to_cart()
        self.client.post(reverse('apply_coupon'), {'code': 'NOPE'})
        self.assertNotIn('coupon', self.client.session)

    def test_cod_checkout_creates_order_reduces_stock_and_emails(self):
        Coupon.objects.create(code='TEN', discount_percent=10)
        self.login()
        self.add_to_cart(quantity=2)
        self.client.post(reverse('apply_coupon'), {'code': 'TEN'})

        response = self.client.post(reverse('checkout'), self.checkout_data())

        order = Order.objects.get()
        self.assertRedirects(
            response, reverse('order_success', args=[order.id])
        )
        self.assertEqual(order.total_amount, Decimal('900.00'))
        self.assertEqual(order.discount_amount, Decimal('100.00'))
        self.assertEqual(order.coupon_code, 'TEN')
        self.assertEqual(order.items.get().quantity, 2)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)

        self.assertEqual(Coupon.objects.get(code='TEN').times_used, 1)
        self.assertEqual(self.client.session['cart'], {})

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f'Order #{order.id}', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ['shopper@example.com'])

    def test_checkout_stores_structured_address(self):
        self.login()
        self.add_to_cart()

        self.client.post(reverse('checkout'), self.checkout_data())

        order = Order.objects.get()
        self.assertEqual(
            (order.city, order.state, order.pincode),
            ('New Delhi', 'Delhi', '110005')
        )
        self.assertEqual(
            order.full_address,
            '12 Test Street, Karol Bagh, New Delhi, Delhi - 110005'
        )

        page = self.client.get(reverse('order_detail', args=[order.id]))
        self.assertContains(page, '110005')
        self.assertIn('110005', mail.outbox[0].body)

    def test_checkout_rejects_bad_pincode_state_and_phone(self):
        self.login()

        for bad in [
            {'pincode': '12345'},        # too short
            {'pincode': '011005'},       # cannot start with 0
            {'pincode': 'abcdef'},
            {'state': 'Atlantis'},
            {'state': ''},
            {'city': ''},
            {'phone': 'xyz'},
        ]:
            self.add_to_cart()
            response = self.client.post(reverse('checkout'), self.checkout_data(**bad))

            # the form is shown again (not a crash, not an order)
            self.assertEqual(response.status_code, 200, bad)
            self.assertEqual(Order.objects.count(), 0, bad)
            self.assertContains(response, 'name="pincode"')

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_invalid_checkout_keeps_what_was_typed(self):
        self.login()
        self.add_to_cart()

        response = self.client.post(
            reverse('checkout'),
            self.checkout_data(pincode='123', city='Mumbai')
        )

        self.assertContains(response, 'value="Mumbai"')
        self.assertContains(response, 'value="123"')

    def test_save_address_checkbox_saves_once_and_first_is_default(self):
        self.login()

        for _ in range(2):
            self.add_to_cart()
            self.client.post(
                reverse('checkout'),
                self.checkout_data(save_address='1')
            )

        address = Address.objects.get()          # same address is not duplicated
        self.assertEqual(address.pincode, '110005')
        self.assertEqual(address.city, 'New Delhi')
        self.assertTrue(address.is_default)

        # not saved when the box is not ticked
        self.add_to_cart()
        self.client.post(
            reverse('checkout'),
            self.checkout_data(address='Another place', pincode='400001', city='Mumbai', state='Maharashtra')
        )
        self.assertEqual(Address.objects.count(), 1)

    def test_checkout_page_shows_state_dropdown_and_saved_address(self):
        self.login()
        Address.objects.create(
            user=self.user, full_name='Test Shopper', phone='9876543210',
            line='1 Old Road', city='Pune', state='Maharashtra', pincode='411001',
            is_default=True,
        )
        self.add_to_cart()

        response = self.client.get(reverse('checkout'))

        self.assertContains(response, '<option value="Maharashtra"')
        self.assertContains(response, 'data-pincode="411001"')
    def test_checkout_requires_login(self):
        self.add_to_cart()
        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_checkout_blocks_quantity_above_stock(self):
        self.login()
        self.add_to_cart(quantity=50)

        response = self.client.post(reverse('checkout'), self.checkout_data())

        self.assertRedirects(response, reverse('cart'))
        self.assertEqual(Order.objects.count(), 0)

    def test_update_cart_ignores_garbage_quantity(self):
        self.add_to_cart()
        response = self.client.post(
            reverse('update_cart', args=[self.product.id]),
            {'quantity': 'abc'}
        )
        self.assertEqual(response.status_code, 302)


class OrderActionTests(BaseCase):

    def make_order(self, status='Pending', quantity=2, payment_status='Pending'):
        order = Order.objects.create(
            user=self.user, full_name='Test', phone='9876543210',
            address='Somewhere', total_amount=Decimal('1000'),
            status=status, payment_status=payment_status,
        )
        OrderItem.objects.create(
            order=order, product=self.product,
            quantity=quantity, price=self.product.price,
        )
        self.product.stock -= quantity
        self.product.save()
        return order

    def test_cancel_restores_stock_and_sends_status_email(self):
        self.login()
        order = self.make_order()

        self.client.post(reverse('cancel_order', args=[order.id]))

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, 'Cancelled')
        self.assertEqual(self.product.stock, 10)
        self.assertTrue(
            any('cancelled' in m.subject.lower() for m in mail.outbox)
        )

    def test_shipped_order_cannot_be_cancelled(self):
        self.login()
        order = self.make_order(status='Shipped')

        self.client.post(reverse('cancel_order', args=[order.id]))

        order.refresh_from_db()
        self.assertEqual(order.status, 'Shipped')

    def test_cancel_requires_post(self):
        self.login()
        order = self.make_order()
        response = self.client.get(reverse('cancel_order', args=[order.id]))
        self.assertEqual(response.status_code, 405)

    def test_cannot_touch_someone_elses_order(self):
        other = User.objects.create_user('other', 'o@example.com', 'Str0ng-pass-123')
        order = self.make_order()
        order.user = other
        order.save()

        self.login()

        self.assertEqual(
            self.client.get(reverse('order_detail', args=[order.id])).status_code,
            404
        )
        self.assertEqual(
            self.client.get(reverse('invoice', args=[order.id])).status_code,
            404
        )
        self.client.post(reverse('cancel_order', args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'Pending')

    def test_return_request_only_for_delivered_orders(self):
        self.login()
        pending = self.make_order(status='Pending', quantity=1)
        delivered = self.make_order(status='Delivered', quantity=1)

        self.client.post(reverse('request_return', args=[pending.id]), {'reason': 'x'})
        self.assertEqual(ReturnRequest.objects.count(), 0)

        self.client.post(
            reverse('request_return', args=[delivered.id]),
            {'reason': 'Wrong size'}
        )
        self.assertEqual(ReturnRequest.objects.count(), 1)

        # a second open request is not created
        self.client.post(
            reverse('request_return', args=[delivered.id]),
            {'reason': 'Again'}
        )
        self.assertEqual(ReturnRequest.objects.count(), 1)

    def test_status_change_in_admin_emails_customer(self):
        order = self.make_order()
        mail.outbox.clear()

        order.status = 'Shipped'
        order.save()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('shipped', mail.outbox[0].subject.lower())

    def test_order_pages_render(self):
        self.login()
        order = self.make_order(status='Shipped')

        for name, args in [
            ('my_orders', []),
            ('order_detail', [order.id]),
            ('order_success', [order.id]),
            ('invoice', [order.id]),
        ]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200, name)


class ReviewAndAccountTests(BaseCase):

    def test_review_create_update_delete(self):
        self.login()
        url = reverse('submit_review', args=[self.product.id])

        self.client.post(url, {'rating': 5, 'title': 'Great', 'comment': 'Loved it'})
        self.assertEqual(Review.objects.get().rating, 5)

        self.client.post(url, {'rating': 3, 'title': 'Ok', 'comment': ''})
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().rating, 3)

        self.client.post(reverse('delete_review', args=[self.product.id]))
        self.assertEqual(Review.objects.count(), 0)

    def test_review_rating_must_be_valid(self):
        self.login()
        self.client.post(
            reverse('submit_review', args=[self.product.id]),
            {'rating': 9}
        )
        self.assertEqual(Review.objects.count(), 0)

    def test_review_requires_login(self):
        response = self.client.post(
            reverse('submit_review', args=[self.product.id]),
            {'rating': 5}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Review.objects.count(), 0)

    def test_product_page_shows_rating(self):
        Review.objects.create(
            product=self.product, user=self.user, rating=4, comment='Nice fit'
        )
        response = self.client.get(self.product.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nice fit')

    def test_logout_is_post_only(self):
        self.login()
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_with_email_and_safe_next(self):
        response = self.client.post(reverse('login'), {
            'username': 'shopper@example.com',
            'password': 'Str0ng-pass-123',
            'next': '/cart/',
        })
        self.assertRedirects(response, '/cart/', fetch_redirect_response=False)

        self.client.post(reverse('logout'))

        response = self.client.post(reverse('login'), {
            'username': 'shopper',
            'password': 'Str0ng-pass-123',
            'next': 'https://evil.example.com/',
        })
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_register_rejects_duplicate_email_and_weak_password(self):
        data = {
            'username': 'newuser', 'email': 'shopper@example.com',
            'password': 'Str0ng-pass-123', 'confirm_password': 'Str0ng-pass-123',
        }
        self.client.post(reverse('register'), data)
        self.assertFalse(User.objects.filter(username='newuser').exists())

        data.update(email='new@example.com', password='12345678', confirm_password='12345678')
        self.client.post(reverse('register'), data)
        self.assertFalse(User.objects.filter(username='newuser').exists())

        data.update(password='Str0ng-pass-123', confirm_password='Str0ng-pass-123')
        self.client.post(reverse('register'), data)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_password_reset_sends_email(self):
        response = self.client.post(
            reverse('password_reset'), {'email': 'shopper@example.com'}
        )
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/password-reset/', mail.outbox[0].body)

    def test_profile_update_and_password_change(self):
        self.login()

        self.client.post(reverse('profile'), {
            'action': 'details', 'first_name': 'Van', 'last_name': 'Shu',
            'email': 'van@example.com',
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Van')
        self.assertEqual(self.user.email, 'van@example.com')

        self.client.post(reverse('profile'), {
            'action': 'password',
            'old_password': 'Str0ng-pass-123',
            'new_password1': 'An0ther-pass-456',
            'new_password2': 'An0ther-pass-456',
        })
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('An0ther-pass-456'))
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)


class AddressTests(BaseCase):

    def data(self, **extra):
        data = {
            'full_name': 'Test Shopper', 'phone': '9876543210',
            'line': '12 Test Street', 'city': 'Delhi',
            'state': 'Delhi', 'pincode': '110001',
        }
        data.update(extra)
        return data

    def test_first_address_becomes_default_and_default_moves(self):
        self.login()

        self.client.post(reverse('address_add'), self.data())
        first = Address.objects.get()
        self.assertTrue(first.is_default)

        self.client.post(reverse('address_add'), self.data(city='Mumbai', is_default='on'))
        first.refresh_from_db()
        second = Address.objects.get(city='Mumbai')
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

        # deleting the default promotes another address
        self.client.post(reverse('address_delete', args=[second.id]))
        first.refresh_from_db()
        self.assertTrue(first.is_default)

    def test_address_validation(self):
        self.login()
        self.client.post(reverse('address_add'), self.data(pincode='12'))
        self.client.post(reverse('address_add'), self.data(phone='abc'))
        self.client.post(reverse('address_add'), self.data(city=''))
        self.assertEqual(Address.objects.count(), 0)

    def test_cannot_edit_someone_elses_address(self):
        other = User.objects.create_user('other', 'o@example.com', 'Str0ng-pass-123')
        address = Address.objects.create(user=other, **self.data())

        self.login()

        response = self.client.get(reverse('address_edit', args=[address.id]))
        self.assertEqual(response.status_code, 404)


class CatalogTests(BaseCase):

    def test_pagination_and_filters(self):
        for i in range(15):
            make_product(f'Item {i}', price=str(100 + i), stock=5)

        response = self.client.get(reverse('products'))
        self.assertEqual(len(response.context['products']), 12)
        self.assertEqual(response.context['total_results'], 16)

        response = self.client.get(reverse('products'), {'page': 2})
        self.assertEqual(len(response.context['products']), 4)

        response = self.client.get(reverse('products'), {
            'min_price': 105, 'max_price': 110, 'sort': 'price_desc'
        })
        prices = [int(p.price) for p in response.context['products']]
        self.assertEqual(prices, [110, 109, 108, 107, 106, 105])

        # junk page number does not crash
        self.assertEqual(
            self.client.get(reverse('products'), {'page': 'zzz'}).status_code, 200
        )

    def test_in_stock_and_deals_filters(self):
        make_product('Sold Out Thing', stock=0)
        make_product('Cheap Deal', price='400', mrp='800')

        response = self.client.get(reverse('products'), {'in_stock': 1})
        names = {p.name for p in response.context['products']}
        self.assertNotIn('Sold Out Thing', names)

        response = self.client.get(reverse('products'), {'deals': 1})
        self.assertEqual({p.name for p in response.context['products']}, {'Cheap Deal'})

    def test_search_suggestions(self):
        self.assertEqual(self.client.get(reverse('search_suggest'), {'q': 'T'}).json(), {'results': []})
        data = self.client.get(reverse('search_suggest'), {'q': 'shirt'}).json()
        self.assertEqual(data['results'][0]['name'], 'Test Shirt')

    def test_wishlist_move_to_cart(self):
        from .models import Wishlist
        self.login()
        Wishlist.objects.create(user=self.user, product=self.product)

        self.client.post(reverse('wishlist_move_to_cart', args=[self.product.id]))

        self.assertEqual(self.client.session['cart'], {str(self.product.id): 1})
        self.assertFalse(Wishlist.objects.exists())

    def test_back_in_stock_alert(self):
        sold_out = make_product('Rare Item', stock=0)

        self.client.post(
            reverse('notify_me', args=[sold_out.id]),
            {'email': 'wait@example.com'}
        )
        self.assertEqual(StockAlert.objects.count(), 1)

        sold_out.stock = 5
        sold_out.save()

        self.assertTrue(StockAlert.objects.get().notified)
        self.assertEqual(mail.outbox[-1].to, ['wait@example.com'])


class SiteTests(BaseCase):

    def test_static_pages_seo_and_errors(self):
        for name in ['about', 'contact', 'privacy', 'terms', 'returns']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

        sitemap = self.client.get(reverse('sitemap'))
        self.assertEqual(sitemap.status_code, 200)
        self.assertContains(sitemap, self.product.get_absolute_url())

        robots = self.client.get(reverse('robots'))
        self.assertContains(robots, 'Sitemap:')

        self.assertEqual(self.client.get('/no-such-page/').status_code, 404)

    def test_contact_form_sends_mail_and_honeypot_blocks_bots(self):
        self.client.post(reverse('contact'), {
            'name': 'Ann', 'email': 'ann@example.com', 'message': 'Hello there'
        })
        self.assertEqual(len(mail.outbox), 1)

        self.client.post(reverse('contact'), {
            'name': 'Bot', 'email': 'bot@example.com',
            'message': 'spam', 'website': 'http://spam.example'
        })
        self.assertEqual(len(mail.outbox), 1)

    def test_admin_dashboard_is_staff_only(self):
        self.login()
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 302)

        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 200)

class PanelTests(BaseCase):

    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            'boss', 'boss@example.com', 'Str0ng-pass-123', is_staff=True
        )

    def staff_login(self):
        self.client.login(username='boss', password='Str0ng-pass-123')

    def make_order(self, status='Pending', quantity=2):
        order = Order.objects.create(
            user=self.user, full_name='Test', phone='9876543210',
            address='Somewhere', total_amount=Decimal('1000'), status=status,
        )
        OrderItem.objects.create(
            order=order, product=self.product,
            quantity=quantity, price=self.product.price,
        )
        self.product.stock -= quantity
        self.product.save()
        return order

    def test_panel_is_staff_only(self):
        urls = [
            reverse('panel_products'), reverse('panel_orders'),
            reverse('panel_customers'), reverse('panel_coupons'),
            reverse('panel_reviews'), reverse('panel_returns'),
            reverse('panel_categories'), reverse('panel_alerts'),
            reverse('panel_orders_export'),
        ]

        for url in urls:                       # anonymous
            self.assertEqual(self.client.get(url).status_code, 302, url)

        self.login()                           # normal customer
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)

        self.client.logout()
        self.staff_login()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_all_panel_pages_render_for_staff(self):
        order = self.make_order()
        Review.objects.create(product=self.product, user=self.user, rating=5)
        self.staff_login()

        for name, args in [
            ('admin_dashboard', []),
            ('panel_product_add', []),
            ('panel_product_edit', [self.product.id]),
            ('panel_category_add', []),
            ('panel_coupon_add', []),
            ('panel_order_detail', [order.id]),
            ('panel_customer_detail', [self.user.id]),
        ]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200, name)

    def test_product_create_edit_with_auto_slug_and_validation(self):
        self.staff_login()
        category = self.product.category

        data = {
            'name': 'Brand New Hoodie', 'slug': '', 'category': category.id,
            'description': 'Warm', 'price': '999', 'mrp': '1499',
            'stock': '7', 'is_available': 'on',
        }

        from django.core.files.uploadedfile import SimpleUploadedFile
        from io import BytesIO
        from PIL import Image
        import tempfile
        from django.test import override_settings

        buffer = BytesIO()
        Image.new('RGB', (4, 4), 'red').save(buffer, 'PNG')

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            data['image'] = SimpleUploadedFile('a.png', buffer.getvalue(), 'image/png')
            self.client.post(reverse('panel_product_add'), data)

        product = Product.objects.get(name='Brand New Hoodie')
        self.assertEqual(product.slug, 'brand-new-hoodie')
        self.assertEqual(product.discount_percent, 33)

        # MRP lower than price is rejected
        response = self.client.post(
            reverse('panel_product_edit', args=[product.id]),
            {**{k: v for k, v in data.items() if k != 'image'}, 'mrp': '500'}
        )
        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.mrp, Decimal('1499'))

        # quick edit and visibility toggle
        self.client.post(
            reverse('panel_product_quick', args=[product.id]),
            {'price': '850', 'stock': '3'}
        )
        product.refresh_from_db()
        self.assertEqual((product.price, product.stock), (Decimal('850'), 3))

        self.client.post(
            reverse('panel_product_quick', args=[product.id]), {'action': 'toggle'}
        )
        product.refresh_from_db()
        self.assertFalse(product.is_available)

        # junk quick-edit values are refused
        self.client.post(
            reverse('panel_product_quick', args=[product.id]),
            {'price': 'abc', 'stock': '-4'}
        )
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)

    def test_ordered_product_is_hidden_not_deleted(self):
        self.make_order()
        self.staff_login()

        self.client.post(reverse('panel_product_delete', args=[self.product.id]))

        self.product.refresh_from_db()
        self.assertFalse(self.product.is_available)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_unordered_product_is_deleted(self):
        spare = make_product('Spare Cap')
        self.staff_login()
        self.client.post(reverse('panel_product_delete', args=[spare.id]))
        self.assertFalse(Product.objects.filter(id=spare.id).exists())

    def test_category_with_products_cannot_be_deleted(self):
        self.staff_login()
        category = self.product.category

        self.client.post(reverse('panel_category_delete', args=[category.id]))
        self.assertTrue(Category.objects.filter(id=category.id).exists())
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())

        empty = Category.objects.create(name='Empty', slug='empty')
        self.client.post(reverse('panel_category_delete', args=[empty.id]))
        self.assertFalse(Category.objects.filter(id=empty.id).exists())

    def test_category_auto_slug(self):
        self.staff_login()
        self.client.post(reverse('panel_category_add'), {'name': 'Summer Wear', 'slug': ''})
        self.assertTrue(Category.objects.filter(slug='summer-wear').exists())

    def test_order_status_update_emails_and_cancel_restocks(self):
        order = self.make_order(quantity=3)
        self.staff_login()
        mail.outbox.clear()

        self.client.post(
            reverse('panel_order_update', args=[order.id]),
            {'status': 'Shipped', 'payment_status': 'Paid'}
        )
        order.refresh_from_db()
        self.assertEqual((order.status, order.payment_status), ('Shipped', 'Paid'))
        self.assertEqual(len(mail.outbox), 1)

        self.client.post(
            reverse('panel_order_update', args=[order.id]),
            {'status': 'Cancelled', 'payment_status': 'Paid'}
        )
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, 'Cancelled')
        self.assertEqual(self.product.stock, 10)          # 10 - 3 + 3

        # a cancelled order cannot be reopened (and stock must not drift)
        self.client.post(
            reverse('panel_order_update', args=[order.id]),
            {'status': 'Processing', 'payment_status': 'Paid'}
        )
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, 'Cancelled')
        self.assertEqual(self.product.stock, 10)

    def test_order_filters_and_csv_export(self):
        self.make_order(status='Pending')
        delivered = self.make_order(status='Delivered', quantity=1)
        self.staff_login()

        response = self.client.get(reverse('panel_orders'), {'status': 'Delivered'})
        ids = [o.id for o in response.context['page_obj']]
        self.assertEqual(ids, [delivered.id])

        response = self.client.get(reverse('panel_orders'), {'q': f'#{delivered.id}'})
        self.assertEqual([o.id for o in response.context['page_obj']], [delivered.id])

        # a junk date does not crash the page
        self.assertEqual(
            self.client.get(reverse('panel_orders'), {'from': 'abc'}).status_code, 200
        )

        response = self.client.get(reverse('panel_orders_export'))
        self.assertEqual(response['Content-Type'], 'text/csv')
        lines = response.content.decode().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith('Order,Date,Customer'))

    def test_coupon_crud_and_validation(self):
        self.staff_login()

        self.client.post(reverse('panel_coupon_add'), {
            'code': 'tmp 10', 'discount_percent': '150', 'min_order_amount': '0',
        })
        self.assertEqual(Coupon.objects.count(), 0)         # 150% rejected

        self.client.post(reverse('panel_coupon_add'), {
            'code': 'tmp 10', 'discount_percent': '10', 'min_order_amount': '0',
            'active': 'on',
        })
        coupon = Coupon.objects.get()
        self.assertEqual(coupon.code, 'TMP10')

        self.client.post(reverse('panel_coupon_toggle', args=[coupon.id]))
        coupon.refresh_from_db()
        self.assertFalse(coupon.active)

        self.client.post(reverse('panel_coupon_delete', args=[coupon.id]))
        self.assertEqual(Coupon.objects.count(), 0)

    def test_review_delete_and_return_update(self):
        review = Review.objects.create(product=self.product, user=self.user, rating=2)
        order = self.make_order(status='Delivered', quantity=1)
        request = ReturnRequest.objects.create(order=order, reason='Torn')
        self.staff_login()

        self.client.post(reverse('panel_return_update', args=[request.id]), {'status': 'Approved'})
        request.refresh_from_db()
        self.assertEqual(request.status, 'Approved')

        self.client.post(reverse('panel_return_update', args=[request.id]), {'status': 'Nonsense'})
        request.refresh_from_db()
        self.assertEqual(request.status, 'Approved')

        self.client.post(reverse('panel_review_delete', args=[review.id]))
        self.assertEqual(Review.objects.count(), 0)

    def test_customer_block_toggle_protects_staff(self):
        self.staff_login()

        self.client.post(reverse('panel_customer_toggle', args=[self.user.id]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        self.client.post(reverse('panel_customer_toggle', args=[self.staff.id]))
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_panel_actions_require_post(self):
        self.staff_login()
        for name in ['panel_product_delete', 'panel_category_delete']:
            self.assertEqual(
                self.client.get(reverse(name, args=[self.product.id])).status_code, 405
            )

class AffiliateTests(BaseCase):

    def setUp(self):
        super().setUp()
        from .models import Affiliate
        self.promoter = User.objects.create_user(
            'promoter', 'promoter@example.com', 'Str0ng-pass-123'
        )
        self.affiliate = Affiliate.objects.create(
            user=self.promoter, code='PROMO1', status='Approved',
            commission_percent=Decimal('10'),
        )

    def checkout_data(self):
        return {
            'full_name': 'Test Shopper', 'phone': '9876543210',
            'address': '12 Test Street', 'pincode': '110005',
            'city': 'New Delhi', 'state': 'Delhi', 'payment_method': 'COD',
        }

    def buy_via_link(self, quantity=2, code='PROMO1'):
        """Visit a referral link, then check out as the normal shopper."""
        self.client.get('/', {'ref': code})
        self.login()
        self.add_to_cart(quantity=quantity)
        self.client.post(reverse('checkout'), self.checkout_data())
        return Order.objects.order_by('-id').first()

    # ---------- tracking ----------

    def test_referral_link_sets_cookie_and_counts_one_click_per_session(self):
        from .models import AffiliateClick

        response = self.client.get('/', {'ref': 'promo1'})
        self.assertEqual(response.cookies['vsh_ref'].value, 'PROMO1')

        self.client.get('/product/', {'ref': 'PROMO1'})          # same visitor again
        self.assertEqual(AffiliateClick.objects.count(), 1)

    def test_unknown_or_unapproved_codes_are_ignored(self):
        from .models import AffiliateClick

        self.affiliate.status = 'Pending'
        self.affiliate.save()

        for code in ['PROMO1', 'NOPE', 'x' * 40]:
            response = self.client.get('/', {'ref': code})
            self.assertNotIn('vsh_ref', response.cookies)

        self.assertEqual(AffiliateClick.objects.count(), 0)

    def test_affiliate_clicking_own_link_is_ignored(self):
        from .models import AffiliateClick

        self.client.login(username='promoter', password='Str0ng-pass-123')
        response = self.client.get('/', {'ref': 'PROMO1'})

        self.assertNotIn('vsh_ref', response.cookies)
        self.assertEqual(AffiliateClick.objects.count(), 0)

    # ---------- commissions ----------

    def test_order_from_link_creates_pending_commission_on_discounted_total(self):
        Coupon.objects.create(code='TEN', discount_percent=10)

        self.client.get('/', {'ref': 'PROMO1'})
        self.login()
        self.add_to_cart(quantity=2)                     # 1000
        self.client.post(reverse('apply_coupon'), {'code': 'TEN'})   # total 900
        self.client.post(reverse('checkout'), self.checkout_data())

        order = Order.objects.get()
        self.assertEqual(order.affiliate, self.affiliate)

        commission = order.commission
        self.assertEqual(commission.status, 'Pending')
        self.assertEqual(commission.order_amount, Decimal('900.00'))
        self.assertEqual(commission.rate, Decimal('10.00'))
        self.assertEqual(commission.amount, Decimal('90.00'))

    def test_no_link_no_commission_and_no_self_referral(self):
        from .models import Commission

        self.login()
        self.add_to_cart()
        self.client.post(reverse('checkout'), self.checkout_data())
        self.assertEqual(Commission.objects.count(), 0)

        # the affiliate buying through their own code earns nothing
        self.client.logout()
        self.client.cookies['vsh_ref'] = 'PROMO1'
        self.client.login(username='promoter', password='Str0ng-pass-123')
        self.add_to_cart()
        self.client.post(reverse('checkout'), self.checkout_data())
        self.assertEqual(Commission.objects.count(), 0)

    def test_delivered_approves_and_cancelled_cancels(self):
        order = self.buy_via_link()
        self.assertEqual(order.commission.status, 'Pending')

        order.status = 'Delivered'
        order.save()
        order.commission.refresh_from_db()
        self.assertEqual(order.commission.status, 'Approved')
        self.assertIsNotNone(order.commission.approved_at)

        second = self.buy_via_link(quantity=1)
        second.status = 'Cancelled'
        second.save()
        second.commission.refresh_from_db()
        self.assertEqual(second.commission.status, 'Cancelled')

    def test_refund_cancels_unpaid_commission_and_flags_paid_one(self):
        order = self.buy_via_link()
        order.status = 'Delivered'
        order.save()

        refund = ReturnRequest.objects.create(order=order, reason='Torn', status='Refunded')
        order.commission.refresh_from_db()
        self.assertEqual(order.commission.status, 'Cancelled')

        # a commission that was already paid out is kept but flagged
        other = self.buy_via_link(quantity=1)
        other.status = 'Delivered'
        other.save()
        other.commission.status = 'Paid'
        other.commission.save()
        ReturnRequest.objects.create(order=other, reason='Wrong', status='Refunded')
        other.commission.refresh_from_db()
        self.assertEqual(other.commission.status, 'Paid')
        self.assertIn('refunded', other.commission.note.lower())

    # ---------- payouts ----------

    def delivered_commission(self, quantity=2):
        order = self.buy_via_link(quantity=quantity)
        order.status = 'Delivered'
        order.save()
        return order.commission

    def set_payout_details(self):
        self.affiliate.payout_method = 'UPI'
        self.affiliate.upi_id = 'promoter@upi'
        self.affiliate.save()

    def test_payout_flow_request_pay_and_reject(self):
        from . import affiliates
        from .models import Payout

        # make every order large enough to pass the minimum payout
        self.product.price = Decimal('6000')
        self.product.save()

        self.delivered_commission(quantity=1)                    # 600
        self.set_payout_details()

        payout, error = affiliates.request_payout(self.affiliate)
        self.assertEqual(error, '')
        self.assertEqual(payout.amount, Decimal('600.00'))
        self.assertEqual(self.affiliate.available_balance, 0)

        # asking again finds nothing new to pay
        again, error = affiliates.request_payout(self.affiliate)
        self.assertIsNone(again)
        self.assertEqual(Payout.objects.count(), 1)

        # rejecting returns the money to the balance
        affiliates.reject_payout(payout, 'Wrong UPI')
        self.assertEqual(self.affiliate.available_balance, Decimal('600.00'))

        payout, _ = affiliates.request_payout(self.affiliate)
        mail.outbox.clear()
        self.assertTrue(affiliates.mark_payout_paid(payout, 'UTR12345'))
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'Paid')
        self.assertEqual(self.affiliate.paid_amount, Decimal('600.00'))
        self.assertFalse(affiliates.mark_payout_paid(payout, 'again'))

    def test_payout_rules(self):
        from . import affiliates

        self.delivered_commission(quantity=1)         # 50, far below the minimum

        payout, error = affiliates.request_payout(self.affiliate)
        self.assertIsNone(payout)
        self.assertIn('details', error.lower())

        self.set_payout_details()
        payout, error = affiliates.request_payout(self.affiliate)
        self.assertIsNone(payout)
        self.assertIn('at least', error.lower())

    def test_cancelling_an_order_inside_a_payout_request_shrinks_it(self):
        from . import affiliates

        self.product.price = Decimal('6000')
        self.product.stock = 50
        self.product.save()
        self.set_payout_details()

        first = self.delivered_commission(quantity=1)             # 600
        second = self.delivered_commission(quantity=1)            # 600
        payout, _ = affiliates.request_payout(self.affiliate)
        self.assertEqual(payout.amount, Decimal('1200.00'))

        second.order.status = 'Cancelled'
        second.order.save()
        payout.refresh_from_db()
        self.assertEqual(payout.amount, Decimal('600.00'))

        first.order.status = 'Cancelled'
        first.order.save()
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'Rejected')

    # ---------- joining + forms ----------

    def test_join_flow_pending_and_auto_approve(self):
        from django.test import override_settings
        from .models import Affiliate

        self.login()

        self.client.post(reverse('affiliate_join'), {'agree': 'on', 'promo_description': 'Instagram'})
        mine = Affiliate.objects.get(user=self.user)
        self.assertEqual(mine.status, 'Pending')
        self.assertEqual(mine.commission_percent, Decimal('5'))
        self.assertTrue(mine.code)

        newbie = User.objects.create_user('newbie', 'newbie@example.com', 'Str0ng-pass-123')
        self.client.logout()
        self.client.login(username='newbie', password='Str0ng-pass-123')

        # terms must be accepted
        self.client.post(reverse('affiliate_join'), {})
        self.assertFalse(Affiliate.objects.filter(user=newbie).exists())

        with override_settings(AFFILIATE_AUTO_APPROVE=True):
            self.client.post(reverse('affiliate_join'), {'agree': 'on'})

        self.assertEqual(Affiliate.objects.get(user=newbie).status, 'Approved')

    def test_payout_details_validation(self):
        self.client.login(username='promoter', password='Str0ng-pass-123')
        url = reverse('affiliate_settings')

        self.client.post(url, {'payout_method': 'UPI', 'upi_id': 'not-a-upi'})
        self.affiliate.refresh_from_db()
        self.assertEqual(self.affiliate.upi_id, '')

        self.client.post(url, {'payout_method': 'BANK', 'account_holder': 'A', 'account_number': '12', 'ifsc': 'bad'})
        self.affiliate.refresh_from_db()
        self.assertEqual(self.affiliate.account_number, '')

        self.client.post(url, {'payout_method': 'UPI', 'upi_id': 'promoter@okaxis'})
        self.client.post(url, {
            'payout_method': 'BANK', 'account_holder': 'Promo Ter', 'bank_name': 'HDFC',
            'account_number': '1234 5678 9012', 'ifsc': 'hdfc0001234',
        })
        self.affiliate.refresh_from_db()
        self.assertEqual(self.affiliate.account_number, '123456789012')
        self.assertEqual(self.affiliate.ifsc, 'HDFC0001234')
        self.assertEqual(self.affiliate.upi_id, '')          # switching method clears the old one

    def test_affiliate_pages_render_and_hide_customer_details(self):
        order = self.buy_via_link()
        self.client.logout()
        self.client.login(username='promoter', password='Str0ng-pass-123')

        self.assertEqual(self.client.get(reverse('affiliate_landing')).status_code, 200)
        page = self.client.get(reverse('affiliate_dashboard'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'PROMO1')
        self.assertContains(page, f'#{order.id}')
        self.assertNotContains(page, 'Test Shopper')          # buyer name stays private
        self.assertNotContains(page, '9876543210')

    def test_dashboard_needs_login_and_a_profile(self):
        self.assertEqual(self.client.get(reverse('affiliate_dashboard')).status_code, 302)
        self.login()                                          # logged in but not an affiliate
        response = self.client.get(reverse('affiliate_dashboard'))
        self.assertRedirects(response, reverse('affiliate_landing'))

    # ---------- admin panel ----------

    def test_panel_affiliate_management(self):
        from .models import Affiliate, Payout

        staff = User.objects.create_user('boss', 'boss@example.com', 'Str0ng-pass-123', is_staff=True)

        # staff only
        self.assertEqual(self.client.get(reverse('panel_affiliates')).status_code, 302)
        self.login()
        self.assertEqual(self.client.get(reverse('panel_payouts')).status_code, 302)
        self.client.logout()

        self.client.login(username='boss', password='Str0ng-pass-123')

        for name in ['panel_affiliates', 'panel_commissions', 'panel_payouts']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

        self.assertEqual(
            self.client.get(reverse('panel_affiliate_detail', args=[self.affiliate.id])).status_code, 200
        )

        # approve a pending application: emails them
        pending = Affiliate.objects.create(user=self.user, code='NEWONE', status='Pending')
        mail.outbox.clear()
        self.client.post(reverse('panel_affiliate_quick', args=[pending.id]), {'action': 'approve'})
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'Approved')
        self.assertEqual(len(mail.outbox), 1)

        # change the rate (validated), suspend stops tracking
        self.client.post(
            reverse('panel_affiliate_update', args=[self.affiliate.id]),
            {'status': 'Approved', 'commission_percent': '7.5'}
        )
        self.affiliate.refresh_from_db()
        self.assertEqual(self.affiliate.commission_percent, Decimal('7.50'))

        self.client.post(
            reverse('panel_affiliate_update', args=[self.affiliate.id]),
            {'status': 'Approved', 'commission_percent': '150'}
        )
        self.affiliate.refresh_from_db()
        self.assertEqual(self.affiliate.commission_percent, Decimal('7.50'))

        self.client.post(reverse('panel_affiliate_quick', args=[self.affiliate.id]), {'action': 'suspend'})
        self.client.logout()
        response = self.client.get('/', {'ref': 'PROMO1'})
        self.assertNotIn('vsh_ref', response.cookies)

    def test_panel_marks_payout_paid_only_with_a_reference(self):
        from .models import Commission, Payout

        order = Order.objects.create(
            user=self.user, full_name='T', phone='9876543210', address='x',
            total_amount=Decimal('1000'), status='Delivered', affiliate=self.affiliate,
        )
        commission = Commission.objects.create(
            affiliate=self.affiliate, order=order, order_amount=Decimal('1000'),
            rate=Decimal('10'), amount=Decimal('100'), status='Approved',
        )
        payout = Payout.objects.create(affiliate=self.affiliate, amount=Decimal('100'))
        commission.payout = payout
        commission.save()

        User.objects.create_user('boss', 'boss@example.com', 'Str0ng-pass-123', is_staff=True)
        self.client.login(username='boss', password='Str0ng-pass-123')

        self.client.post(reverse('panel_payout_paid', args=[payout.id]), {'reference': ''})
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'Requested')

        mail.outbox.clear()
        self.client.post(reverse('panel_payout_paid', args=[payout.id]), {'reference': 'UTR999'})
        payout.refresh_from_db()
        commission.refresh_from_db()
        self.assertEqual((payout.status, payout.reference, commission.status), ('Paid', 'UTR999', 'Paid'))
        self.assertEqual(len(mail.outbox), 1)

class GoLiveTests(BaseCase):

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def checkout_data(self, **extra):
        data = {
            'full_name': 'Test Shopper', 'phone': '9876543210',
            'address': '12 Test Street', 'pincode': '110005',
            'city': 'New Delhi', 'state': 'Delhi', 'payment_method': 'RAZORPAY',
        }
        data.update(extra)
        return data

    def start_online_payment(self, quantity=2):
        """Go through checkout up to the Razorpay screen (Razorpay API mocked)."""
        from unittest import mock

        self.login()
        self.add_to_cart(quantity=quantity)

        fake_client = mock.Mock()
        fake_client.order.create.return_value = {'id': 'order_TEST123'}

        with mock.patch('app.views.get_razorpay_client', return_value=fake_client):
            response = self.client.post(reverse('checkout'), self.checkout_data())

        self.assertEqual(response.status_code, 200)
        return Order.objects.get()

    # ---------- online payment ----------

    def test_pending_online_order_keeps_items_but_not_stock(self):
        order = self.start_online_payment(quantity=3)

        self.assertEqual(order.payment_status, 'Pending')
        self.assertEqual(order.items.get().quantity, 3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)               # not taken yet

    def test_browser_callback_and_webhook_finish_the_order_only_once(self):
        from unittest import mock
        from .payments import finalize_paid_order

        order = self.start_online_payment(quantity=3)
        mail.outbox.clear()

        fake_client = mock.Mock()                              # signature check passes
        with mock.patch('app.views.get_razorpay_client', return_value=fake_client):
            response = self.client.post(reverse('razorpay_verify'), {
                'razorpay_order_id': 'order_TEST123',
                'razorpay_payment_id': 'pay_1',
                'razorpay_signature': 'sig',
                'order_id': order.id,
            })

        self.assertTrue(response.json()['success'])
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((order.payment_status, order.status), ('Paid', 'Processing'))
        self.assertEqual(self.product.stock, 7)
        self.assertEqual(self.client.session['cart'], {})
        self.assertEqual(len(mail.outbox), 1)                  # one confirmation, not two

        # the webhook arriving afterwards changes nothing
        self.assertFalse(finalize_paid_order(order.id, 'pay_1'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)
        self.assertEqual(len(mail.outbox), 1)

    def test_signature_failure_marks_payment_failed_and_keeps_stock(self):
        import razorpay
        from unittest import mock

        order = self.start_online_payment()

        fake_client = mock.Mock()
        fake_client.utility.verify_payment_signature.side_effect = (
            razorpay.errors.SignatureVerificationError('bad')
        )

        with mock.patch('app.views.get_razorpay_client', return_value=fake_client):
            response = self.client.post(reverse('razorpay_verify'), {
                'razorpay_order_id': 'order_TEST123', 'razorpay_payment_id': 'pay_1',
                'razorpay_signature': 'forged', 'order_id': order.id,
            })

        self.assertFalse(response.json()['success'])
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.payment_status, 'Failed')
        self.assertEqual(self.product.stock, 10)

    def webhook(self, payload, secret='whsec', sign=True, signature=None):
        import hashlib, hmac, json
        from django.test import override_settings

        body = json.dumps(payload)
        digest = signature or hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

        with override_settings(RAZORPAY_WEBHOOK_SECRET='whsec'):
            return self.client.post(
                reverse('razorpay_webhook'), data=body, content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE=digest if sign else '',
            )

    def test_webhook_completes_order_when_the_browser_never_came_back(self):
        order = self.start_online_payment(quantity=2)
        self.client.logout()                                   # the customer closed the browser
        mail.outbox.clear()

        response = self.webhook({
            'event': 'payment.captured',
            'payload': {'payment': {'entity': {'id': 'pay_9', 'order_id': 'order_TEST123'}}},
        })

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((order.payment_status, order.razorpay_payment_id), ('Paid', 'pay_9'))
        self.assertEqual(self.product.stock, 8)
        self.assertEqual(len(mail.outbox), 1)

    def test_webhook_rejects_bad_signatures_and_unknown_orders(self):
        order = self.start_online_payment()
        self.client.logout()

        payload = {
            'event': 'payment.captured',
            'payload': {'payment': {'entity': {'id': 'pay_9', 'order_id': 'order_TEST123'}}},
        }

        self.assertEqual(self.webhook(payload, signature='wrong').status_code, 400)
        self.assertEqual(self.webhook(payload, sign=False).status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'Pending')

        unknown = {'event': 'payment.captured',
                   'payload': {'payment': {'entity': {'id': 'p', 'order_id': 'order_NOPE'}}}}
        self.assertEqual(self.webhook(unknown).status_code, 200)

        # with no secret configured the endpoint refuses everything
        from django.test import override_settings
        with override_settings(RAZORPAY_WEBHOOK_SECRET=''):
            response = self.client.post(
                reverse('razorpay_webhook'), data='{}', content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE='x',
            )
        self.assertEqual(response.status_code, 400)

    def test_webhook_payment_failed_does_not_touch_paid_orders(self):
        order = self.start_online_payment()
        self.client.logout()

        failed = {'event': 'payment.failed',
                  'payload': {'payment': {'entity': {'id': 'p', 'order_id': 'order_TEST123'}}}}

        self.webhook(failed)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'Failed')

        from .payments import finalize_paid_order
        finalize_paid_order(order.id, 'pay_late')                 # paid after an earlier failed try
        self.webhook(failed)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'Paid')

    def test_paid_but_stock_short_is_flagged_not_lost(self):
        from .payments import finalize_paid_order

        order = self.start_online_payment(quantity=5)
        Product.objects.filter(id=self.product.id).update(stock=2)    # sold elsewhere meanwhile

        finalize_paid_order(order.id, 'pay_x')

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.payment_status, 'Paid')
        self.assertEqual(order.status, 'Pending')                    # needs a human
        self.assertIn('PAID BUT STOCK SHORT', order.admin_note)
        self.assertEqual(self.product.stock, 0)                      # never negative

    def test_online_payment_commission_and_coupon_count_after_payment(self):
        from .models import Affiliate, Commission
        from .payments import finalize_paid_order

        promoter = User.objects.create_user('promo', 'p@example.com', 'Str0ng-pass-123')
        Affiliate.objects.create(user=promoter, code='PROMO9', status='Approved', commission_percent=10)
        Coupon.objects.create(code='TEN', discount_percent=10)

        self.client.get('/', {'ref': 'PROMO9'})
        self.login()
        self.add_to_cart(quantity=2)
        self.client.post(reverse('apply_coupon'), {'code': 'TEN'})

        from unittest import mock
        fake = mock.Mock()
        fake.order.create.return_value = {'id': 'order_TEST123'}
        with mock.patch('app.views.get_razorpay_client', return_value=fake):
            self.client.post(reverse('checkout'), self.checkout_data())

        order = Order.objects.get()
        self.assertEqual(Commission.objects.count(), 0)               # nothing before payment
        self.assertEqual(Coupon.objects.get().times_used, 0)

        finalize_paid_order(order.id, 'pay_1')

        self.assertEqual(Commission.objects.get().amount, Decimal('90.00'))
        self.assertEqual(Coupon.objects.get().times_used, 1)

    def test_stale_unpaid_orders_are_cancelled_quietly(self):
        from django.core.management import call_command

        order = self.start_online_payment()
        paid = Order.objects.create(
            user=self.user, full_name='P', phone='9876543210', address='x',
            total_amount=Decimal('10'), payment_method='RAZORPAY', payment_status='Paid',
        )
        Order.objects.filter(id__in=[order.id, paid.id]).update(
            created_at=timezone.now() - timedelta(hours=30)
        )
        mail.outbox.clear()

        call_command('cancel_stale_orders', stdout=__import__('io').StringIO())

        order.refresh_from_db()
        paid.refresh_from_db()
        self.assertEqual(order.status, 'Cancelled')
        self.assertEqual(paid.status, 'Pending')                      # paid orders are never touched
        self.assertEqual(len(mail.outbox), 0)

    # ---------- login protection, media, small UX ----------

    def test_login_is_locked_after_repeated_failures(self):
        for _ in range(8):
            self.client.post(reverse('login'), {'username': 'shopper', 'password': 'wrong'})

        # even the right password is refused during the lock
        self.client.post(reverse('login'), {'username': 'shopper', 'password': 'Str0ng-pass-123'})
        self.assertNotIn('_auth_user_id', self.client.session)

        # another account / address is not affected
        other = User.objects.create_user('other', 'o@example.com', 'Str0ng-pass-123')
        self.client.post(reverse('login'), {'username': 'other', 'password': 'Str0ng-pass-123'})
        self.assertIn('_auth_user_id', self.client.session)

    def test_success_clears_failure_count(self):
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'shopper', 'password': 'wrong'})
        self.client.post(reverse('login'), {'username': 'shopper', 'password': 'Str0ng-pass-123'})
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post(reverse('logout'))

        for _ in range(7):
            self.client.post(reverse('login'), {'username': 'shopper', 'password': 'wrong'})
        self.client.post(reverse('login'), {'username': 'shopper', 'password': 'Str0ng-pass-123'})
        self.assertIn('_auth_user_id', self.client.session)         # 7 < 8, still allowed

    def test_robots_hides_private_areas(self):
        text = self.client.get(reverse('robots')).content.decode()
        for path in ('/panel/', '/affiliate/dashboard/', '/razorpay/', '/admin/'):
            self.assertIn(f'Disallow: {path}', text)

    def test_delivered_order_links_to_review_form(self):
        order = Order.objects.create(
            user=self.user, full_name='T', phone='9876543210', address='x',
            total_amount=Decimal('500'), status='Delivered',
        )
        OrderItem.objects.create(order=order, product=self.product, quantity=1, price=self.product.price)
        pending = Order.objects.create(
            user=self.user, full_name='T', phone='9876543210', address='x',
            total_amount=Decimal('500'), status='Pending',
        )
        OrderItem.objects.create(order=pending, product=self.product, quantity=1, price=self.product.price)

        self.login()

        self.assertContains(self.client.get(reverse('order_detail', args=[order.id])), 'Write a review')
        self.assertNotContains(self.client.get(reverse('order_detail', args=[pending.id])), 'Write a review')

    def test_address_form_uses_state_list_and_rejects_others(self):
        self.login()
        response = self.client.get(reverse('address_add'))
        self.assertContains(response, '<option value="Kerala"')

        self.client.post(reverse('address_add'), {
            'full_name': 'A', 'phone': '9876543210', 'line': 'Road 1',
            'city': 'Kochi', 'state': 'Atlantis', 'pincode': '682001',
        })
        self.assertEqual(Address.objects.count(), 0)

    def test_panel_shows_stock_short_note(self):
        from .payments import finalize_paid_order

        order = self.start_online_payment(quantity=5)
        Product.objects.filter(id=self.product.id).update(stock=1)
        finalize_paid_order(order.id, 'pay_x')

        User.objects.create_user('boss', 'boss@example.com', 'Str0ng-pass-123', is_staff=True)
        self.client.logout()
        self.client.login(username='boss', password='Str0ng-pass-123')

        page = self.client.get(reverse('panel_order_detail', args=[order.id]))
        self.assertContains(page, 'PAID BUT STOCK SHORT')