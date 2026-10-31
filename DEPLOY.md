# Going live: Vanshora

Everything below is in the order you should do it.

## 1. Before you deploy (on your own computer)

1. Rotate your Razorpay keys. The test keys used while developing were shared in a chat,
   so treat them as public. Create a new pair in the Razorpay dashboard. For real payments
   switch the dashboard to **Live mode** and use the live key id and secret.
2. Decide how you will send email (Gmail app password, Zoho, SendGrid, AWS SES, ...).
3. Read and edit the legal pages for your business: `templates/pages/about_page.html` (About page text),
   `privacy.html`, `terms.html` and `returns.html` in the same folder. They contain general text, not legal advice.
4. Put real product photos in through the admin panel (`/admin/dashboard/` > Products).
   The sample products added with `python manage.py seed_demo` have placeholder pictures.
   Remove all sample products at once with `python manage.py seed_demo --remove`.
5. Delete the old backup copies if you no longer need them:
   `templates_backup/` and the `db.sqlite3.backup-*` files.

## 2. Server settings (.env)

Copy `.env.example` to `.env` on the server and fill it in. The important ones:

| Setting | Meaning |
|---|---|
| `DEBUG=False` | Must be False in production |
| `SECRET_KEY` | Long random string. Make one with `python -c "import secrets;print(secrets.token_urlsafe(60))"` |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` | Your domain (https) |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Live keys |
| `RAZORPAY_WEBHOOK_SECRET` | See step 4 below |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | Your email provider |

## 3. Install and start

```
python -m venv .venv
.venv\Scripts\activate            (Linux: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py check --deploy   (should show only the optional HSTS preload note)
gunicorn vanshuuu.wsgi --workers 3 --bind 0.0.0.0:8000
```

Run gunicorn behind Nginx (or the platform's router) with HTTPS. The app redirects
to HTTPS and trusts the `X-Forwarded-Proto` header.

* **Static files** are served by WhiteNoise. Nothing else to set up.
* **Uploaded images** (`/media/`): with `SERVE_MEDIA=True` Django serves them, which is fine for a
  small store on one server. For heavier traffic let Nginx serve `/media/` from the `media/`
  folder (and set `SERVE_MEDIA=False`) or move images to S3 / Cloudinary.
  On hosts with a temporary disk (Heroku, some Render plans) uploaded images vanish on every
  deploy. Use a persistent disk or cloud storage there.
* **Database:** SQLite works for a small shop on one server. For more, set the `DB_*` values
  to use PostgreSQL.

## 4. Razorpay webhook (important)

Without it, a customer who pays and then closes the browser before the page returns would
be charged but the order would stay unpaid. The webhook fixes that.

1. Razorpay dashboard > Settings > Webhooks > Add new webhook.
2. URL: `https://yourdomain.com/razorpay/webhook/`
3. Choose a secret, paste the same value into `RAZORPAY_WEBHOOK_SECRET`.
4. Tick the events `payment.captured`, `order.paid` and `payment.failed`.

## 5. Daily jobs

```
python manage.py cancel_stale_orders        # cancels online-payment orders never paid for 24 hours
```

Schedule it once a day (cron on Linux, Task Scheduler on Windows).

Back up `db.sqlite3` and the `media/` folder regularly, for example a nightly copy to
another place.

## 6. Test checklist after the first deploy

- Home, product page, search, filters and pagination load; product images show.
- Register, log in, log out, "Forgot password" email arrives.
- Add to cart, apply a coupon, checkout with Cash on Delivery. Order email arrives.
- Checkout with Razorpay (test with a small real amount in live mode). The order shows as Paid.
- Admin panel: change the order status, the customer gets an email.
- Affiliate: apply, approve, open the referral link in a private window, order, see the commission.
- `https://yourdomain.com/sitemap.xml` and `/robots.txt` open.

## 7. Things the program does by design

* Stock is taken when an order is placed (Cash on Delivery) or when the online payment succeeds.
* If a customer pays but the product sold out in between, the order is kept and marked with a
  note ("PAID BUT STOCK SHORT") in the admin order page so you can refund or restock.
* Refunds are not automatic. Refund in the Razorpay dashboard (or by cash), then mark it in the panel.
* Affiliate payouts are manual: pay by UPI or bank, then enter the reference in Payouts.
* Logging: errors are written to `logs/vanshuuu.log`.
