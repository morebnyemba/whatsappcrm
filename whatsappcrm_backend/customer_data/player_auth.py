# whatsappcrm_backend/customer_data/player_auth.py
"""
Player web authentication via a WhatsApp one-time code.

Players don't have a web password — they interact through WhatsApp — so the
player portal (app.<domain>) logs them in by:
  1) POST /crm-api/auth/player/request-otp/  {phone}   → a 6-digit code is sent
     to that number over WhatsApp (generic response either way, to avoid leaking
     which numbers have accounts).
  2) POST /crm-api/auth/player/verify-otp/   {phone, code} → returns JWT
     access/refresh tokens for the linked user.

Codes are stored hashed, expire quickly, are single-use, attempt-limited, and
rate-limited per number.
"""
import logging
import secrets

from django.contrib.auth.hashers import make_password, check_password
from django.urls import path
from django.utils import timezone
from datetime import timedelta

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)

CODE_LENGTH = 6
OTP_TTL_MINUTES = 5
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
GENERIC_MSG = "If that number has an account, we've sent a login code on WhatsApp."


def _normalise_phone(raw: str) -> str:
    return ''.join(ch for ch in (raw or '') if ch.isdigit())


def _gen_code() -> str:
    return ''.join(secrets.choice('0123456789') for _ in range(CODE_LENGTH))


def request_login_otp(phone: str) -> None:
    """Generate and send an OTP if the number maps to a player account. Silent no-op otherwise."""
    from conversations.models import Contact
    from customer_data.models import CustomerProfile, PlayerLoginOTP
    from meta_integration.utils import send_whatsapp_message, create_text_message_data

    wa_id = _normalise_phone(phone)
    if not wa_id:
        return
    contact = Contact.objects.filter(whatsapp_id=wa_id).first()
    if not contact:
        return
    # Must map to a real user account.
    if not CustomerProfile.objects.filter(contact=contact, user__isnull=False).exists():
        return

    # Cooldown: don't resend if a fresh code was just issued.
    recent = PlayerLoginOTP.objects.filter(contact=contact, consumed=False).order_by('-created_at').first()
    if recent and recent.created_at > timezone.now() - timedelta(seconds=RESEND_COOLDOWN_SECONDS):
        return

    # Invalidate previous outstanding codes, then issue a new one.
    PlayerLoginOTP.objects.filter(contact=contact, consumed=False).update(consumed=True)
    code = _gen_code()
    PlayerLoginOTP.objects.create(
        contact=contact,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    body = (f"Your BetBlitz login code is *{code}*.\n"
            f"It expires in {OTP_TTL_MINUTES} minutes. If you didn't request it, ignore this message.")
    try:
        send_whatsapp_message(to_phone_number=wa_id, message_type='text', data=create_text_message_data(body))
    except Exception as e:
        logger.error(f"Failed to send login OTP to {wa_id}: {e}", exc_info=True)


def verify_login_otp(phone: str, code: str):
    """Return the authenticated user for a valid code, else None."""
    from conversations.models import Contact
    from customer_data.models import CustomerProfile, PlayerLoginOTP

    wa_id = _normalise_phone(phone)
    code = (code or '').strip()
    if not wa_id or not code:
        return None
    contact = Contact.objects.filter(whatsapp_id=wa_id).first()
    if not contact:
        return None
    otp = PlayerLoginOTP.objects.filter(contact=contact, consumed=False).order_by('-created_at').first()
    if not otp or not otp.is_valid():
        return None

    otp.attempts += 1
    if check_password(code, otp.code_hash):
        otp.consumed = True
        otp.save(update_fields=['attempts', 'consumed'])
        profile = CustomerProfile.objects.filter(contact=contact, user__isnull=False).select_related('user').first()
        return profile.user if profile else None

    # Wrong code: burn an attempt; lock the code out after too many tries.
    if otp.attempts >= MAX_ATTEMPTS:
        otp.consumed = True
    otp.save(update_fields=['attempts', 'consumed'])
    return None


class RequestOTPView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        request_login_otp(request.data.get('phone', ''))
        return Response({"detail": GENERIC_MSG}, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = verify_login_otp(request.data.get('phone', ''), request.data.get('code', ''))
        if not user:
            return Response({"detail": "Invalid or expired code."}, status=status.HTTP_400_BAD_REQUEST)
        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "username": user.username,
        }, status=status.HTTP_200_OK)


urlpatterns = [
    path('request-otp/', RequestOTPView.as_view(), name='player_request_otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='player_verify_otp'),
]
