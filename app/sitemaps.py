from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, Product


class StaticSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return ['home', 'products', 'about', 'contact', 'privacy', 'terms', 'returns']

    def location(self, item):
        return reverse(item)


class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Product.objects.filter(is_available=True).order_by('id')

    def lastmod(self, obj):
        return obj.created_at

    def location(self, obj):
        return reverse('product_detail', args=[obj.slug])


class CategorySitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Category.objects.order_by('id')

    def location(self, obj):
        return f"{reverse('products')}?category={obj.slug}"


sitemaps = {
    'static': StaticSitemap,
    'products': ProductSitemap,
    'categories': CategorySitemap,
}
