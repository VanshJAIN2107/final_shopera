from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .emails import send_back_in_stock, send_order_status_update
from .affiliates import cancel_commission, sync_commission
from .models import Commission, Order, Product, ReturnRequest


@receiver(pre_save, sender=Order)
def remember_old_status(sender, instance, **kwargs):
    """Keep the previous status so post_save can tell if it changed."""
    instance._old_status = None

    if instance.pk:
        instance._old_status = (
            Order.objects.filter(pk=instance.pk)
            .values_list('status', flat=True)
            .first()
        )


@receiver(post_save, sender=Order)
def email_on_status_change(sender, instance, created, **kwargs):
    old = getattr(instance, '_old_status', None)

    if not created and old and old != instance.status:
        send_order_status_update(instance)


@receiver(pre_save, sender=Product)
def remember_old_stock(sender, instance, **kwargs):
    instance._old_stock = None

    if instance.pk:
        instance._old_stock = (
            Product.objects.filter(pk=instance.pk)
            .values_list('stock', flat=True)
            .first()
        )


@receiver(post_save, sender=Product)
def notify_back_in_stock(sender, instance, created, **kwargs):
    old = getattr(instance, '_old_stock', None)

    if created or old is None:
        return

    if old == 0 and instance.stock > 0 and instance.is_available:
        for alert in instance.stock_alerts.filter(notified=False):
            if send_back_in_stock(alert):
                alert.notified = True
                alert.save(update_fields=['notified'])

@receiver(post_save, sender=Order)
def update_affiliate_commission(sender, instance, created, **kwargs):
    if not created:
        sync_commission(instance)


@receiver(post_save, sender=ReturnRequest)
def cancel_commission_on_refund(sender, instance, **kwargs):
    if instance.status == 'Refunded':
        commission = Commission.objects.filter(order=instance.order).first()
        if commission:
            cancel_commission(commission, 'Order was refunded.')