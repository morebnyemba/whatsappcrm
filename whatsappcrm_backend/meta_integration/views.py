# whatsappcrm_backend/meta_integration/views.py

import json
import logging
import hashlib # For signature verification
import hmac    # For signature verification

from django.http import HttpResponse, JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from datetime import datetime
from django.db import transaction
from django.conf import settings # To get APP_SECRET for signature verification

from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action

from .models import MetaAppConfig, WebhookEventLog
from .serializers import (
    MetaAppConfigSerializer,
    WebhookEventLogSerializer,
    WebhookEventLogListSerializer
)
from conversations.models import Contact, Message
# from flows.services import process_message_for_flow # Import moved into handle_message
from .tasks import send_whatsapp_message_task, send_read_receipt_task

# Use a logger specific to this app
logger = logging.getLogger('meta_integration')

# Sensitive header names that should be filtered from logs
SENSITIVE_HEADER_NAMES = ['authorization', 'cookie', 'x-access-token', 'x-api-key']

def get_active_meta_config():
    """Helper function to get the first active MetaAppConfig."""
    try:
        return MetaAppConfig.objects.get_active_config()
    except MetaAppConfig.DoesNotExist:
        logger.critical("CRITICAL: No active Meta App Configuration found. Webhook and message sending will fail.")
        return None
    except Exception as e:
        logger.critical(f"CRITICAL: Error retrieving active MetaAppConfig: {e}", exc_info=True)
        return None


def get_meta_config_by_phone_number_id(phone_number_id: str):
    """
    Helper function to get MetaAppConfig by phone_number_id.
    Falls back to any active config if no match is found.
    """
    try:
        return MetaAppConfig.objects.get_config_by_phone_number_id(phone_number_id)
    except Exception as e:
        logger.error(f"Error retrieving MetaAppConfig by phone_number_id {phone_number_id}: {e}", exc_info=True)
        return None

