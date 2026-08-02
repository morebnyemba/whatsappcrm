# whatsappcrm_backend/customer_data/test_player_auth.py
import re
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from conversations.models import Contact
from .models import CustomerProfile, PlayerLoginOTP


class PlayerOtpAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('player_263771234567')
        self.contact = Contact.objects.create(whatsapp_id='263771234567')
        CustomerProfile.objects.create(contact=self.contact, user=self.user)
        self.client = APIClient()

    def _request_and_capture_code(self, phone='263771234567'):
        sent = {}
        def fake_send(to_phone_number, message_type, data):
            sent['to'] = to_phone_number; sent['body'] = data.get('body', '')
            return {"messages": [{"id": "x"}]}
        with mock.patch('meta_integration.utils.send_whatsapp_message', side_effect=fake_send):
            r = self.client.post('/crm-api/auth/player/request-otp/', {'phone': phone}, format='json')
        self.assertEqual(r.status_code, 200)
        m = re.search(r'\*(\d{6})\*', sent.get('body', ''))
        return (m.group(1) if m else None), sent

    def test_full_otp_login(self):
        code, sent = self._request_and_capture_code()
        self.assertIsNotNone(code)
        self.assertEqual(sent['to'], '263771234567')
        r = self.client.post('/crm-api/auth/player/verify-otp/', {'phone': '263771234567', 'code': code}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.json()); self.assertIn('refresh', r.json())

    def test_wrong_code_rejected_and_locked_after_max(self):
        self._request_and_capture_code()
        for _ in range(5):
            r = self.client.post('/crm-api/auth/player/verify-otp/', {'phone': '263771234567', 'code': '000000'}, format='json')
            self.assertEqual(r.status_code, 400)
        # Even the correct code is now locked out (attempts exhausted -> consumed).
        otp = PlayerLoginOTP.objects.filter(contact=self.contact).order_by('-created_at').first()
        self.assertTrue(otp.consumed)

    def test_unknown_number_is_generic_and_creates_nothing(self):
        with mock.patch('meta_integration.utils.send_whatsapp_message') as send:
            r = self.client.post('/crm-api/auth/player/request-otp/', {'phone': '263779999999'}, format='json')
        self.assertEqual(r.status_code, 200)          # generic, no enumeration
        send.assert_not_called()
        self.assertEqual(PlayerLoginOTP.objects.count(), 0)

    def test_resend_cooldown(self):
        code1, _ = self._request_and_capture_code()
        # Immediate second request is suppressed by the cooldown (no new OTP row).
        with mock.patch('meta_integration.utils.send_whatsapp_message') as send:
            self.client.post('/crm-api/auth/player/request-otp/', {'phone': '263771234567'}, format='json')
            send.assert_not_called()
        self.assertEqual(PlayerLoginOTP.objects.filter(contact=self.contact).count(), 1)
