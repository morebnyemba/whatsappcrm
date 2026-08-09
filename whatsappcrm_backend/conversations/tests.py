from django.test import TestCase, override_settings

from .models import Contact, ContactSession


class ContactSessionTimeoutTests(TestCase):
    """ContactSession.session_timeout_minutes previously read the undefined
    setting SESSION_TIMEOUT_MINUTES, silently falling back to the class
    default of 30 minutes regardless of configuration — login sessions never
    actually respected the shorter timeout operators expected."""

    def setUp(self):
        self.contact = Contact.objects.create(whatsapp_id='263771234567')
        self.session = ContactSession.objects.create(contact=self.contact)

    @override_settings(SESSION_TIMEOUT_MINUTES=5)
    def test_reads_configured_session_timeout_minutes(self):
        self.assertEqual(self.session.session_timeout_minutes, 5)

    def test_class_default_fallback_is_five_minutes(self):
        # If SESSION_TIMEOUT_MINUTES is ever absent from settings entirely,
        # the class-level fallback should match the same 5-minute policy.
        self.assertEqual(ContactSession.DEFAULT_SESSION_TIMEOUT_MINUTES, 5)

    def test_start_sets_expiry_using_configured_timeout(self):
        from django.utils import timezone
        with override_settings(SESSION_TIMEOUT_MINUTES=5):
            before = timezone.now()
            self.session.start()
            self.session.refresh_from_db()
            delta = self.session.expires_at - before
            self.assertLess(delta.total_seconds(), 5 * 60 + 5)
            self.assertGreater(delta.total_seconds(), 5 * 60 - 5)