@method_decorator(csrf_exempt, name='dispatch')
class MetaWebhookAPIView(View):
    """
    Handles webhook verification and incoming event notifications from Meta.
    """

    def _verify_signature(self, request_body_bytes, x_hub_signature_256, app_secret_key):
        """
        Verifies the X-Hub-Signature-256 header using the provided app_secret_key.
        
        The app_secret_key should be the "App Secret" from your Meta App Dashboard
        (Settings > Basic > App Secret), NOT the WhatsApp Business API access token.
        
        Meta calculates the signature as: HMAC-SHA256(app_secret, request_body)
        and sends it in the X-Hub-Signature-256 header as: sha256=<hex_digest>
        """
        if not x_hub_signature_256:
            logger.warning("Webhook signature (X-Hub-Signature-256) missing.")
            return False
        if not app_secret_key:
            logger.error("App Secret not configured for signature verification. Verification skipped (INSECURE).")
            return True # Or False, depending on strictness policy

        if not x_hub_signature_256.startswith('sha256='):
            logger.warning("Webhook signature format is invalid (must start with 'sha256=').")
            return False

        expected_signature_hex = x_hub_signature_256.split('sha256=', 1)[1]
        
        byte_key = app_secret_key.encode('utf-8')
        hashed = hmac.new(byte_key, request_body_bytes, hashlib.sha256)
        calculated_signature_hex = hashed.hexdigest()

        if not hmac.compare_digest(calculated_signature_hex, expected_signature_hex):
            logger.warning(f"Webhook signature mismatch. Expected: {expected_signature_hex}, Calculated: {calculated_signature_hex}")
            logger.debug(f"Request body size: {len(request_body_bytes)} bytes")
            logger.debug(f"App secret length: {len(app_secret_key)} chars")
            return False
        
        logger.debug("Webhook signature verified successfully.")
        return True

    def get(self, request, *args, **kwargs):
        logger.debug(f"Webhook GET request received. Query params: {request.GET}")
        active_config = get_active_meta_config()
        if not active_config:
            logger.error("WEBHOOK GET: Verification failed: No active MetaAppConfig.")
            return HttpResponse("Server configuration error: Meta App settings not found.", status=500)
        
        verify_token_from_db = active_config.verify_token
        mode = request.GET.get('hub.mode')
        token_from_request = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')

        logger.info(f"Webhook verification attempt for config '{active_config.name}': mode='{mode}', token_matches='{token_from_request == verify_token_from_db}', challenge='{challenge}'")

        if mode and token_from_request:
            if mode == 'subscribe' and token_from_request == verify_token_from_db:
                logger.info(f"Webhook verified for config '{active_config.name}'. Responding with challenge.")
                return HttpResponse(challenge, status=200)
            else:
                logger.warning(f"Webhook verification failed for config '{active_config.name}'. Mode: {mode}, Received Token: {token_from_request}, Expected: {verify_token_from_db}")
                return HttpResponse("Verification token mismatch", status=403)
        else:
            logger.error("Missing 'hub.mode' or 'hub.verify_token' in GET request.")
            return HttpResponse("Bad request: Missing required verification parameters.", status=400)


    def post(self, request, *args, **kwargs):
        # For multi-config support, we need to first parse the payload to get phone_number_id,
        # then find the matching config for signature verification.
        # If no specific config is found, try all active configs.
        
        raw_payload_str = request.body.decode('utf-8', errors='ignore')
        
        # Parse payload first to extract phone_number_id for config lookup
        try:
            payload = json.loads(raw_payload_str)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook: {e}. Body: {raw_payload_str[:500]}...")
            return HttpResponse("Invalid JSON payload", status=400)
        
        # Extract phone_number_id from payload for config routing
        phone_number_id_from_payload = None
        try:
            phone_number_id_from_payload = payload.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('metadata', {}).get('phone_number_id')
        except (IndexError, AttributeError):
            pass
        
        # Try to find the matching config by phone_number_id
        active_config = get_meta_config_by_phone_number_id(phone_number_id_from_payload)
        
        if not active_config:
            logger.error("WEBHOOK POST: Processing failed - No active MetaAppConfig found for this phone_number_id or any fallback. Event ignored.")
            return HttpResponse("EVENT_RECEIVED_BUT_UNCONFIGURED", status=200)

        # Get app_secret from the database config instead of settings
        # Use getattr to safely access app_secret field, returning None if the migration hasn't been applied yet
        app_secret = getattr(active_config, 'app_secret', None)
        
        # Strip whitespace from app secret if present
        if app_secret:
            app_secret = app_secret.strip()

        if not app_secret:
             logger.warning(
                f"App Secret is not configured for MetaAppConfig '{active_config.name}'. "
                f"Webhook signature verification will be skipped. "
                f"THIS IS A SECURITY RISK. Please add the app_secret in the MetaAppConfig admin."
            )
        else:
            signature = request.headers.get('X-Hub-Signature-256')
            # Filter sensitive headers before logging
            # X-Hub-Signature-256 is safe to log as it's meant for verification
            safe_headers = {
                k: v for k, v in request.headers.items() 
                if k.lower() not in SENSITIVE_HEADER_NAMES
            }
            logger.debug(f"Webhook headers (filtered): {safe_headers}")
            if not self._verify_signature(request.body, signature, app_secret):
                logger.error(f"Webhook signature verification FAILED for config '{active_config.name}'. Discarding request.")
                # Log header keys (not values) for debugging
                header_keys = list(request.headers.keys())
                WebhookEventLog.objects.create(
                    app_config=active_config, event_type='security',
                    payload={'error': 'Signature verification failed', 'header_keys': header_keys},
                    processing_status='rejected', processing_notes='Invalid X-Hub-Signature-256'
                )
                return HttpResponse("Invalid signature", status=403)

        logger.info(f"Webhook POST request received (Signature OK if secret configured). Body size: {len(raw_payload_str)}. Config: {active_config.name}, Phone Number ID: {phone_number_id_from_payload}")
        logger.debug(f"Raw webhook payload: {raw_payload_str}")

        base_log_defaults = {
            'app_config': active_config,
            'waba_id_received': payload.get('entry', [{}])[0].get('id'),
            'phone_number_id_received': payload.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('metadata', {}).get('phone_number_id'),
            'event_type': 'unknown',
            'payload_object_type': payload.get('object'),
            'processing_status': 'pending',
            'processing_notes': None
        }

        try:
            if payload.get("object") == "whatsapp_business_account":
                for entry_idx, entry in enumerate(payload.get("entry", [])):
                    waba_id = entry.get("id")
                    for change_idx, change in enumerate(entry.get("changes", [])):
                        value = change.get("value", {})
                        field = change.get("field")
                        metadata = value.get("metadata", {})
                        phone_id = metadata.get("phone_number_id")
                        logger.info(f"Processing entry[{entry_idx}].change[{change_idx}]: field='{field}', phone_id='{phone_id}'")
                        log_defaults_for_change = {**base_log_defaults, 'waba_id_received': waba_id, 'phone_number_id_received': phone_id}

                        if field == "messages":
                            if "messages" in value:
                                for msg_data in value["messages"]:
                                    wamid = msg_data.get("id")
                                    log_entry, _ = WebhookEventLog.objects.update_or_create(
                                        event_identifier=wamid, event_type='message',
                                        defaults={**log_defaults_for_change, 'payload': msg_data}
                                    )
                                    if log_entry.processing_status not in ['processed', 'ignored', 'error_final']:
                                        self.handle_message(msg_data, metadata, value, active_config, log_entry)
                                    else:
                                        logger.info(f"Skipping reprocessing for already handled message WAMID: {wamid}, Status: {log_entry.processing_status}")
                            elif "statuses" in value:
                                for status_data in value["statuses"]:
                                    wamid = status_data.get("id")
                                    log_entry, _ = WebhookEventLog.objects.update_or_create(
                                        event_identifier=wamid, event_type='message_status',
                                        defaults={**log_defaults_for_change, 'payload': status_data}
                                    )
                                    if log_entry.processing_status not in ['processed', 'ignored']:
                                        self.handle_status_update(status_data, metadata, active_config, log_entry)
                            elif "errors" in value:
                                for error_data in value["errors"]:
                                    log_entry = WebhookEventLog.objects.create(**log_defaults_for_change, payload=error_data, event_identifier=f"error_{error_data.get('code')}_{timezone.now().timestamp()}", event_type='error')
                                    self.handle_error_notification(error_data, metadata, active_config, log_entry) 
                            else:
                                logger.warning(f"Messages field '{field}' but no 'messages', 'statuses', or 'errors' key. Value: {value.keys()}")
                        
                        elif field == "message_template_status_update":
                            log_entry = WebhookEventLog.objects.create(**log_defaults_for_change, payload=value, event_type='template_status', event_identifier=value.get("message_template_id") or f"template_{value.get('message_template_name')}_{value.get('event')}")
                            self.handle_template_status_update(value, active_config, log_entry)
                        else: 
                            logger.warning(f"Unhandled change field '{field}'. Value: {value}")
                            WebhookEventLog.objects.create(**log_defaults_for_change, payload=value, event_type='unknown', processing_status='ignored', processing_notes=f"Unhandled field: {field}")
            else: 
                logger.warning(f"Unknown webhook object type: {payload.get('object')}")
                WebhookEventLog.objects.create(**base_log_defaults, payload=payload, event_type='unknown', processing_status='ignored', processing_notes=f"Unknown object: {payload.get('object')}")

            return HttpResponse("EVENT_RECEIVED", status=200)
        except Exception as e:
            logger.error(f"Error processing webhook structure/dispatching: {e}", exc_info=True)
            WebhookEventLog.objects.create(**base_log_defaults, payload=payload if 'payload' in locals() else {'raw_error': raw_payload_str}, processing_status='error', processing_notes=f"Unhandled exception: {str(e)}")
            return HttpResponse("Internal Server Error", status=500)


    def _save_log(self, log_entry: WebhookEventLog, status: str, notes: str = None):
        old_status = log_entry.processing_status
        log_entry.processing_status = status
        if notes:
            log_entry.processing_notes = f"{log_entry.processing_notes}\n{notes}" if log_entry.processing_notes else notes
        log_entry.processed_at = timezone.now()
        try:
            log_entry.save(update_fields=['processing_status', 'processing_notes', 'processed_at'])
            logger.debug(f"WebhookEventLog ID {log_entry.id} status from '{old_status}' to '{status}'.")
        except Exception as e:
            logger.error(f"Failed to save WebhookEventLog (ID: {log_entry.pk or 'New'}): {e}", exc_info=True)


    @transaction.atomic 
    def handle_message(self, message_data, metadata, value_obj, app_config, log_entry: WebhookEventLog):
        """
        Handles incoming WhatsApp messages.
        Creates Contact and Message objects, then queues flow processing asynchronously.
        """
        from conversations.services import get_or_create_contact_by_wa_id
        from flows.tasks import process_flow_for_message_task

        whatsapp_message_id = message_data.get("id")
        from_phone = message_data.get("from")
        message_type = message_data.get("type", "unknown")
        ts_str = message_data.get("timestamp")
        msg_ts = timezone.make_aware(datetime.fromtimestamp(int(ts_str))) if ts_str and ts_str.isdigit() else timezone.now()
        
        logger.info(f"Handling message WAMID: {whatsapp_message_id}, From: {from_phone}, Type: {message_type}") 
        
        # Extract contact profile name
        contact_profile_name = "Unknown"
        contact_wa_id_from_payload = from_phone
        if 'contacts' in value_obj and value_obj['contacts']:
            contact_payload = value_obj['contacts'][0]
            if isinstance(contact_payload, dict):
                contact_profile_name = contact_payload.get('profile', {}).get('name', "Unknown")
                contact_wa_id_from_payload = contact_payload.get('wa_id', from_phone)
        
        try:
            # Use the service to get or create contact, associating with the app_config
            contact, created = get_or_create_contact_by_wa_id(
                wa_id=contact_wa_id_from_payload,
                name=contact_profile_name,
                meta_app_config=app_config  # Associate contact with the config they messaged
            )
            
            if not contact:
                logger.error(f"Failed to create/get contact for {contact_wa_id_from_payload}")
                self._save_log(log_entry, 'error', f"Contact creation failed for {contact_wa_id_from_payload}")
                return
            
            # Update last_seen
            contact.last_seen = msg_ts
            contact.save(update_fields=['last_seen'])
            
            # Create or update message object
            incoming_msg_obj, msg_created = Message.objects.update_or_create(
                wamid=whatsapp_message_id,
                defaults={
                    'contact': contact,
                    'direction': 'in',
                    'message_type': message_type,
                    'content_payload': message_data,
                    'timestamp': msg_ts, 
                    'status': 'delivered',
                    'status_timestamp': msg_ts
                }
            )
            
            if not msg_created:
                logger.info(f"Incoming message WAMID {whatsapp_message_id} already exists. Updating timestamp. Processing will continue to check flow state.")
                incoming_msg_obj.timestamp = msg_ts
                incoming_msg_obj.content_payload = message_data
                incoming_msg_obj.save()
            else:
                logger.info(f"Saved incoming message (WAMID: {whatsapp_message_id}) as DB ID {incoming_msg_obj.id}")
            
            if log_entry and log_entry.pk:
                log_entry.message = incoming_msg_obj
                log_entry.processing_status = 'processing_queued'
                log_entry.save(update_fields=['message', 'processing_status'])
            
            # Queue flow processing asynchronously
            transaction.on_commit(
                lambda: process_flow_for_message_task.delay(incoming_msg_obj.id)
            )
            logger.info(f"Queued process_flow_for_message_task for message {incoming_msg_obj.id}")
            
            # Send read receipt asynchronously
            self._send_read_receipt(whatsapp_message_id, app_config)
            
        except Exception as e:
            logger.error(f"Error in handle_message for WAMID {whatsapp_message_id}: {e}", exc_info=True)
            self._save_log(log_entry, 'error', f"Handle msg error: {str(e)[:200]}")
    
    def _send_read_receipt(self, wamid: str, app_config: MetaAppConfig, show_typing_indicator: bool = False):
        """
        Dispatches a Celery task to send a read receipt for the given message ID.
        """
        if not wamid:
            logger.warning("Cannot send read receipt: Missing WAMID.")
            return
        
        if not app_config:
            logger.warning("Cannot send read receipt: Missing app_config.")
            return

        send_read_receipt_task.delay(
            wamid=wamid,
            config_id=app_config.id,
            show_typing_indicator=show_typing_indicator
        )
        logger.info(f"Dispatched read receipt task for WAMID {wamid} (Typing: {show_typing_indicator})")


    def handle_status_update(self, status_data, metadata, app_config, log_entry: WebhookEventLog):
        wamid = status_data.get("id"); status_value = status_data.get("status"); ts_str = status_data.get("timestamp")
        status_ts = timezone.make_aware(datetime.fromtimestamp(int(ts_str))) if ts_str and ts_str.isdigit() else timezone.now()
        if not log_entry.event_identifier: log_entry.event_identifier = wamid
        logger.info(f"Status Update: WAMID={wamid}, Status='{status_value}'")
        notes = [f"Status for WAMID {wamid} is {status_value}."]
        try:
            msg_to_update = Message.objects.filter(wamid=wamid, direction='out').first()
            if msg_to_update:
                msg_to_update.status = status_value; msg_to_update.status_timestamp = status_ts
                if 'conversation' in status_data and isinstance(status_data['conversation'], dict):
                    msg_to_update.conversation_id_from_meta = status_data['conversation'].get('id')
                if 'pricing' in status_data and isinstance(status_data['pricing'], dict):
                    msg_to_update.pricing_model_from_meta = status_data['pricing'].get('pricing_model')
                msg_to_update.save()
                notes.append("DB record updated.")
                self._save_log(log_entry, 'processed', " ".join(notes))
            else: self._save_log(log_entry, 'ignored', f"No matching outgoing msg for WAMID {wamid}.")
        except Exception as e: logger.error(f"Error updating status for WAMID {wamid}: {e}", exc_info=True); self._save_log(log_entry, 'error', str(e))

    def handle_error_notification(self, error_data, metadata, app_config, log_entry): 
        logger.error(f"Received error notification from Meta: {error_data}")
        self._save_log(log_entry, 'processed', f"Error notification logged: {error_data.get('title')}")

    def handle_template_status_update(self, template_data, app_config, log_entry): 
        logger.info(f"Received template status update: {template_data}")
        self._save_log(log_entry, 'processed', f"Template status update logged for: {template_data.get('message_template_name')}")

    def handle_referral(self, referral_data, contact_wa_id, app_config, log_entry): 
        logger.info(f"Received referral data for {contact_wa_id}: {referral_data}")
        self._save_log(log_entry, 'processed', "Referral data logged.")

    def handle_system_message(self, system_data, contact_wa_id, app_config, log_entry): 
        logger.info(f"Received system message for {contact_wa_id}: {system_data}")
        self._save_log(log_entry, 'processed', "System message logged.")

    def handle_flow_response(self, flow_response_data, contact_wa_id, app_config, log_entry): 
        """
        Handles WhatsApp UI Flow (NFM) responses by persisting them to the
        database and merging the data into the contact's active flow context.
        """
        from flows.whatsapp_flow_response_processor import WhatsAppFlowResponseProcessor
        from flows.models import WhatsAppFlow
        from conversations.services import get_or_create_contact_by_wa_id

        logger.info(f"Received Flow (NFM) response for {contact_wa_id}: {flow_response_data}")
        try:
            contact, _ = get_or_create_contact_by_wa_id(
                wa_id=contact_wa_id, name='Unknown', meta_app_config=app_config
            )
            if not contact:
                logger.error(f"Could not get/create contact for {contact_wa_id} in handle_flow_response")
                self._save_log(log_entry, 'error', f"Contact creation failed for {contact_wa_id}")
                return

            # Attempt to find the WhatsAppFlow matching this config
            whatsapp_flow = (
                WhatsAppFlow.objects
                .filter(meta_app_config=app_config, is_active=True)
                .order_by('-updated_at')
                .first()
            )
            if whatsapp_flow:
                result = WhatsAppFlowResponseProcessor.process_response(
                    whatsapp_flow=whatsapp_flow,
                    contact=contact,
                    response_data=flow_response_data,
                )
                notes = f"Flow response processed: {result}" if result else "Flow response processing returned None"
                self._save_log(log_entry, 'processed', notes)
            else:
                logger.warning(
                    f"No active WhatsAppFlow found for config '{app_config.name}'. "
                    f"Flow response for {contact_wa_id} logged but not persisted to WhatsAppFlowResponse."
                )
                self._save_log(log_entry, 'processed', "Flow (NFM) response logged; no matching WhatsAppFlow found.")
        except Exception as e:
            logger.error(f"Error in handle_flow_response for {contact_wa_id}: {e}", exc_info=True)
            self._save_log(log_entry, 'error', f"handle_flow_response error: {str(e)[:200]}")


