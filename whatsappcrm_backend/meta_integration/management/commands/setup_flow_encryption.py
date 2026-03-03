import logging

import requests
from django.core.management.base import BaseCommand

from meta_integration.flow_crypto import generate_rsa_key_pair
from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Generate RSA key pair for WhatsApp Flows encryption and upload "
        "the public key to Meta for each active MetaAppConfig (or a specific one)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--config-id',
            type=int,
            help='Target a specific MetaAppConfig by ID. If omitted, all active configs are processed.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='Regenerate and re-upload keys even if a private key already exists.',
        )

    def handle(self, *args, **options):
        config_id = options['config_id']
        force = options['force']

        if config_id:
            try:
                configs = [MetaAppConfig.objects.get(pk=config_id)]
            except MetaAppConfig.DoesNotExist:
                self.stderr.write(self.style.ERROR(
                    f"MetaAppConfig with ID {config_id} not found."
                ))
                return
        else:
            configs = list(MetaAppConfig.objects.get_all_active_configs())
            if not configs:
                self.stderr.write(self.style.ERROR("No active MetaAppConfigs found."))
                return

        for config in configs:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n=== {config.name} (phone_number_id: {config.phone_number_id}) ==="
            ))

            if config.flow_private_key_pem and not force:
                self.stdout.write(
                    "  Private key already exists. Use --force to regenerate."
                )
                # Still upload the existing public key
                self._upload_public_key(config)
                continue

            # Generate new key pair
            self.stdout.write("  Generating RSA key pair...")
            private_key_pem, public_key_pem = generate_rsa_key_pair()

            config.flow_private_key_pem = private_key_pem
            config.save(update_fields=['flow_private_key_pem'])
            self.stdout.write(self.style.SUCCESS("  ✅ Private key saved to database."))

            # Upload public key to Meta
            self._upload_public_key(config, public_key_pem)

    def _upload_public_key(self, config, public_key_pem=None):
        """Upload the public key to Meta's API for this phone number."""
        if public_key_pem is None:
            # Derive public key from stored private key
            if not config.flow_private_key_pem:
                self.stderr.write(self.style.ERROR(
                    "  ❌ No private key stored. Cannot derive public key."
                ))
                return
            from cryptography.hazmat.primitives import serialization as ser
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            private_key = load_pem_private_key(
                config.flow_private_key_pem.encode('utf-8'),
                password=None,
            )
            public_key_pem = private_key.public_key().public_bytes(
                encoding=ser.Encoding.PEM,
                format=ser.PublicFormat.SubjectPublicKeyInfo,
            ).decode('utf-8')

        url = (
            f"https://graph.facebook.com/{config.api_version}"
            f"/{config.phone_number_id}/whatsapp_business_encryption"
        )
        headers = {
            "Authorization": f"Bearer {config.access_token}",
        }

        self.stdout.write("  Uploading public key to Meta...")
        try:
            response = requests.post(
                url,
                headers=headers,
                data={"business_public_key": public_key_pem},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            if result.get('success'):
                self.stdout.write(self.style.SUCCESS(
                    "  ✅ Public key uploaded to Meta successfully."
                ))
            else:
                self.stderr.write(self.style.ERROR(
                    f"  ❌ Meta API response: {result}"
                ))
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_msg += f" - Details: {e.response.json()}"
                except (ValueError, Exception):
                    error_msg += f" - Response: {e.response.text}"
            self.stderr.write(self.style.ERROR(
                f"  ❌ Failed to upload public key: {error_msg}"
            ))
