import json
import hmac
import hashlib
import base64
import os
from django.test import TestCase, RequestFactory
from django.conf import settings
from unittest.mock import patch, MagicMock

from .views import MetaWebhookAPIView, WhatsAppFlowEndpointView
from .models import MetaAppConfig
from .flow_crypto import (
    generate_rsa_key_pair,
    decrypt_flow_request,
    encrypt_flow_response,
)


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


class FlowCryptoTestCase(TestCase):
    """Test cases for WhatsApp Flows encryption/decryption utilities."""

    def test_generate_rsa_key_pair(self):
        """Test RSA key pair generation produces valid PEM keys."""
        private_pem, public_pem = generate_rsa_key_pair()
        self.assertIn('-----BEGIN PRIVATE KEY-----', private_pem)
        self.assertIn('-----END PRIVATE KEY-----', private_pem)
        self.assertIn('-----BEGIN PUBLIC KEY-----', public_pem)
        self.assertIn('-----END PUBLIC KEY-----', public_pem)

    def test_decrypt_flow_request(self):
        """Test decryption of a simulated encrypted flow request."""
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        private_pem, public_pem = generate_rsa_key_pair()

        # Simulate Meta encrypting a request
        pub_key = serialization.load_pem_public_key(public_pem.encode('utf-8'))
        test_payload = {"action": "INIT", "flow_token": "test_token_123"}
        payload_bytes = json.dumps(test_payload).encode('utf-8')

        aes_key = os.urandom(16)
        iv = os.urandom(12)

        encrypted_aes_key = pub_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(iv)).encryptor()
        ciphertext = encryptor.update(payload_bytes) + encryptor.finalize()
        encrypted_flow_data = ciphertext + encryptor.tag

        # Decrypt using our function
        decrypted, dec_aes_key, dec_iv = decrypt_flow_request(
            base64.b64encode(encrypted_flow_data).decode('utf-8'),
            base64.b64encode(encrypted_aes_key).decode('utf-8'),
            base64.b64encode(iv).decode('utf-8'),
            private_pem,
        )

        self.assertEqual(decrypted, test_payload)
        self.assertEqual(dec_aes_key, aes_key)
        self.assertEqual(dec_iv, iv)

    def test_encrypt_flow_response(self):
        """Test encryption of a flow response and verify it can be decrypted."""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        aes_key = os.urandom(16)
        iv = os.urandom(12)
        response_data = {"screen": "LOGIN", "data": {"error_message": ""}}

        encrypted = encrypt_flow_response(response_data, aes_key, iv)

        # Verify by decrypting with flipped IV
        flipped_iv = bytearray(byte ^ 0xFF for byte in iv)
        enc_bytes = base64.b64decode(encrypted)
        resp_ciphertext = enc_bytes[:-16]
        resp_tag = enc_bytes[-16:]
        decryptor = Cipher(
            algorithms.AES(aes_key), modes.GCM(flipped_iv, resp_tag)
        ).decryptor()
        resp_bytes = decryptor.update(resp_ciphertext) + decryptor.finalize()
        decrypted = json.loads(resp_bytes.decode('utf-8'))

        self.assertEqual(decrypted, response_data)

    def test_roundtrip_encrypt_decrypt(self):
        """Test full roundtrip: generate keys, encrypt request, decrypt, encrypt response."""
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        private_pem, public_pem = generate_rsa_key_pair()
        pub_key = serialization.load_pem_public_key(public_pem.encode('utf-8'))

        # Request payload
        request_payload = {
            "action": "data_exchange",
            "screen": "LOGIN",
            "data": {"username": "testuser", "password": "testpass"},
            "flow_token": "wa_id_123",
        }

        # Encrypt request (simulate Meta)
        aes_key = os.urandom(16)
        iv = os.urandom(12)
        encrypted_aes_key = pub_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(iv)).encryptor()
        payload_bytes = json.dumps(request_payload).encode('utf-8')
        ciphertext = encryptor.update(payload_bytes) + encryptor.finalize()
        encrypted_flow_data = ciphertext + encryptor.tag

        # Decrypt request (our endpoint)
        decrypted, dec_aes_key, dec_iv = decrypt_flow_request(
            base64.b64encode(encrypted_flow_data).decode('utf-8'),
            base64.b64encode(encrypted_aes_key).decode('utf-8'),
            base64.b64encode(iv).decode('utf-8'),
            private_pem,
        )
        self.assertEqual(decrypted, request_payload)

        # Encrypt response (our endpoint)
        response_payload = {"screen": "COMPLETE", "data": {"extension_message_response": {}}}
        encrypted_response = encrypt_flow_response(response_payload, dec_aes_key, dec_iv)

        # Decrypt response (simulate Meta)
        flipped_iv = bytearray(byte ^ 0xFF for byte in dec_iv)
        enc_bytes = base64.b64decode(encrypted_response)
        resp_ct = enc_bytes[:-16]
        resp_tag = enc_bytes[-16:]
        decryptor = Cipher(
            algorithms.AES(dec_aes_key), modes.GCM(flipped_iv, resp_tag)
        ).decryptor()
        resp = json.loads(
            (decryptor.update(resp_ct) + decryptor.finalize()).decode('utf-8')
        )
        self.assertEqual(resp, response_payload)


