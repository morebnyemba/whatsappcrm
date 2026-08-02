# whatsappcrm_backend/customer_data/test_permissions.py
"""
Surface separation: player (non-staff) tokens must not reach CRM/admin APIs,
but must reach their own betting data. Staff reach the CRM APIs.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

CRM_URLS = [
    '/crm-api/flows/flows/',
    '/crm-api/conversations/contacts/',
    '/crm-api/conversations/messages/',
    '/crm-api/customer-data/profiles/',
]
PLAYER_URLS = [
    '/crm-api/football/fixtures/',
    '/crm-api/football/wallet/me/',
    '/crm-api/football/tickets/',
    '/crm-api/football/tickets/summary/',
]


class SurfacePermissionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staffuser', password='x', is_staff=True)
        self.player = User.objects.create_user('player1', password='x')  # non-staff

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_player_is_blocked_from_crm(self):
        c = self._client(self.player)
        for url in CRM_URLS:
            self.assertEqual(c.get(url).status_code, 403, f"player should be 403 on {url}")

    def test_player_can_reach_own_betting_data(self):
        c = self._client(self.player)
        for url in PLAYER_URLS:
            self.assertEqual(c.get(url).status_code, 200, f"player should be 200 on {url}")

    def test_staff_can_reach_crm(self):
        c = self._client(self.staff)
        for url in CRM_URLS:
            self.assertNotEqual(c.get(url).status_code, 403, f"staff should not be 403 on {url}")

    def test_anonymous_is_unauthorized(self):
        c = APIClient()
        self.assertIn(c.get('/crm-api/flows/flows/').status_code, (401, 403))
        self.assertIn(c.get('/crm-api/football/fixtures/').status_code, (401, 403))
