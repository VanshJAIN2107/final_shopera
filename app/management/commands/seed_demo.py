"""
Add sample categories and products to the store.

    python manage.py seed_demo            add them (safe to run again)
    python manage.py seed_demo --remove   remove them again (ordered ones are only hidden)

Product images are generated placeholders saved in media/products/demo/.
Replace them with real photos from the admin panel (Products > Edit).
"""

import random
import textwrap
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from app.models import Category, OrderItem, Product

IMAGE_DIR = 'products/demo/'

# category name -> (gradient colours, list of products)
# product: (name, description, price, mrp or None, stock)
CATALOG = {
    'Footwear': (('#3b2f2a', '#b8864b'), [
        ('Classic White Sneakers for Men',
         'Clean everyday sneakers with a cushioned insole, breathable upper and grippy rubber sole. Goes with jeans, chinos and shorts.', 1499, 2499, 60),
        ('Running Shoes with Air Cushion',
         'Lightweight mesh running shoes with shock-absorbing midsole and flexible outsole for long daily runs.', 1899, 3299, 45),
        ('Leather Formal Oxford Shoes',
         'Handcrafted look faux-leather oxfords with lace-up closure and padded footbed, made for office and weddings.', 2199, 3999, 30),
        ('Women\'s Casual Flat Sandals',
         'Soft strap flat sandals with anti-slip sole. Comfortable for all-day wear, easy to match with any outfit.', 699, 1199, 80),
    ]),
    'Watches & Accessories': (('#2b211c', '#9a6b3f'), [
        ('Analog Wrist Watch with Leather Strap',
         'Minimal dial analog watch with date window, scratch resistant glass and a genuine-feel leather strap.', 1299, 2499, 40),
        ('Smart Fitness Band with Heart Rate',
         'Track steps, sleep, heart rate and workouts. 10-day battery, water resistant and call or message alerts.', 1799, 3499, 55),
        ('Polarized Aviator Sunglasses',
         'UV400 polarized lenses in a lightweight metal frame. Reduces glare for driving and outdoor trips.', 599, 1299, 90),
        ('Genuine Leather Wallet for Men',
         'Slim bi-fold wallet with 6 card slots, coin pocket and RFID protection in a premium leather finish.', 549, 999, 70),
    ]),
    'Home & Kitchen': (('#4a5d4f', '#c8b28a'), [
        ('Stainless Steel Water Bottle 1 Litre',
         'Double wall vacuum insulated bottle that keeps drinks cold for 24 hours and hot for 12. Leak proof lid.', 649, 999, 100),
        ('Non-Stick Cookware Set 3 Piece',
         'Induction friendly non-stick kadhai, fry pan and tawa with cool-touch handles and glass lid.', 1599, 2999, 35),
        ('Cotton Bedsheet Double Bed with 2 Pillow Covers',
         'Soft 180 TC cotton bedsheet with vibrant fade-resistant print. Easy to wash and long lasting.', 799, 1599, 60),
        ('LED Table Lamp with Touch Dimmer',
         'Rechargeable LED desk lamp with 3 colour modes, touch dimmer and flexible neck. Perfect for study and work.', 899, 1499, 50),
    ]),
    'Beauty & Personal Care': (('#8c5a52', '#e8c5a0'), [
        ('Vitamin C Face Serum 30 ml',
         'Brightening serum with 10 percent Vitamin C and hyaluronic acid. Helps reduce dark spots and dullness.', 449, 799, 120),
        ('Beard Trimmer with 40 Length Settings',
         'Cordless USB rechargeable trimmer with stainless steel blades, 90 minutes runtime and travel lock.', 999, 1999, 65),
        ('Aloe Vera Gel with Cucumber 300 ml',
         'Cooling multipurpose gel for face, skin and hair. Paraben free and suitable for daily use.', 199, 349, 150),
        ('Hair Dryer 1800W with Cool Shot',
         'Fast drying hair dryer with 2 speed and 3 heat settings, concentrator nozzle and cool shot button.', 799, 1499, 45),
    ]),
    'Books & Stationery': (('#34495e', '#d9a066'), [
        ('Hardbound Ruled Notebook A5 (Pack of 3)',
         '192 pages each, 100 GSM bleed-proof paper and a sturdy hard cover. Ideal for notes, journals and planning.', 349, 599, 140),
        ('Gel Pens Set of 20 Assorted Colours',
         'Smooth writing 0.5 mm gel pens in vibrant colours. Quick drying ink, great for school, office and art.', 199, 399, 200),
        ('Daily Planner and Goal Tracker 2026',
         'Undated daily planner with habit tracker, priority lists and monthly review pages in a premium cover.', 299, 499, 90),
        ('Wooden Desk Organizer with Drawer',
         'Multi compartment desk organizer for pens, phone and documents. Keeps your workspace neat.', 699, 1199, 40),
    ]),
    'Sports & Fitness': (('#1f4e5f', '#e8c58f'), [
        ('Yoga Mat 6 mm Anti-Slip',
         'Extra thick, non-slip TPE yoga mat with carry strap. Comfortable for yoga, pilates and floor exercises.', 599, 1299, 85),
        ('Adjustable Dumbbell Set 20 kg',
         'Home gym dumbbell set with anti-rust plates and secure locking collars. Includes connecting rod for barbell use.', 2499, 3999, 25),
        ('Skipping Rope with Ball Bearing',
         'Tangle free speed jump rope with adjustable length and soft foam grips for cardio and boxing training.', 199, 399, 160),
        ('Gym Duffel Bag with Shoe Compartment',
         'Water resistant sports bag with separate shoe pocket, wet pouch and padded shoulder strap.', 799, 1499, 50),
    ]),
    'Mobiles & Accessories': (('#2c3e50', '#7fb3d5'), [
        ('20000 mAh Power Bank with Fast Charging',
         'Dual USB output power bank with 22.5W fast charging and LED battery indicator. Charges a phone 4 times.', 1299, 2299, 70),
        ('Wireless Bluetooth Earbuds with Mic',
         'True wireless earbuds with 30 hour playtime, touch controls, noise reduction mic and IPX5 sweat resistance.', 999, 2999, 80),
        ('Type-C Fast Charging Cable 1.5 m (Pack of 2)',
         'Braided nylon cable supporting up to 65W charging and fast data transfer. Reinforced and tangle free.', 299, 599, 180),
        ('Adjustable Mobile Stand for Desk',
         'Foldable aluminium phone and tablet holder with stable base and anti-slip pads for video calls and streaming.', 349, 699, 95),
    ]),
    'Bags & Luggage': (('#5b4636', '#d4b483'), [
        ('Laptop Backpack 30 L with USB Port',
         'Water resistant backpack with padded laptop sleeve up to 15.6 inch, USB charging port and anti-theft pocket.', 1099, 2199, 60),
        ('Travel Trolley Cabin Bag 55 cm',
         'Hard shell cabin luggage with 360 degree spinner wheels, TSA friendly lock and expandable interior.', 2999, 5499, 30),
        ('Women\'s Sling Handbag',
         'Stylish faux leather sling with adjustable strap, magnetic closure and multiple inner pockets.', 799, 1599, 55),
        ('Canvas Tote Bag with Zip',
         'Sturdy cotton canvas tote with inner zip pocket and long handles. Daily use, college and shopping.', 349, 699, 110),
    ]),
}


