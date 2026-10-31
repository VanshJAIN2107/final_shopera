from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products'
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='products/')
    stock = models.PositiveIntegerField(default=0)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    mrp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Original price (MRP). Leave empty if there is no discount.'
    )

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('product_detail', args=[self.slug])

    @property
    def discount_percent(self):
        if self.mrp and self.mrp > self.price:
            return int(round((self.mrp - self.price) / self.mrp * 100))
        return 0

    @property
    def savings(self):
        if self.mrp and self.mrp > self.price:
            return self.mrp - self.price
        return 0


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='gallery'
    )
    image = models.ImageField(upload_to='products/gallery/')
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.product.name} image {self.pk}'


class Order(models.Model):

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('COD', 'Cash on Delivery'),
        ('RAZORPAY', 'UPI / Razorpay'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Failed', 'Failed'),
    ]

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE
    )

    full_name = models.CharField(max_length=200)

    phone = models.CharField(max_length=15)

    address = models.TextField()

    city = models.CharField(max_length=100, blank=True, default='')

    state = models.CharField(max_length=100, blank=True, default='')

    pincode = models.CharField(max_length=10, blank=True, default='')

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='COD'
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='Pending'
    )

    razorpay_order_id = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    razorpay_signature = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Pending'
    )

    coupon_code = models.CharField(max_length=30, blank=True)

    admin_note = models.CharField(max_length=255, blank=True)

    affiliate = models.ForeignKey(
        'Affiliate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='orders'
    )

    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Order #{self.id} - {self.user.username}"

    @property
    def full_address(self):
        place = ', '.join(part for part in (self.city, self.state) if part)
        if self.pincode:
            place = f'{place} - {self.pincode}' if place else self.pincode
        return ', '.join(part for part in (self.address, place) if part)

    @property
    def subtotal(self):
        return self.total_amount + self.discount_amount

    @property
    def can_cancel(self):
        return self.status in ('Pending', 'Processing')


class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items'
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField()

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    @property
    def total_price(self):
        return self.price * self.quantity


class Wishlist(models.Model):

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='wishlist_items'
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='wishlist_items'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.product.name}"

class Review(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews'
    )

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='reviews'
    )

    rating = models.PositiveSmallIntegerField(
        choices=[(i, f'{i} star{"s" if i > 1 else ""}') for i in range(1, 6)]
    )

    title = models.CharField(max_length=120, blank=True)

    comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('product', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.product.name} - {self.rating}/5 by {self.user.username}'


class Address(models.Model):

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='addresses'
    )

    full_name = models.CharField(max_length=200)

    phone = models.CharField(max_length=15)

    line = models.CharField('Address', max_length=255)

    city = models.CharField(max_length=100)

    state = models.CharField(max_length=100)

    pincode = models.CharField(max_length=10)

    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', '-created_at']
        verbose_name_plural = 'addresses'

    def __str__(self):
        return f'{self.full_name}, {self.city} - {self.pincode}'

    @property
    def full_address(self):
        return f'{self.line}, {self.city}, {self.state} - {self.pincode}'


class Coupon(models.Model):

    code = models.CharField(max_length=30, unique=True)

    discount_percent = models.PositiveIntegerField(
        help_text='Percentage off, 1 to 100'
    )

    max_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Optional cap on the discount amount'
    )

    min_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    active = models.BooleanField(default=True)

    valid_from = models.DateTimeField(null=True, blank=True)

    valid_to = models.DateTimeField(null=True, blank=True)

    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Total number of times this coupon can be used'
    )

    times_used = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def evaluate(self, subtotal):
        """Return (discount_amount, error_message)."""
        from django.utils import timezone

        now = timezone.now()

        if not self.active:
            return 0, 'This coupon is not active.'

        if self.valid_from and now < self.valid_from:
            return 0, 'This coupon is not valid yet.'

        if self.valid_to and now > self.valid_to:
            return 0, 'This coupon has expired.'

        if self.usage_limit is not None and self.times_used >= self.usage_limit:
            return 0, 'This coupon has reached its usage limit.'

        if subtotal < self.min_order_amount:
            return 0, f'Add items worth Rs. {self.min_order_amount} or more to use this coupon.'

        discount = subtotal * self.discount_percent / 100

        if self.max_discount is not None:
            discount = min(discount, self.max_discount)

        return round(discount, 2), ''


