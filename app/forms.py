from django import forms
from django.utils.text import slugify

from .models import Category, Coupon, Order, Product


# =========================================================
# helpers
# =========================================================

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.ImageField):
    """File field that accepts several files at once."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean

        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data if item]

        return [single_clean(data, initial)] if data else []


def unique_slug(model, text, instance=None):
    base = slugify(text)[:45] or 'item'
    slug = base
    number = 2

    queryset = model.objects.all()
    if instance is not None and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    while queryset.filter(slug=slug).exists():
        slug = f'{base}-{number}'
        number += 1

    return slug


class StyledForm(forms.ModelForm):
    """Adds Bootstrap classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            widget = field.widget

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault('class', 'form-control')
            else:
                widget.attrs.setdefault('class', 'form-control')


# =========================================================
# products / categories
# =========================================================

class ProductForm(StyledForm):

    gallery = MultipleFileField(
        required=False,
        label='More images',
        help_text='Optional. You can select several images at once.',
    )

    class Meta:
        model = Product
        fields = [
            'name', 'slug', 'category', 'description',
            'price', 'mrp', 'stock', 'is_available', 'image',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 6}),
        }
        help_texts = {
            'slug': 'Leave empty to create it from the name.',
            'mrp': 'Original price. Fill it to show a discount (must be higher than the price).',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['gallery'].widget.attrs.update({'class': 'form-control', 'accept': 'image/*'})

    def clean_slug(self):
        slug = slugify(self.cleaned_data.get('slug') or '')

        # editing with an empty slug keeps the product's current slug
        if not slug and self.instance.pk:
            return self.instance.slug

        if slug and Product.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Another product already uses this slug.')

        return slug

    def clean(self):
        cleaned = super().clean()

        price = cleaned.get('price')
        mrp = cleaned.get('mrp')

        if price is not None and price < 0:
            self.add_error('price', 'Price cannot be negative.')

        if mrp and price is not None and mrp <= price:
            self.add_error('mrp', 'MRP must be higher than the selling price (or leave it empty).')

        return cleaned

    def save(self, commit=True):
        product = super().save(commit=False)

        if not product.slug:
            product.slug = unique_slug(Product, product.name, product)

        if commit:
            product.save()

        return product


class CategoryForm(StyledForm):

    class Meta:
        model = Category
        fields = ['name', 'slug']
        help_texts = {'slug': 'Leave empty to create it from the name.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False

    def clean_slug(self):
        slug = slugify(self.cleaned_data.get('slug') or '')

        if slug and Category.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Another category already uses this slug.')

        return slug

    def save(self, commit=True):
        category = super().save(commit=False)

        if not category.slug:
            category.slug = unique_slug(Category, category.name, category)

        if commit:
            category.save()

        return category


# =========================================================
# coupons / orders
# =========================================================

class CouponForm(StyledForm):

    class Meta:
        model = Coupon
        fields = [
            'code', 'discount_percent', 'max_discount', 'min_order_amount',
            'valid_from', 'valid_to', 'usage_limit', 'active',
        ]
        widgets = {
            'valid_from': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'
            ),
            'valid_to': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valid_from'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        self.fields['valid_to'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper().replace(' ', '')

        if Coupon.objects.filter(code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This coupon code already exists.')

        return code

    def clean_discount_percent(self):
        value = self.cleaned_data['discount_percent']

        if value < 1 or value > 100:
            raise forms.ValidationError('Enter a percentage between 1 and 100.')

        return value

    def clean(self):
        cleaned = super().clean()

        start = cleaned.get('valid_from')
        end = cleaned.get('valid_to')

        if start and end and end <= start:
            self.add_error('valid_to', 'End date must be after the start date.')

        return cleaned


class OrderUpdateForm(StyledForm):

    class Meta:
        model = Order
        fields = ['status', 'payment_status']

# =========================================================
# affiliate program
# =========================================================

import re


class AffiliateApplyForm(forms.Form):

    promo_description = forms.CharField(
        required=False,
        max_length=600,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        label='How will you promote us?',
    )

    agree = forms.BooleanField(
        error_messages={'required': 'Please accept the affiliate terms to continue.'},
        label='I agree to the affiliate terms',
    )


class PayoutDetailsForm(forms.Form):

    payout_method = forms.ChoiceField(
        choices=[('UPI', 'UPI'), ('BANK', 'Bank transfer')],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    upi_id = forms.CharField(required=False, max_length=80)
    account_holder = forms.CharField(required=False, max_length=120)
    bank_name = forms.CharField(required=False, max_length=120)
    account_number = forms.CharField(required=False, max_length=24)
    ifsc = forms.CharField(required=False, max_length=15)

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('payout_method')

        if method == 'UPI':
            upi = (cleaned.get('upi_id') or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9._\-]{2,}@[A-Za-z0-9]{2,}', upi):
                self.add_error('upi_id', 'Enter a valid UPI id, like name@bank.')
            cleaned['upi_id'] = upi

        elif method == 'BANK':
            holder = (cleaned.get('account_holder') or '').strip()
            number = re.sub(r'\s', '', cleaned.get('account_number') or '')
            ifsc = (cleaned.get('ifsc') or '').strip().upper()

            if not holder:
                self.add_error('account_holder', 'Enter the account holder name.')

            if not re.fullmatch(r'\d{9,18}', number):
                self.add_error('account_number', 'Account number must be 9 to 18 digits.')

            if not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', ifsc):
                self.add_error('ifsc', 'Enter a valid IFSC code, like HDFC0001234.')

            cleaned.update(account_holder=holder, account_number=number, ifsc=ifsc)

        return cleaned