def make_image(title, category, colours, seed):
    """Create a simple branded placeholder picture (1600 x 1600) and return JPEG bytes."""
    from PIL import Image, ImageDraw, ImageFont

    size = 1600
    k = size / 800                      # the layout below was designed for 800 px
    top, bottom = colours

    def hex_to_rgb(value):
        value = value.lstrip('#')
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    a, b = hex_to_rgb(top), hex_to_rgb(bottom)

    image = Image.new('RGB', (size, size))
    draw = ImageDraw.Draw(image)

    for y in range(size):
        t = y / size
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        )

    rng = random.Random(seed)

    # soft decorative circles
    overlay = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for _ in range(5):
        r = int(rng.randint(90, 260) * k)
        x, y = int(rng.randint(-40, 800) * k), int(rng.randint(-40, 800) * k)
        od.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rng.randint(14, 34)))
    image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(image)

    def font(path, px):
        try:
            return ImageFont.truetype(path, int(px * k))
        except OSError:
            return ImageFont.load_default()

    bold = font(r'C:\Windows\Fonts\segoeuib.ttf', 54)
    light = font(r'C:\Windows\Fonts\segoeui.ttf', 30)

    # card
    draw.rounded_rectangle(
        [90 * k, 190 * k, 710 * k, 610 * k], radius=int(36 * k), fill=(255, 255, 255)
    )

    lines = textwrap.wrap(title, width=17)[:4]
    y = (400 - (len(lines) * 62) // 2) * k
    for line in lines:
        w = draw.textlength(line, font=bold)
        draw.text(((size - w) / 2, y), line, font=bold, fill=(43, 33, 28))
        y += 62 * k

    tag = category.upper()
    w = draw.textlength(tag, font=light)
    draw.text(((size - w) / 2, 140 * k), tag, font=light, fill=(255, 255, 255))

    brand = settings.SITE_NAME
    w = draw.textlength(brand, font=light)
    draw.text(((size - w) / 2, 650 * k), brand, font=light, fill=(255, 255, 255))

    buffer = BytesIO()
    image.save(buffer, 'JPEG', quality=92, subsampling=0)
    return buffer.getvalue()

class Command(BaseCommand):
    help = 'Add (or remove) sample categories and products.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--remove', action='store_true',
            help='Remove the sample products added by this command.'
        )
        parser.add_argument(
            '--regenerate', action='store_true',
            help='Redraw the placeholder pictures sharper. Photos you uploaded yourself are not touched.'
        )

    def handle(self, *args, **options):
        if options['remove']:
            return self.remove()

        if options['regenerate']:
            return self.regenerate()

        made_categories = made_products = skipped = 0

        for category_name, (colours, products) in CATALOG.items():

            category, created = Category.objects.get_or_create(
                slug=slugify(category_name),
                defaults={'name': category_name},
            )
            made_categories += int(created)

            for name, description, price, mrp, stock in products:

                slug = slugify(name)[:45]

                if Product.objects.filter(slug=slug).exists():
                    skipped += 1
                    continue

                with transaction.atomic():
                    product = Product(
                        category=category,
                        name=name,
                        slug=slug,
                        description=description,
                        price=Decimal(price),
                        mrp=Decimal(mrp) if mrp else None,
                        stock=stock,
                        is_available=True,
                    )

                    picture = make_image(name, category_name, colours, seed=slug)
                    product.image.save(
                        f'{IMAGE_DIR}{slug}.jpg'.replace('products/', '', 1),
                        ContentFile(picture),
                        save=False,
                    )
                    product.save()

                made_products += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. {made_categories} new categories, {made_products} new products '
            f'({skipped} already existed).'
        ))
        self.stdout.write(
            'Images are placeholders: replace them with real photos in the admin panel.'
        )

    def remove(self):
        removed = hidden = 0

        for product in Product.objects.filter(image__startswith=IMAGE_DIR):
            if OrderItem.objects.filter(product=product).exists():
                product.is_available = False
                product.save(update_fields=['is_available'])
                hidden += 1
            else:
                product.delete()
                removed += 1

        for category in Category.objects.filter(slug__in=[slugify(n) for n in CATALOG]):
            if not category.products.exists():
                category.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Removed {removed} sample products, hid {hidden} that were already ordered.'
        ))

    def regenerate(self):
        """Redraw only the pictures this command created (products/demo/...)."""
        done = 0

        for category_name, (colours, products) in CATALOG.items():
            for name, *_ in products:
                slug = slugify(name)[:45]
                product = Product.objects.filter(slug=slug).first()

                if not product or not product.image:
                    continue

                if not product.image.name.startswith(IMAGE_DIR):
                    continue                                 # a real photo, leave it alone

                with open(product.image.path, 'wb') as handle:
                    handle.write(make_image(name, category_name, colours, seed=slug))

                done += 1

        self.stdout.write(self.style.SUCCESS(f'Redrew {done} placeholder pictures at 1600 x 1600.'))