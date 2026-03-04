# whatsappcrm_backend/meta_integration/flow_crypto.py

"""
Encryption/decryption utilities for WhatsApp Flows data exchange.

WhatsApp Flows uses end-to-end encryption for data exchange between
Meta's servers and the business endpoint. This module implements the
required RSA + AES-GCM cryptographic operations.

Reference:
    https://developers.facebook.com/docs/whatsapp/flows/guides/implementingyourflowendpoint
"""

import base64
import json
import logging
import os

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


def generate_rsa_key_pair():
    """
    Generate a 2048-bit RSA key pair for WhatsApp Flows encryption.

    Returns:
        tuple: (private_key_pem: str, public_key_pem: str)
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode('utf-8')

    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode('utf-8')

    return private_key_pem, public_key_pem


def decrypt_flow_request(encrypted_flow_data_b64, encrypted_aes_key_b64,
                         initial_vector_b64, private_key_pem):
    """
    Decrypt an incoming WhatsApp Flows data exchange request.

    Args:
        encrypted_flow_data_b64: Base64-encoded AES-GCM encrypted flow data (with tag appended).
        encrypted_aes_key_b64: Base64-encoded RSA-OAEP encrypted AES key.
        initial_vector_b64: Base64-encoded 12-byte IV for AES-GCM.
        private_key_pem: PEM-encoded RSA private key string.

    Returns:
        tuple: (decrypted_data: dict, aes_key: bytes, iv: bytes)
    """
    flow_data = base64.b64decode(encrypted_flow_data_b64)
    iv = base64.b64decode(initial_vector_b64)
    encrypted_aes_key = base64.b64decode(encrypted_aes_key_b64)

    private_key = serialization.load_pem_private_key(
        data=private_key_pem.encode('utf-8'),
        password=None,
    )

    aes_key = private_key.decrypt(
        encrypted_aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    # Last 16 bytes of encrypted flow data is the GCM authentication tag
    encrypted_flow_data_body = flow_data[:-16]
    encrypted_flow_data_tag = flow_data[-16:]

    decryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(iv, encrypted_flow_data_tag),
    ).decryptor()

    decrypted_data_bytes = decryptor.update(encrypted_flow_data_body) + decryptor.finalize()
    decrypted_data = json.loads(decrypted_data_bytes.decode('utf-8'))

    return decrypted_data, aes_key, iv


def encrypt_flow_response(response_data, aes_key, iv):
    """
    Encrypt an outgoing WhatsApp Flows data exchange response.

    Args:
        response_data: Dictionary to encrypt and send back.
        aes_key: The AES key obtained from decrypting the request.
        iv: The IV obtained from decrypting the request.

    Returns:
        str: Base64-encoded encrypted response (flipped_iv + ciphertext + tag).
    """
    # Flip the IV bytes (bitwise NOT)
    flipped_iv = bytearray(byte ^ 0xFF for byte in iv)

    encryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(flipped_iv),
    ).encryptor()

    encrypted = (
        encryptor.update(json.dumps(response_data).encode('utf-8'))
        + encryptor.finalize()
        + encryptor.tag
    )

    return base64.b64encode(encrypted).decode('utf-8')
