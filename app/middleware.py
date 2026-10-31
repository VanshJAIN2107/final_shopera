import hashlib

from django.conf import settings

from .affiliates import COOKIE_NAME
from .models import Affiliate, AffiliateClick


class AffiliateReferralMiddleware:
    """Remember which affiliate sent a visitor (?ref=CODE) and count the click."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        code = request.GET.get('ref', '').strip() if request.method == 'GET' else ''

        affiliate = None

        if code and len(code) <= 20:
            affiliate = (
                Affiliate.objects
                .filter(code__iexact=code, status='Approved')
                .first()
            )

        response = self.get_response(request)

        if affiliate is None:
            return response

        user = getattr(request, 'user', None)

        # affiliates clicking their own link are ignored
        if user is not None and user.is_authenticated and user.pk == affiliate.user_id:
            return response

        response.set_cookie(
            COOKIE_NAME,
            affiliate.code,
            max_age=settings.AFFILIATE_COOKIE_DAYS * 24 * 3600,
            httponly=True,
            samesite='Lax',
            secure=not settings.DEBUG,
        )

        # one counted click per visitor session per affiliate
        session_key = f'aff_click_{affiliate.code}'

        if hasattr(request, 'session') and not request.session.get(session_key):
            request.session[session_key] = True

            ip = request.META.get('REMOTE_ADDR', '')
            visitor = hashlib.sha256(f'{ip}{settings.SECRET_KEY}'.encode()).hexdigest()[:32]

            AffiliateClick.objects.create(
                affiliate=affiliate,
                landing_path=request.path[:200],
                referer=request.META.get('HTTP_REFERER', '')[:200],
                visitor=visitor,
            )

        return response
