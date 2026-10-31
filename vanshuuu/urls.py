from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.sitemaps.views import sitemap
from django.urls import path, re_path, reverse_lazy
from django.views.static import serve

from app.sitemaps import sitemaps
from app.views import *
from app.views_extra import *
from app.views_panel import *
from app.views_affiliate import *
from app.views_panel_affiliate import *


handler404 = 'app.views_extra.error_404'
handler500 = 'app.views_extra.error_500'
handler403 = 'app.views_extra.error_403'


urlpatterns = [

    # =====================================================
    # ADMIN
    # =====================================================

    path('admin/dashboard/', admin_dashboard, name='admin_dashboard'),

    path('admin/', admin.site.urls),

    # =====================================================
    # STORE MANAGEMENT PANEL
    # =====================================================

    path('panel/', panel_home, name='panel_home'),

    path('panel/products/', panel_products, name='panel_products'),
    path('panel/products/add/', panel_product_form, name='panel_product_add'),
    path('panel/products/<int:product_id>/edit/', panel_product_form, name='panel_product_edit'),
    path('panel/products/<int:product_id>/quick/', panel_product_quick, name='panel_product_quick'),
    path('panel/products/<int:product_id>/delete/', panel_product_delete, name='panel_product_delete'),

    path('panel/categories/', panel_categories, name='panel_categories'),
    path('panel/categories/add/', panel_category_form, name='panel_category_add'),
    path('panel/categories/<int:category_id>/edit/', panel_category_form, name='panel_category_edit'),
    path('panel/categories/<int:category_id>/delete/', panel_category_delete, name='panel_category_delete'),

    path('panel/orders/', panel_orders, name='panel_orders'),
    path('panel/orders/export/', panel_orders_export, name='panel_orders_export'),
    path('panel/orders/<int:order_id>/', panel_order_detail, name='panel_order_detail'),
    path('panel/orders/<int:order_id>/update/', panel_order_update, name='panel_order_update'),

    path('panel/customers/', panel_customers, name='panel_customers'),
    path('panel/customers/<int:user_id>/', panel_customer_detail, name='panel_customer_detail'),
    path('panel/customers/<int:user_id>/toggle/', panel_customer_toggle, name='panel_customer_toggle'),

    path('panel/coupons/', panel_coupons, name='panel_coupons'),
    path('panel/coupons/add/', panel_coupon_form, name='panel_coupon_add'),
    path('panel/coupons/<int:coupon_id>/edit/', panel_coupon_form, name='panel_coupon_edit'),
    path('panel/coupons/<int:coupon_id>/toggle/', panel_coupon_toggle, name='panel_coupon_toggle'),
    path('panel/coupons/<int:coupon_id>/delete/', panel_coupon_delete, name='panel_coupon_delete'),

    path('panel/reviews/', panel_reviews, name='panel_reviews'),
    path('panel/reviews/<int:review_id>/delete/', panel_review_delete, name='panel_review_delete'),

    path('panel/returns/', panel_returns, name='panel_returns'),
    path('panel/returns/<int:return_id>/update/', panel_return_update, name='panel_return_update'),

    path('panel/stock-requests/', panel_alerts, name='panel_alerts'),
    path('panel/stock-requests/<int:alert_id>/delete/', panel_alert_delete, name='panel_alert_delete'),

    path('panel/affiliates/', panel_affiliates, name='panel_affiliates'),
    path('panel/affiliates/<int:affiliate_id>/', panel_affiliate_detail, name='panel_affiliate_detail'),
    path('panel/affiliates/<int:affiliate_id>/update/', panel_affiliate_update, name='panel_affiliate_update'),
    path('panel/affiliates/<int:affiliate_id>/quick/', panel_affiliate_quick, name='panel_affiliate_quick'),
    path('panel/commissions/', panel_commissions, name='panel_commissions'),
    path('panel/payouts/', panel_payouts, name='panel_payouts'),
    path('panel/payouts/<int:payout_id>/paid/', panel_payout_paid, name='panel_payout_paid'),
    path('panel/payouts/<int:payout_id>/reject/', panel_payout_reject, name='panel_payout_reject'),


    # =====================================================
    # HOME + PRODUCTS
    # =====================================================

    path('', home, name='home'),

    path('product/', products, name='products'),

    path('product/<slug:slug>/', product_detail, name='product_detail'),

    path('search/suggest/', search_suggest, name='search_suggest'),

    path('product/<int:product_id>/review/', submit_review, name='submit_review'),

    path('product/<int:product_id>/review/delete/', delete_review, name='delete_review'),

    path('product/<int:product_id>/notify/', notify_me, name='notify_me'),


    # =====================================================
    # AUTHENTICATION
    # =====================================================

    path('register/', register, name='register'),

    path('login/', user_login, name='login'),

    path('logout/', user_logout, name='logout'),


    # Forgot / reset password
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.txt',
            subject_template_name='registration/password_reset_subject.txt',
            success_url=reverse_lazy('password_reset_done'),
        ),
        name='password_reset'
    ),

    path(
        'password-reset/sent/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html'
        ),
        name='password_reset_done'
    ),

    path(
        'password-reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('password_reset_complete'),
        ),
        name='password_reset_confirm'
    ),

    path(
        'password-reset/complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html'
        ),
        name='password_reset_complete'
    ),


    # =====================================================
    # ACCOUNT
    # =====================================================

    path('account/', profile, name='profile'),

    path('account/addresses/', address_list, name='address_list'),

    path('account/addresses/add/', address_form, name='address_add'),

    path('account/addresses/<int:address_id>/edit/', address_form, name='address_edit'),

    path('account/addresses/<int:address_id>/delete/', address_delete, name='address_delete'),

    path('account/addresses/<int:address_id>/default/', address_make_default, name='address_default'),


    # =====================================================
    # CART + COUPONS
    # =====================================================

    path('cart/', cart, name='cart'),

    path('cart/add/<int:product_id>/', add_to_cart, name='add_to_cart'),

    path('cart/remove/<int:product_id>/', remove_from_cart, name='remove_from_cart'),

    path('cart/update/<int:product_id>/', update_cart, name='update_cart'),

    path('cart/coupon/apply/', apply_coupon, name='apply_coupon'),

    path('cart/coupon/remove/', remove_coupon, name='remove_coupon'),


    # =====================================================
    # CHECKOUT
    # =====================================================

    path('checkout/', checkout, name='checkout'),

    path('razorpay/verify/', razorpay_verify, name='razorpay_verify'),

    path('razorpay/webhook/', razorpay_webhook, name='razorpay_webhook'),


    # =====================================================
    # ORDERS
    # =====================================================

    path('order-success/<int:order_id>/', order_success, name='order_success'),

    path('my-orders/', my_orders, name='my_orders'),

    path('order/<int:order_id>/', order_detail, name='order_detail'),

    path('order/<int:order_id>/cancel/', cancel_order, name='cancel_order'),

    path('order/<int:order_id>/return/', request_return, name='request_return'),

    path('order/<int:order_id>/invoice/', invoice, name='invoice'),


    # =====================================================
    # WISHLIST
    # =====================================================

    path('wishlist/', wishlist, name='wishlist'),

    path('wishlist/add/<int:product_id>/', add_to_wishlist, name='add_to_wishlist'),

    path('wishlist/remove/<int:product_id>/', remove_from_wishlist, name='remove_from_wishlist'),

    path('wishlist/move-to-cart/<int:product_id>/', wishlist_move_to_cart, name='wishlist_move_to_cart'),


    # =====================================================
    # STATIC PAGES + SEO
    # =====================================================

    # =====================================================
    # AFFILIATE PROGRAM
    # =====================================================

    path('affiliate/', affiliate_landing, name='affiliate_landing'),
    path('affiliate/join/', affiliate_join, name='affiliate_join'),
    path('affiliate/dashboard/', affiliate_dashboard, name='affiliate_dashboard'),
    path('affiliate/settings/', affiliate_settings, name='affiliate_settings'),
    path('affiliate/payout/request/', affiliate_payout_request, name='affiliate_payout_request'),

    path('about/', about, name='about'),

    path('contact/', contact, name='contact'),

    path('privacy-policy/', privacy, name='privacy'),

    path('terms-and-conditions/', terms, name='terms'),

    path('returns-and-refunds/', returns_policy, name='returns'),

    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),

    path('robots.txt', robots_txt, name='robots'),

]


# =========================================================
# MEDIA FILES (development only; use Nginx / a CDN in production)
# =========================================================

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )

elif settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
