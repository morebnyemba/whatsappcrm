# whatsappcrm_backend/customer_data/test_compliance.py
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from conversations.models import Contact
from . import compliance
from .models import CustomerProfile, UserWallet, WalletTransaction, ResponsibleGamblingControls


def _make_user(username, dob=None):
    user = User.objects.create(username=username)
    contact = Contact.objects.create(whatsapp_id=f"wa_{username}")
    CustomerProfile.objects.create(contact=contact, user=user, date_of_birth=dob)
    return user


class ComplianceTests(TestCase):
    def setUp(self):
        adult_dob = date.today().replace(year=date.today().year - 25)
        self.adult = _make_user('adult', dob=adult_dob)

    def test_missing_dob_blocks_betting(self):
        user = _make_user('nodob', dob=None)
        allowed, msg = compliance.check_can_bet(user)
        self.assertFalse(allowed)
        self.assertIn('date of birth', msg.lower())

    def test_underage_blocked(self):
        minor = _make_user('minor', dob=date.today().replace(year=date.today().year - 15))
        allowed, msg = compliance.check_can_bet(minor)
        self.assertFalse(allowed)
        self.assertIn('18', msg)

    def test_adult_allowed(self):
        allowed, msg = compliance.check_can_bet(self.adult)
        self.assertTrue(allowed)

    @override_settings(RG_REQUIRE_KYC=True)
    def test_kyc_gate(self):
        allowed, msg = compliance.check_can_bet(self.adult)
        self.assertFalse(allowed)
        self.assertIn('verify', msg.lower())
        controls = compliance.get_controls(self.adult)
        controls.kyc_verified = True
        controls.save()
        allowed, _ = compliance.check_can_bet(self.adult)
        self.assertTrue(allowed)

    def test_self_exclusion_blocks_bet_and_deposit(self):
        compliance.set_self_exclusion(self.adult, days=7)
        allowed, msg = compliance.check_can_bet(self.adult)
        self.assertFalse(allowed)
        self.assertIn('self-excluded', msg.lower())
        ok, msg2 = compliance.check_deposit_within_limit(self.adult, 10)
        self.assertFalse(ok)

    def test_daily_deposit_limit(self):
        compliance.set_daily_deposit_limit(self.adult, 100)
        wallet, _ = UserWallet.objects.get_or_create(user=self.adult)
        WalletTransaction.objects.create(wallet=wallet, amount=Decimal('80'),
                                         transaction_type='DEPOSIT', status='COMPLETED')
        ok, msg = compliance.check_deposit_within_limit(self.adult, 30)  # 80+30 > 100
        self.assertFalse(ok)
        ok2, _ = compliance.check_deposit_within_limit(self.adult, 20)   # 80+20 == 100
        self.assertTrue(ok2)

    def test_daily_stake_limit(self):
        compliance.set_daily_stake_limit(self.adult, 50)
        wallet, _ = UserWallet.objects.get_or_create(user=self.adult)
        # Stakes are recorded as negative BET_PLACED transactions.
        WalletTransaction.objects.create(wallet=wallet, amount=Decimal('-40'),
                                         transaction_type='BET_PLACED', status='COMPLETED')
        ok, msg = compliance.check_stake_within_limit(self.adult, 20)  # 40+20 > 50
        self.assertFalse(ok)
        ok2, _ = compliance.check_stake_within_limit(self.adult, 10)   # 40+10 == 50
        self.assertTrue(ok2)

    def test_remove_limit(self):
        compliance.set_daily_deposit_limit(self.adult, 100)
        compliance.set_daily_deposit_limit(self.adult, None)
        self.assertIsNone(compliance.get_controls(self.adult).daily_deposit_limit)