@method_decorator(csrf_exempt, name='dispatch')
class WhatsAppFlowEndpointView(View):
    """
    Handles data exchange requests from WhatsApp UI Flows.
    WhatsApp calls this endpoint when a user interacts with a Flow screen.
    Currently supports the login/authentication flow.

    Meta sends encrypted requests containing:
        - encrypted_flow_data: AES-GCM encrypted payload (base64)
        - encrypted_aes_key: RSA-OAEP encrypted AES key (base64)
        - initial_vector: AES-GCM IV (base64)

    The decrypted payload contains:
        - action: "ping" | "INIT" | "data_exchange"
        - flow_token: unique token for the flow session
        - screen: current screen name (for data_exchange)
        - data: user-submitted form data (for data_exchange)

    Response format:
        Encrypted (base64) response containing screen name and data to render.
    """

    def post(self, request, *args, **kwargs):
        try:
            raw_body = json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        # Check if the request is encrypted (has encryption fields)
        encrypted_flow_data = raw_body.get('encrypted_flow_data')
        encrypted_aes_key = raw_body.get('encrypted_aes_key')
        initial_vector = raw_body.get('initial_vector')

        if encrypted_flow_data and encrypted_aes_key and initial_vector:
            return self._handle_encrypted_request(
                encrypted_flow_data, encrypted_aes_key, initial_vector
            )

        # Fallback: handle unencrypted request (for testing / draft flows)
        return self._handle_plaintext_request(raw_body)

    def _handle_encrypted_request(self, encrypted_flow_data, encrypted_aes_key,
                                  initial_vector):
        """Decrypt the request, process it, and return an encrypted response."""
        from .flow_crypto import decrypt_flow_request, encrypt_flow_response

        # Find a config that has a private key
        private_key_pem = self._get_private_key()
        if not private_key_pem:
            logger.error("WhatsApp Flow endpoint: No private key configured for decryption.")
            return HttpResponse(status=500)

        try:
            body, aes_key, iv = decrypt_flow_request(
                encrypted_flow_data, encrypted_aes_key,
                initial_vector, private_key_pem,
            )
        except Exception as e:
            logger.error(f"WhatsApp Flow endpoint: Decryption failed: {e}", exc_info=True)
            return HttpResponse(status=500)

        logger.info(
            f"WhatsApp Flow endpoint (encrypted). Action: {body.get('action')}, "
            f"flow_token: {body.get('flow_token')}"
        )

        try:
            response_data = self._process_body(body)
        except Exception as e:
            logger.error(f"WhatsApp Flow endpoint: Unhandled error processing body: {e}", exc_info=True)
            response_data = {"data": {"error": "An error occurred."}}

        try:
            encrypted_response = encrypt_flow_response(response_data, aes_key, iv)
        except Exception as e:
            logger.error(f"WhatsApp Flow endpoint: Encryption failed: {e}", exc_info=True)
            return HttpResponse(status=500)

        return HttpResponse(encrypted_response, content_type='text/plain')

    def _handle_plaintext_request(self, body):
        """Handle an unencrypted request (draft flows / testing)."""
        action = body.get('action')
        flow_token = body.get('flow_token')
        logger.info(f"WhatsApp Flow endpoint called. Action: {action}, flow_token: {flow_token}")

        response_data = self._process_body(body)
        return JsonResponse(response_data)

    def _process_body(self, body):
        """Route the decrypted/plain body to the correct handler and return response dict."""
        action = body.get('action')

        if action == 'ping':
            return {"data": {"status": "active"}}

        if action == 'INIT':
            return self._handle_init(body)

        if action == 'data_exchange':
            return self._handle_data_exchange(body)

        logger.warning(f"WhatsApp Flow endpoint: Unknown action '{action}'")
        return {"data": {"error": "Unknown action"}}

    def _get_private_key(self):
        """Retrieve the first available private key from active MetaAppConfigs."""
        config = MetaAppConfig.objects.filter(
            is_active=True, flow_private_key_pem__isnull=False,
        ).exclude(flow_private_key_pem='').first()
        return config.flow_private_key_pem if config else None


    def _handle_init(self, body):
        """Handle INIT action - return the appropriate initial screen dict."""
        flow_token = body.get('flow_token', '')
        # Check flow_action_payload to determine which screen to show
        flow_action_payload = body.get('flow_action_payload', {}) or {}
        screen_hint = flow_action_payload.get('screen', '')

        if screen_hint == 'REGISTER':
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "",
                    "is_error": False
                }
            }

        # Default to login screen
        return {
            "screen": "LOGIN",
            "data": {
                "error_message": "",
                "is_error": False
            }
        }

    def _handle_data_exchange(self, body):
        """Handle data_exchange action - process form submissions."""
        from django.contrib.auth import authenticate
        from conversations.models import Contact, ContactSession

        screen = body.get('screen')
        data = body.get('data', {})
        flow_token = body.get('flow_token')

        logger.info(f"WhatsApp Flow data_exchange: screen={screen}, flow_token={flow_token}")

        if screen == 'LOGIN':
            return self._handle_login_screen(data, flow_token)

        if screen == 'REGISTER':
            return self._handle_register_screen(data, flow_token)

        logger.warning(f"WhatsApp Flow data_exchange: Unknown screen '{screen}'")
        return {"data": {"error": "Unknown screen"}}

    # ------------------------------------------------------------------
    # Screen handlers
    # ------------------------------------------------------------------

    def _handle_login_screen(self, data, flow_token):
        """Process the LOGIN screen form submission."""
        from django.contrib.auth import authenticate
        from conversations.models import Contact, ContactSession

        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            return {
                "screen": "LOGIN",
                "data": {
                    "error_message": "Please enter both username and password.",
                    "is_error": True
                }
            }

        auth_user = authenticate(username=username, password=password)
        if auth_user is not None:
            if not flow_token:
                logger.error("WhatsApp Flow auth: flow_token missing. Cannot create session.")
                return {
                    "screen": "LOGIN",
                    "data": {
                        "error_message": "Authentication error. Please try again.",
                        "is_error": True
                    }
                }

            try:
                contact = Contact.objects.get(whatsapp_id=flow_token)
                session, _ = ContactSession.objects.get_or_create(contact=contact)
                session.start()
                logger.info(f"WhatsApp Flow auth: Session started for contact {flow_token} as user '{username}'.")
            except Contact.DoesNotExist:
                logger.error(f"WhatsApp Flow auth: Contact with whatsapp_id '{flow_token}' not found.")
                return {
                    "screen": "LOGIN",
                    "data": {
                        "error_message": "Authentication error. Please try again.",
                        "is_error": True
                    }
                }

            return {
                "screen": "COMPLETE",
                "data": {}
            }
        else:
            logger.warning(f"WhatsApp Flow auth: Failed authentication attempt for username '{username}'.")
            return {
                "screen": "LOGIN",
                "data": {
                    "error_message": "Incorrect username or password. Please try again.",
                    "is_error": True
                }
            }

    def _handle_register_screen(self, data, flow_token):
        """Process the REGISTER screen form submission — create a new user account."""
        from django.contrib.auth.models import User
        from conversations.models import Contact, ContactSession
        from customer_data.models import CustomerProfile
        import datetime as _dt

        if not isinstance(data, dict):
            data = {}

        username = (data.get('username') or '').strip()
        email = (data.get('email') or '').strip()
        password = (data.get('password') or '').strip()
        confirm_password = (data.get('confirm_password') or '').strip()
        first_name = (data.get('first_name') or '').strip()
        last_name = (data.get('last_name') or '').strip()
        gender = (data.get('gender') or '').strip()
        date_of_birth = (data.get('date_of_birth') or '').strip()
        referral_code = (data.get('referral_code') or '').strip() or None

        # --- Validation ---
        if not first_name or not last_name:
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "First name and last name are required.",
                    "is_error": True
                }
            }

        if not username or not password:
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "Username and password are required.",
                    "is_error": True
                }
            }

        if not email or '@' not in email:
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "A valid email address is required.",
                    "is_error": True
                }
            }

        if password != confirm_password:
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "Passwords do not match.",
                    "is_error": True
                }
            }

        if len(password) < 8:
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "Password must be at least 8 characters.",
                    "is_error": True
                }
            }

        if User.objects.filter(username=username).exists():
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "Username already taken. Please choose another.",
                    "is_error": True
                }
            }

        if CustomerProfile.objects.filter(email=email).exists():
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "An account with this email already exists.",
                    "is_error": True
                }
            }

        # Validate date_of_birth format if provided
        parsed_dob = None
        if date_of_birth:
            try:
                parsed_dob = _dt.date.fromisoformat(date_of_birth)
            except ValueError:
                return {
                    "screen": "REGISTER",
                    "data": {
                        "error_message": "Date of birth must be in YYYY-MM-DD format (e.g. 1990-01-31).",
                        "is_error": True
                    }
                }

        # Normalise gender to model choices: M / F / O
        gender_map = {'m': 'M', 'male': 'M', 'f': 'F', 'female': 'F', 'o': 'O', 'other': 'O'}
        normalised_gender = gender_map.get(gender.lower(), None) if gender else None

        # --- Create account ---
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            logger.info(f"WhatsApp Flow register: User '{username}' created.")

            # Link to contact if flow_token is a whatsapp_id
            if flow_token:
                try:
                    contact = Contact.objects.get(whatsapp_id=flow_token)
                    # Create or update customer profile
                    profile, created = CustomerProfile.objects.get_or_create(
                        contact=contact,
                        defaults={
                            'user': user,
                            'email': email,
                            'first_name': first_name,
                            'last_name': last_name,
                            'gender': normalised_gender,
                            'date_of_birth': parsed_dob,
                        },
                    )
                    if not created:
                        # Update existing profile: always set the names/DOB/gender
                        # submitted during registration so User and profile are consistent.
                        update_fields = []
                        if not profile.user:
                            profile.user = user
                            update_fields.append('user')
                        if email and not profile.email:
                            profile.email = email
                            update_fields.append('email')
                        if first_name:
                            profile.first_name = first_name
                            update_fields.append('first_name')
                        if last_name:
                            profile.last_name = last_name
                            update_fields.append('last_name')
                        if normalised_gender:
                            profile.gender = normalised_gender
                            update_fields.append('gender')
                        if parsed_dob:
                            profile.date_of_birth = parsed_dob
                            update_fields.append('date_of_birth')
                        if update_fields:
                            profile.save(update_fields=update_fields)

                    # Process referral code if provided
                    if referral_code:
                        try:
                            from referrals.utils import link_referral
                            link_referral(new_user=user, referral_code=referral_code)
                            logger.info(
                                f"WhatsApp Flow register: Linked referral code '{referral_code}' "
                                f"to user '{username}'."
                            )
                        except Exception as ref_exc:
                            logger.warning(
                                f"WhatsApp Flow register: Could not apply referral code "
                                f"'{referral_code}' for user '{username}': {ref_exc}"
                            )

                    # Start a session so the user is immediately logged in
                    session, _ = ContactSession.objects.get_or_create(contact=contact)
                    session.start()
                    logger.info(
                        f"WhatsApp Flow register: Session started for contact {flow_token} "
                        f"as user '{username}'."
                    )
                except Contact.DoesNotExist:
                    logger.warning(
                        f"WhatsApp Flow register: Contact with whatsapp_id '{flow_token}' not found. "
                        f"User created but not linked to a contact."
                    )

            return {
                "screen": "COMPLETE",
                "data": {}
            }

        except Exception as e:
            logger.error(f"WhatsApp Flow register: Error creating user '{username}': {e}", exc_info=True)
            return {
                "screen": "REGISTER",
                "data": {
                    "error_message": "Registration failed. Please try again later.",
                    "is_error": True
                }
            }


