from django.conf import settings
from django.contrib import admin

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

# =========================================================
# ADMIN SITE BRANDING
# =========================================================

admin.site.site_header = settings.SITE_NAME.upper()
admin.site.site_title = f"{settings.SITE_NAME} Admin"
admin.site.index_title = "Store Management Dashboard"


# =========================================================
# CATEGORY ADMIN
# =========================================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'name',
        'slug',
        'product_count',
    )

    search_fields = (
        'name',
        'slug',
    )

    prepopulated_fields = {
        'slug': ('name',)
    }

    ordering = ('name',)

    def product_count(self, obj):
        return obj.products.count()

    product_count.short_description = "Products"


# =========================================================
# PRODUCT ADMIN
# =========================================================

class ProductImageInline(admin.TabularInline):

    model = ProductImage

    extra = 1

    fields = ('image', 'position')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    inlines = [ProductImageInline]

    list_display = (
    'id',
    'name',
    'category',
    'price',
    'stock',
    'is_available',
    'availability_status',
    'created_at',
)

    list_filter = (
        'category',
        'is_available',
        'created_at',
    )

    search_fields = (
        'name',
        'description',
        'slug',
    )

    prepopulated_fields = {
        'slug': ('name',)
    }

    list_editable = (
        'price',
        'stock',
        'is_available',
    )

    ordering = (
        '-created_at',
    )

    readonly_fields = (
        'created_at',
    )

    fieldsets = (
        (
            "Product Information",
            {
                'fields': (
                    'name',
                    'slug',
                    'category',
                    'description',
                    'image',
                )
            }
        ),
        (
            "Pricing & Inventory",
            {
                'fields': (
                    'price',
                    'mrp',
                    'stock',
                    'is_available',
                )
            }
        ),
        (
            "System Information",
            {
                'fields': (
                    'created_at',
                )
            }
        ),
    )

    def availability_status(self, obj):

        if not obj.is_available:
            return "❌ Unavailable"

        if obj.stock == 0:
            return "⚠️ Out of Stock"

        if obj.stock <= 5:
            return "⚠️ Low Stock"

        return "✅ Available"

    availability_status.short_description = "Status"


# =========================================================
# ORDER ITEM INLINE
# =========================================================

class OrderItemInline(admin.TabularInline):

    model = OrderItem

    extra = 0

    fields = (
        'product',
        'quantity',
        'price',
        'total',
    )

    readonly_fields = (
        'total',
    )

    def total(self, obj):

        if obj.quantity and obj.price:
            return obj.quantity * obj.price

        return 0

    total.short_description = "Total"


# =========================================================
# ORDER ADMIN
# =========================================================

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'customer_name',
        'phone',
        'total_amount',
        'payment_method',
        'payment_status',
        'status',
        'created_at',
    )

    list_filter = (
        'status',
        'payment_status',
        'payment_method',
        'created_at',
    )

    search_fields = (
        'user__username',
        'full_name',
        'phone',
        'razorpay_order_id',
        'razorpay_payment_id',
    )

    ordering = (
        '-created_at',
    )

    readonly_fields = (
        'created_at',
        'razorpay_order_id',
        'razorpay_payment_id',
        'razorpay_signature',
    )

    list_editable = (
        'status',
        'payment_status',
    )

    inlines = [
        OrderItemInline,
    ]

    fieldsets = (

        (
            "Customer Information",
            {
                'fields': (
                    'user',
                    'full_name',
                    'phone',
                    'address',
                    'pincode',
                    'city',
                    'state',
                )
            }
        ),

        (
            "Order Information",
            {
                'fields': (
                    'total_amount',
                    'status',
                    'created_at',
                )
            }
        ),

        (
            "Payment Information",
            {
                'fields': (
                    'payment_method',
                    'payment_status',
                )
            }
        ),

        (
            "Razorpay Details",
            {
                'classes': (
                    'collapse',
                ),
                'fields': (
                    'razorpay_order_id',
                    'razorpay_payment_id',
                    'razorpay_signature',
                )
            }
        ),
    )

    def customer_name(self, obj):
        return obj.full_name

    customer_name.short_description = "Customer"


# =========================================================
# ORDER ITEM ADMIN
# =========================================================

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'order',
        'product',
        'quantity',
        'price',
        'total_price_display',
    )

    search_fields = (
        'order__id',
        'product__name',
    )

    list_filter = (
        'product',
    )

    def total_price_display(self, obj):
        return obj.price * obj.quantity

    total_price_display.short_description = "Total"


# =========================================================
# WISHLIST ADMIN
# =========================================================

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'user',
        'product',
        'created_at',
    )

    search_fields = (
        'user__username',
        'product__name',
    )

    list_filter = (
        'created_at',
    )

    ordering = (
        '-created_at',
    )

    readonly_fields = (
        'created_at',
    )


# =========================================================
# REVIEWS, ADDRESSES, COUPONS, RETURNS, STOCK ALERTS
# =========================================================

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):

    list_display = ('product', 'user', 'rating', 'title', 'created_at')

    list_filter = ('rating', 'created_at')

    search_fields = ('product__name', 'user__username', 'title', 'comment')

    readonly_fields = ('created_at',)


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):

    list_display = ('user', 'full_name', 'city', 'state', 'pincode', 'is_default')

    search_fields = ('user__username', 'full_name', 'city', 'pincode')


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):

    list_display = (
        'code',
        'discount_percent',
        'max_discount',
        'min_order_amount',
        'active',
        'times_used',
        'usage_limit',
        'valid_to',
    )

    list_editable = ('active',)

    search_fields = ('code',)

    readonly_fields = ('times_used',)


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):

    list_display = ('id', 'order', 'status', 'created_at')

    list_filter = ('status', 'created_at')

    list_editable = ('status',)

    search_fields = ('order__id', 'order__full_name', 'reason')

    readonly_fields = ('created_at',)


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):

    list_display = ('product', 'email', 'notified', 'created_at')

    list_filter = ('notified',)

    search_fields = ('product__name', 'email')