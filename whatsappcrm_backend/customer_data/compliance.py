# whatsappcrm_backend/customer_data/compliance.py
"""
Responsible-gambling compliance checks and controls.

Central place for the regulatory gating a real-money betting product needs:
- age verification (>= minimum age) before a first bet,
- optional KYC gating before a first bet,
- self-exclusion (blocks betting and deposits while active),
- daily deposit and daily stake limits.

Enforced at the two money chokepoints:
- customer_data.ticket_processing.process_bet_ticket_submission (betting),
- customer_data.utils.perform_deposit (deposits).

Each check returns (allowed: bool, message: str) so callers can surface a clear,
user-facing reason. Limits/exclusion default to "off" (no limit, not excluded)
so existing behaviour is unchanged until a user or admin sets them; the age gate
is on by default (configurable via settings.RG_MIN_AGE), and KYC gating is
off by default (settings.RG_REQUIRE_KYC) since verification is operator-driven.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone


def _min_age() -> int:
    return int(getattr(settings, 'RG_MIN_AGE', 18))


def _require_kyc() -> bool:
    return bool(getattr(settings, 'RG_REQUIRE_KYC', False))


def get_controls(user):
    """Return (creating if needed) the user's ResponsibleGamblingControls."""
    from .models import ResponsibleGamblingControls
    controls, _ = ResponsibleGamblingControls.objects.get_or_create(user=user)
    return controls


def _age_from_dob(dob):
    if not dob:
        return None
    today = timezone.localdate()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def user_age(user):
    """Age derived from the linked CustomerProfile's date_of_birth, or None."""
    profile = getattr(user, 'customer_profile', None)
    return _age_from_dob(getattr(profile, 'date_of_birth', None)) if profile else None


def check_can_bet(user, controls=None) -> tuple[bool, str]:
    """Age, KYC and self-exclusion gate for placing a bet."""
    controls = controls or get_controls(user)

    if controls.is_self_excluded():
        until = timezone.localtime(controls.self_excluded_until).strftime('%d %b %Y %H:%M')
        return False, (f"🛡️ You are self-excluded until {until}. Betting and deposits are blocked "
                       f"until then. If you need support, please contact us.")

    age = user_age(user)
    min_age = _min_age()
    if age is None:
        return False, (f"To bet you must confirm your date of birth (you must be {min_age}+). "
                       f"Please complete your profile first.")
    if age < min_age:
        return False, f"You must be at least {min_age} years old to place a bet."

    if _require_kyc() and not controls.kyc_verified:
        return False, ("Before your first bet we need to verify your identity (KYC). "
                       "Please complete verification to continue.")

    return True, ""


def deposits_today(user) -> Decimal:
    from .models import WalletTransaction
    since = timezone.now() - timedelta(hours=24)
    total = (WalletTransaction.objects
             .filter(wallet__user=user, transaction_type='DEPOSIT', created_at__gte=since)
             .exclude(status='FAILED')
             .aggregate(s=Sum('amount'))['s'])
    return total or Decimal('0.00')


def stakes_today(user) -> Decimal:
    """Total staked in the last 24h (BET_PLACED transactions are stored negative)."""
    from .models import WalletTransaction
    since = timezone.now() - timedelta(hours=24)
    total = (WalletTransaction.objects
             .filter(wallet__user=user, transaction_type='BET_PLACED', created_at__gte=since)
             .aggregate(s=Sum('amount'))['s'])
    return abs(total) if total else Decimal('0.00')


def check_deposit_within_limit(user, amount, controls=None) -> tuple[bool, str]:
    controls = controls or get_controls(user)
    if controls.is_self_excluded():
        until = timezone.localtime(controls.self_excluded_until).strftime('%d %b %Y %H:%M')
        return False, f"🛡️ You are self-excluded until {until}. Deposits are blocked until then."
    limit = controls.daily_deposit_limit
    if limit is not None:
        used = deposits_today(user)
        if used + Decimal(str(amount)) > limit:
            remaining = max(Decimal('0.00'), limit - used)
            return False, (f"That deposit would exceed your daily deposit limit of ${limit:.2f}. "
                           f"You have ${remaining:.2f} left today.")
    return True, ""


def check_stake_within_limit(user, stake, controls=None) -> tuple[bool, str]:
    controls = controls or get_controls(user)
    limit = controls.daily_stake_limit
    if limit is not None:
        used = stakes_today(user)
        if used + Decimal(str(stake)) > limit:
            remaining = max(Decimal('0.00'), limit - used)
            return False, (f"That stake would exceed your daily stake limit of ${limit:.2f}. "
                           f"You have ${remaining:.2f} left today.")
    return True, ""


# --- Controls management (used by the WhatsApp "Safer gambling" flow) -------- #

def set_self_exclusion(user, days: int):
    controls = get_controls(user)
    controls.self_excluded_until = timezone.now() + timedelta(days=int(days))
    controls.save(update_fields=['self_excluded_until', 'updated_at'])
    return controls


def set_daily_deposit_limit(user, amount):
    controls = get_controls(user)
    controls.daily_deposit_limit = None if amount in (None, '') else Decimal(str(amount))
    controls.save(update_fields=['daily_deposit_limit', 'updated_at'])
    return controls


def set_daily_stake_limit(user, amount):
    controls = get_controls(user)
    controls.daily_stake_limit = None if amount in (None, '') else Decimal(str(amount))
    controls.save(update_fields=['daily_stake_limit', 'updated_at'])
    return controls


def limits_summary(user) -> str:
    controls = get_controls(user)
    dep = f"${controls.daily_deposit_limit:.2f}" if controls.daily_deposit_limit is not None else "none"
    stake = f"${controls.daily_stake_limit:.2f}" if controls.daily_stake_limit is not None else "none"
    lines = [
        "🛡️ *Safer Gambling*",
        "",
        f"Daily deposit limit: {dep}",
        f"Daily stake limit: {stake}",
    ]
    if controls.is_self_excluded():
        until = timezone.localtime(controls.self_excluded_until).strftime('%d %b %Y %H:%M')
        lines.append(f"Self-excluded until: {until}")
    else:
        lines.append("Self-excluded: no")
    lines.append("")
    lines.append("Set a limit or take a break using the options below. "
                 "If gambling stops being fun, please take a break.")
    return "\n".join(lines)