class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS: return True
        return request.user and request.user.is_staff

class MetaAppConfigViewSet(viewsets.ModelViewSet):
    queryset = MetaAppConfig.objects.all().order_by('-is_active', 'name')
    serializer_class = MetaAppConfigSerializer
    permission_classes = [permissions.IsAdminUser]

    @transaction.atomic
    def perform_create(self, serializer):
        # Multiple active configs are now allowed - no need to deactivate others
        serializer.save()

    @transaction.atomic
    def perform_update(self, serializer):
        # Multiple active configs are now allowed - no need to deactivate others
        serializer.save()

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def set_active(self, request, pk=None):
        """Toggle the active status of a configuration."""
        config = self.get_object()
        config.is_active = True
        config.save(update_fields=['is_active', 'updated_at'])
        return Response(self.get_serializer(config).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def set_inactive(self, request, pk=None):
        """Deactivate a configuration."""
        config = self.get_object()
        config.is_active = False
        config.save(update_fields=['is_active', 'updated_at'])
        return Response(self.get_serializer(config).data, status=status.HTTP_200_OK)

class WebhookEventLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WebhookEventLog.objects.all().select_related('app_config').order_by('-received_at')
    permission_classes = [permissions.IsAdminUser]
    filterset_fields = ['event_type', 'processing_status', 'event_identifier', 'phone_number_id_received', 'waba_id_received']
    search_fields = ['payload', 'processing_notes', 'event_identifier']

    def get_serializer_class(self):
        return WebhookEventLogListSerializer if self.action == 'list' else WebhookEventLogSerializer

    @action(detail=False, methods=['get'])
    def latest(self, request):
        count_str = request.query_params.get('count', '10')
        try:
            count = int(count_str)
            if not (0 < count <= 200): raise ValueError("Count must be between 1 and 200.")
        except ValueError as e:
            return Response({"error": f"Invalid 'count' parameter: {e}"}, status=status.HTTP_400_BAD_REQUEST)
        latest_logs = self.get_queryset()[:count]
        serializer = self.get_serializer(latest_logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        log_entry = self.get_object()
        if log_entry.event_type != 'message':
             return Response({"error": "Only 'message' events can be marked for reprocessing via this action currently."}, status=status.HTTP_400_BAD_REQUEST)
        
        log_entry.processing_status = 'pending_reprocessing'
        log_entry.processing_notes = (log_entry.processing_notes or "") + \
                                     f"\nManually marked for reprocessing by {request.user} on {timezone.now().isoformat()}."
        log_entry.processed_at = None 
        log_entry.save(update_fields=['processing_status', 'processing_notes', 'processed_at'])
        logger.info(f"WebhookEventLog {log_entry.id} marked for reprocessing by user {request.user}.")
        return Response({"message": f"Event {log_entry.id} marked for reprocessing."}, status=status.HTTP_200_OK)