class WhatsAppFlowEndpointTestCase(TestCase):
    """Test cases for the WhatsApp Flow endpoint view."""

    def setUp(self):
        self.factory = RequestFactory()
        self.private_pem, self.public_pem = generate_rsa_key_pair()
        self.config = MetaAppConfig.objects.create(
            name="Flow Test Config",
            access_token="test_token",
            phone_number_id="555555555",
            waba_id="waba_test",
            verify_token="verify_test",
            is_active=True,
            flow_private_key_pem=self.private_pem,
        )

    def _encrypt_payload(self, payload):
        """Helper to encrypt a payload as Meta would."""
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        pub_key = serialization.load_pem_public_key(self.public_pem.encode('utf-8'))
        aes_key = os.urandom(16)
        iv = os.urandom(12)

        encrypted_aes_key = pub_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(iv)).encryptor()
        payload_bytes = json.dumps(payload).encode('utf-8')
        ciphertext = encryptor.update(payload_bytes) + encryptor.finalize()
        encrypted_flow_data = ciphertext + encryptor.tag

        return {
            "encrypted_flow_data": base64.b64encode(encrypted_flow_data).decode('utf-8'),
            "encrypted_aes_key": base64.b64encode(encrypted_aes_key).decode('utf-8'),
            "initial_vector": base64.b64encode(iv).decode('utf-8'),
        }, aes_key, iv

    def _decrypt_response(self, response_text, aes_key, iv):
        """Helper to decrypt a response from the endpoint."""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        flipped_iv = bytearray(byte ^ 0xFF for byte in iv)
        enc_bytes = base64.b64decode(response_text)
        ct = enc_bytes[:-16]
        tag = enc_bytes[-16:]
        decryptor = Cipher(
            algorithms.AES(aes_key), modes.GCM(flipped_iv, tag)
        ).decryptor()
        return json.loads(
            (decryptor.update(ct) + decryptor.finalize()).decode('utf-8')
        )

    def test_encrypted_ping(self):
        """Test encrypted ping request returns active status."""
        payload = {"action": "ping"}
        encrypted_body, aes_key, iv = self._encrypt_payload(payload)

        request = self.factory.post(
            '/flow-endpoint/',
            data=json.dumps(encrypted_body).encode('utf-8'),
            content_type='application/json',
        )

        view = WhatsAppFlowEndpointView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 200)
        decrypted = self._decrypt_response(response.content.decode(), aes_key, iv)
        self.assertEqual(decrypted, {"data": {"status": "active"}})

    def test_encrypted_init_default_login(self):
        """Test encrypted INIT returns login screen by default."""
        payload = {"action": "INIT", "flow_token": "wa_test"}
        encrypted_body, aes_key, iv = self._encrypt_payload(payload)

        request = self.factory.post(
            '/flow-endpoint/',
            data=json.dumps(encrypted_body).encode('utf-8'),
            content_type='application/json',
        )

        view = WhatsAppFlowEndpointView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 200)
        decrypted = self._decrypt_response(response.content.decode(), aes_key, iv)
        self.assertEqual(decrypted["screen"], "LOGIN")

    def test_plaintext_ping_still_works(self):
        """Test that plaintext (unencrypted) requests still work for draft flows."""
        payload = {"action": "ping"}
        request = self.factory.post(
            '/flow-endpoint/',
            data=json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )

        view = WhatsAppFlowEndpointView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data, {"data": {"status": "active"}})

    def test_plaintext_init_still_works(self):
        """Test that plaintext INIT requests still work."""
        payload = {"action": "INIT", "flow_token": "test"}
        request = self.factory.post(
            '/flow-endpoint/',
            data=json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )

        view = WhatsAppFlowEndpointView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["screen"], "LOGIN")
