"""
Django settings for the Vanshuuu store.

Secrets and per-environment values come from environment variables or from a
local ".env" file in the project root (see .env.example). Never commit .env.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# =========================================================
# ENVIRONMENT (.env loader, no extra dependency needed)
# =========================================================

def _load_env_file(path):
    if not path.exists():
        return

    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()

        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / '.env')


def env(name, default=''):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in env(name, default).split(',') if item.strip()]


# =========================================================
# CORE
# =========================================================

DEBUG = env_bool('DEBUG', False)

SECRET_KEY = env('SECRET_KEY')

if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'dev-only-insecure-key-change-me'
    else:
        raise RuntimeError(
            'SECRET_KEY is not set. Add it to your .env file or environment.'
        )

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')

CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

# Public base URL, used in emails and the sitemap
SITE_URL = env('SITE_URL', 'http://127.0.0.1:8000')

# Store name shown everywhere (pages, emails, invoices). Change it here or in .env
SITE_NAME = env('SITE_NAME', 'Vanshora')


# =========================================================
# APPS / MIDDLEWARE
# =========================================================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    'app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'app.middleware.AffiliateReferralMiddleware',
]

# Serve static files in production when WhiteNoise is installed
try:
    import whitenoise  # noqa: F401
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
except ImportError:
    pass

ROOT_URLCONF = 'vanshuuu.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'app.context_processors.nav_counts',
                'app.context_processors.site_info',
                'app.context_processors.panel_counts',
            ],
        },
    },
]

WSGI_APPLICATION = 'vanshuuu.wsgi.application'


# =========================================================
# DATABASE (SQLite by default, PostgreSQL if DB_NAME is set)
# =========================================================

if env('DB_NAME'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME'),
            'USER': env('DB_USER'),
            'PASSWORD': env('DB_PASSWORD'),
            'HOST': env('DB_HOST', 'localhost'),
            'PORT': env('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# =========================================================
# AUTH
# =========================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # reset links valid for 24 hours


# =========================================================
# INTERNATIONALIZATION
# =========================================================

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True


# =========================================================
# STATIC / MEDIA
# =========================================================

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =========================================================
# EMAIL
# =========================================================

EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = env('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(env('EMAIL_PORT', '25') or 25)
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', False)
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = env(
    'DEFAULT_FROM_EMAIL',
    'Vanshuuu Store <no-reply@vanshuuu.local>'
)


# =========================================================
# PAYMENTS (Razorpay)
# =========================================================

RAZORPAY_KEY_ID = env('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = env('RAZORPAY_KEY_SECRET')
RAZORPAY_WEBHOOK_SECRET = env('RAZORPAY_WEBHOOK_SECRET')


# =========================================================
# AFFILIATE PROGRAM
# =========================================================

AFFILIATE_DEFAULT_COMMISSION = env('AFFILIATE_DEFAULT_COMMISSION', '5')      # percent of order total
AFFILIATE_COOKIE_DAYS = int(env('AFFILIATE_COOKIE_DAYS', '30') or 30)         # how long a link click is remembered
AFFILIATE_MIN_PAYOUT = env('AFFILIATE_MIN_PAYOUT', '500')                  # rupees
AFFILIATE_AUTO_APPROVE = env_bool('AFFILIATE_AUTO_APPROVE', False)            # True = no manual approval


# =========================================================
# PRODUCTION SECURITY (only when DEBUG is off)
# =========================================================

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    X_FRAME_OPTIONS = 'DENY'

    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': (
                'whitenoise.storage.CompressedManifestStaticFilesStorage'
                if 'whitenoise.middleware.WhiteNoiseMiddleware' in MIDDLEWARE
                else 'django.contrib.staticfiles.storage.StaticFilesStorage'
            ),
        },
    }

# =========================================================
# MEDIA IN PRODUCTION
# =========================================================
# Best practice: let Nginx (or a CDN / S3 / Cloudinary) serve /media/.
# On a small single-server site you can let Django serve uploaded images:
SERVE_MEDIA = env_bool('SERVE_MEDIA', True)


# =========================================================
# LOGGING (errors go to the console and to logs/vanshuuu.log)
# =========================================================

LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'plain': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'},
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'vanshuuu.log'),
            'maxBytes': 2_000_000,
            'backupCount': 5,
            'formatter': 'plain',
            'encoding': 'utf-8',
        },
    },
    'root': {'handlers': ['console', 'file'], 'level': 'WARNING'},
    'loggers': {
        'app': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'django.request': {'handlers': ['console', 'file'], 'level': 'ERROR', 'propagate': False},
    },
}
