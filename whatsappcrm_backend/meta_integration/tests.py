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
            app_secret=self.test_app_secret,
            access_token="test_token",
            phone_number_id="987654321",
            waba_id="111222333",
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

    @patch('meta_integration.views.get_meta_config_by_phone_number_id')
    def test_webhook_post_with_valid_signature(self, mock_get_config):
        """Test complete webhook POST with valid signature"""
        mock_get_config.return_value = self.meta_config
        
        test_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "111222333",
                "changes": [{
                    "value": {
                        "metadata": {
                            "phone_number_id": "987654321"
                        }
                    },
                    "field": "messages"
                }]
            }]
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

    @patch('meta_integration.views.get_meta_config_by_phone_number_id')
    def test_webhook_post_with_invalid_signature(self, mock_get_config):
        """Test complete webhook POST with invalid signature"""
        mock_get_config.return_value = self.meta_config
        
        test_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "111222333",
                "changes": [{
                    "value": {
                        "metadata": {
                            "phone_number_id": "987654321"
                        }
                    },
                    "field": "messages"
                }]
            }]
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


class MultiConfigRoutingTestCase(TestCase):
    """Test cases for multiple configuration routing"""

    def setUp(self):
        # Create multiple test configs
        self.config_1 = MetaAppConfig.objects.create(
            name="Config 1",
            app_secret="secret_1",
            access_token="token_1",
            phone_number_id="111111111",
            waba_id="waba_1",
            verify_token="verify_1",
            is_active=True
        )
        self.config_2 = MetaAppConfig.objects.create(
            name="Config 2",
            app_secret="secret_2",
            access_token="token_2",
            phone_number_id="222222222",
            waba_id="waba_2",
            verify_token="verify_2",
            is_active=True
        )
        self.config_3 = MetaAppConfig.objects.create(
            name="Config 3 (Inactive)",
            app_secret="secret_3",
            access_token="token_3",
            phone_number_id="333333333",
            waba_id="waba_3",
            verify_token="verify_3",
            is_active=False
        )

    def test_multiple_active_configs_allowed(self):
        """Test that multiple configs can be active simultaneously"""
        active_configs = MetaAppConfig.objects.filter(is_active=True)
        self.assertEqual(active_configs.count(), 2)

    def test_get_config_by_phone_number_id_exact_match(self):
        """Test getting config by phone number ID with exact match"""
        config = MetaAppConfig.objects.get_config_by_phone_number_id("111111111")
        self.assertEqual(config, self.config_1)
        
        config = MetaAppConfig.objects.get_config_by_phone_number_id("222222222")
        self.assertEqual(config, self.config_2)

    def test_get_config_by_phone_number_id_fallback(self):
        """Test getting config falls back to any active config if no match"""
        config = MetaAppConfig.objects.get_config_by_phone_number_id("nonexistent")
        self.assertIsNotNone(config)
        self.assertTrue(config.is_active)

    def test_get_config_by_phone_number_id_inactive(self):
        """Test that inactive config can still be found by phone number ID"""
        config = MetaAppConfig.objects.get_config_by_phone_number_id("333333333")
        self.assertEqual(config, self.config_3)

    def test_get_all_active_configs(self):
        """Test getting all active configurations"""
        active_configs = MetaAppConfig.objects.get_all_active_configs()
        self.assertEqual(active_configs.count(), 2)
        self.assertIn(self.config_1, active_configs)
        self.assertIn(self.config_2, active_configs)
        self.assertNotIn(self.config_3, active_configs)

    def test_get_active_config_returns_first(self):
        """Test that get_active_config returns the first active config"""
        config = MetaAppConfig.objects.get_active_config()
        self.assertIsNotNone(config)
        self.assertTrue(config.is_active)