class ReturnRequest(models.Model):

    STATUS_CHOICES = [
        ('Requested', 'Requested'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Refunded', 'Refunded'),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='return_requests'
    )

    reason = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Requested'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Return for order #{self.order_id} ({self.status})'


class StockAlert(models.Model):
    """'Notify me when back in stock' sign-ups."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_alerts'
    )

    email = models.EmailField()

    created_at = models.DateTimeField(auto_now_add=True)

    notified = models.BooleanField(default=False)

    class Meta:
        unique_together = ('product', 'email')

    def __str__(self):
        return f'{self.email} -> {self.product.name}'

# =========================================================
# AFFILIATE PROGRAM
# =========================================================

class Affiliate(models.Model):

    STATUS_CHOICES = [
        ('Pending', 'Pending approval'),
        ('Approved', 'Approved'),
        ('Suspended', 'Suspended'),
    ]

    PAYOUT_METHODS = [
        ('UPI', 'UPI'),
        ('BANK', 'Bank transfer'),
    ]

    user = models.OneToOneField(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='affiliate'
    )

    code = models.CharField(max_length=20, unique=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Pending'
    )

    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        help_text='Percent of the order total paid to this affiliate'
    )

    promo_description = models.TextField(
        blank=True,
        help_text='How the affiliate plans to promote the store'
    )

    payout_method = models.CharField(max_length=10, choices=PAYOUT_METHODS, blank=True)
    upi_id = models.CharField(max_length=80, blank=True)
    account_holder = models.CharField(max_length=120, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=24, blank=True)
    ifsc = models.CharField(max_length=15, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} ({self.code})'

    @property
    def is_approved(self):
        return self.status == 'Approved'

    @property
    def has_payout_details(self):
        if self.payout_method == 'UPI':
            return bool(self.upi_id)
        if self.payout_method == 'BANK':
            return bool(self.account_holder and self.account_number and self.ifsc)
        return False

    @property
    def payout_summary(self):
        if self.payout_method == 'UPI':
            return f'UPI: {self.upi_id}'
        if self.payout_method == 'BANK':
            tail = self.account_number[-4:] if self.account_number else ''
            return f'{self.bank_name or "Bank"} A/c ****{tail} ({self.ifsc})'
        return 'Not set'

    def _sum(self, **filters):
        from django.db.models import Sum
        return self.commissions.filter(**filters).aggregate(t=Sum('amount'))['t'] or 0

    @property
    def pending_amount(self):          # waiting for delivery
        return self._sum(status='Pending')

    @property
    def available_balance(self):       # approved and not yet requested
        return self._sum(status='Approved', payout__isnull=True)

    @property
    def requested_amount(self):        # inside a payout request
        return self._sum(status='Approved', payout__isnull=False)

    @property
    def paid_amount(self):
        return self._sum(status='Paid')

    @property
    def lifetime_earnings(self):
        return self.pending_amount + self.available_balance + self.requested_amount + self.paid_amount


class AffiliateClick(models.Model):

    affiliate = models.ForeignKey(
        Affiliate,
        on_delete=models.CASCADE,
        related_name='clicks'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    landing_path = models.CharField(max_length=200, blank=True)

    referer = models.CharField(max_length=200, blank=True)

    visitor = models.CharField(max_length=40, blank=True)   # hashed, never the raw IP

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.affiliate.code} click {self.created_at:%Y-%m-%d %H:%M}'


class Payout(models.Model):

    STATUS_CHOICES = [
        ('Requested', 'Requested'),
        ('Paid', 'Paid'),
        ('Rejected', 'Rejected'),
    ]

    affiliate = models.ForeignKey(
        Affiliate,
        on_delete=models.CASCADE,
        related_name='payouts'
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Requested')

    method_summary = models.CharField(max_length=200, blank=True)   # where the money goes

    reference = models.CharField(max_length=120, blank=True)        # UTR / transaction id

    note = models.CharField(max_length=255, blank=True)

    requested_at = models.DateTimeField(auto_now_add=True)

    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f'Payout #{self.pk} Rs.{self.amount} ({self.status})'


class Commission(models.Model):

    STATUS_CHOICES = [
        ('Pending', 'Pending (order not delivered yet)'),
        ('Approved', 'Approved'),
        ('Paid', 'Paid'),
        ('Cancelled', 'Cancelled'),
    ]

    affiliate = models.ForeignKey(
        Affiliate,
        on_delete=models.CASCADE,
        related_name='commissions'
    )

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='commission'
    )

    order_amount = models.DecimalField(max_digits=10, decimal_places=2)

    rate = models.DecimalField(max_digits=5, decimal_places=2)

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')

    payout = models.ForeignKey(
        Payout,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='commissions'
    )

    note = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Commission Rs.{self.amount} on order #{self.order_id} ({self.status})'