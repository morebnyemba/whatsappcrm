import json
import hmac
import hashlib
from django.test import TestCase, RequestFactory
from django.conf import settings
from unittest.mock import patch, MagicMock

from .views import MetaWebhookAPIView
from .models import MetaAppConfig


class WebhookSignatureVerificationTestCase(TestCase):
    """Test cases for webhook signature verification"""

    def setUp(self):
        self.factory = RequestFactory()
        self.view = MetaWebhookAPIView()
        self.test_app_secret = "test_app_secret_12345"
        
        # Create a test MetaAppConfig
        self.meta_config = MetaAppConfig.objects.create(
            name="Test Config",
            app_id="123456789",
            app_secret="test_secret",
            access_token="test_token",
            phone_number_id="987654321",
            business_account_id="111222333",
            verify_token="test_verify_token",
            is_active=True
        )

    def _generate_signature(self, body_bytes, secret):
        """Helper to generate a valid signature"""
        return 'sha256=' + hmac.new(
            secret.encode('utf-8'),
            body_bytes,
            hashlib.sha256
        ).hexdigest()

    def test_signature_verification_success(self):
        """Test that valid signature passes verification"""
        test_payload = {"test": "data"}
        body_bytes = json.dumps(test_payload).encode('utf-8')
        valid_signature = self._generate_signature(body_bytes, self.test_app_secret)
        
        result = self.view._verify_signature(body_bytes, valid_signature, self.test_app_secret)
        self.assertTrue(result)

    def test_signature_verification_failure_wrong_secret(self):
        """Test that signature fails with wrong secret"""
        test_payload = {"test": "data"}
        body_bytes = json.dumps(test_payload).encode('utf-8')
        signature_with_wrong_secret = self._generate_signature(body_bytes, "wrong_secret")
        
        result = self.view._verify_signature(body_bytes, signature_with_wrong_secret, self.test_app_secret)
        self.assertFalse(result)

    def test_signature_verification_failure_modified_body(self):
        """Test that signature fails when body is modified"""
        test_payload = {"test": "data"}
        body_bytes = json.dumps(test_payload).encode('utf-8')
        valid_signature = self._generate_signature(body_bytes, self.test_app_secret)
        
        # Modify the body
        modified_body = json.dumps({"test": "modified_data"}).encode('utf-8')
        
        result = self.view._verify_signature(modified_body, valid_signature, self.test_app_secret)
        self.assertFalse(result)

    def test_signature_verification_missing_signature(self):
        """Test that missing signature fails verification"""
        body_bytes = b'{"test": "data"}'
        result = self.view._verify_signature(body_bytes, None, self.test_app_secret)
        self.assertFalse(result)

    def test_signature_verification_invalid_format(self):
        """Test that invalid signature format fails"""
        body_bytes = b'{"test": "data"}'
        invalid_signature = "invalid_format_signature"
        
        result = self.view._verify_signature(body_bytes, invalid_signature, self.test_app_secret)
        self.assertFalse(result)

    def test_signature_verification_with_whitespace_in_secret(self):
        """Test that whitespace is handled in app secret"""
        test_payload = {"test": "data"}
        body_bytes = json.dumps(test_payload).encode('utf-8')
        
        # Generate signature with secret without whitespace
        valid_signature = self._generate_signature(body_bytes, self.test_app_secret)
        
        # Verify with secret that has whitespace - should be stripped in post() method
        secret_with_whitespace = f"  {self.test_app_secret}  "
        
        result = self.view._verify_signature(body_bytes, valid_signature, secret_with_whitespace.strip())
        self.assertTrue(result)

    def test_signature_verification_empty_body(self):
        """Test signature verification with empty body"""
        body_bytes = b''
        valid_signature = self._generate_signature(body_bytes, self.test_app_secret)
        
        result = self.view._verify_signature(body_bytes, valid_signature, self.test_app_secret)
        self.assertTrue(result)

    @patch('meta_integration.views.get_active_meta_config')
    @patch.object(settings, 'WHATSAPP_APP_SECRET', 'test_app_secret_12345')
    def test_webhook_post_with_valid_signature(self, mock_get_config):
        """Test complete webhook POST with valid signature"""
        mock_get_config.return_value = self.meta_config
        
        test_payload = {
            "object": "whatsapp_business_account",
            "entry": []
        }
        body_bytes = json.dumps(test_payload).encode('utf-8')
        signature = self._generate_signature(body_bytes, self.test_app_secret)
        
        request = self.factory.post(
            '/webhook/',
            data=body_bytes,
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=signature
        )
        
        view = MetaWebhookAPIView.as_view()
        response = view(request)
        
        # Should return 200, not 403
        self.assertEqual(response.status_code, 200)

    @patch('meta_integration.views.get_active_meta_config')
    @patch.object(settings, 'WHATSAPP_APP_SECRET', 'test_app_secret_12345')
    def test_webhook_post_with_invalid_signature(self, mock_get_config):
        """Test complete webhook POST with invalid signature"""
        mock_get_config.return_value = self.meta_config
        
        test_payload = {
            "object": "whatsapp_business_account",
            "entry": []
        }
        body_bytes = json.dumps(test_payload).encode('utf-8')
        # Use wrong secret to generate signature
        signature = self._generate_signature(body_bytes, "wrong_secret")
        
        request = self.factory.post(
            '/webhook/',
            data=body_bytes,
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=signature
        )
        
        view = MetaWebhookAPIView.as_view()
        response = view(request)
        
        # Should return 403 for invalid signature
        self.assertEqual(response.status_code, 403)
