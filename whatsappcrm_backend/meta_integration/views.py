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
    """Helper function to get the active MetaAppConfig."""
    try:
        return MetaAppConfig.objects.get_active_config()
    except MetaAppConfig.DoesNotExist:
        logger.critical("CRITICAL: No active Meta App Configuration found. Webhook and message sending will fail.")
        return None
    except MetaAppConfig.MultipleObjectsReturned:
        logger.critical("CRITICAL: Multiple active Meta App Configurations found. Please fix in Django Admin.")
        return None
    except Exception as e:
        logger.critical(f"CRITICAL: Error retrieving active MetaAppConfig: {e}", exc_info=True)
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
        active_config = get_active_meta_config()
        app_secret = getattr(settings, 'WHATSAPP_APP_SECRET', None)
        
        # Strip whitespace from app secret if present
        if app_secret:
            app_secret = app_secret.strip()

        if not active_config:
            logger.error("WEBHOOK POST: Processing failed - No active MetaAppConfig. Event ignored.")
            return HttpResponse("EVENT_RECEIVED_BUT_UNCONFIGURED", status=200)

        if not app_secret:
             logger.critical(
                f"CRITICAL: WHATSAPP_APP_SECRET is not configured in Django settings for MetaAppConfig "
                f"('{active_config.name}'). Webhook signature verification will be skipped. "
                f"THIS IS A SECURITY RISK."
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
                logger.error("Webhook signature verification FAILED. Discarding request.")
                # Log header keys (not values) for debugging
                header_keys = list(request.headers.keys())
                WebhookEventLog.objects.create(
                    app_config=active_config, event_type='security',
                    payload={'error': 'Signature verification failed', 'header_keys': header_keys},
                    processing_status='rejected', processing_notes='Invalid X-Hub-Signature-256'
                )
                return HttpResponse("Invalid signature", status=403)

        raw_payload_str = request.body.decode('utf-8', errors='ignore')
        logger.info(f"Webhook POST request received (Signature OK if secret configured). Body size: {len(raw_payload_str)}. Config: {active_config.name}")
        logger.debug(f"Raw webhook payload: {raw_payload_str}")
        
        try:
            payload = json.loads(raw_payload_str)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook: {e}. Body: {raw_payload_str[:500]}...")
            WebhookEventLog.objects.create(
                app_config=active_config, event_type='error',
                payload={'error': 'Invalid JSON', 'body_snippet': raw_payload_str[:500], 'exception': str(e)},
                processing_status='error', processing_notes='Failed to parse JSON.'
            )
            return HttpResponse("Invalid JSON payload", status=400)

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
            # Use the service to get or create contact
            contact, created = get_or_create_contact_by_wa_id(
                wa_id=contact_wa_id_from_payload,
                name=contact_profile_name,
                meta_app_config=None
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

        if message_data.get("referral"): self.handle_referral(message_data.get("referral"), contact_wa_id_from_payload, app_config, log_entry)
        if message_data.get("system"): self.handle_system_message(message_data.get("system"), contact_wa_id_from_payload, app_config, log_entry)
        if message_type == "interactive" and message_data.get("interactive", {}).get("type") == "nfm_reply":
             self.handle_flow_response(message_data.get("interactive",{}).get("nfm_reply",{}), contact_wa_id_from_payload, app_config, log_entry)


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
        logger.info(f"Received Flow (NFM) response for {contact_wa_id}: {flow_response_data}")
        self._save_log(log_entry, 'processed', "Flow (NFM) response logged and passed for processing.")


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
        if serializer.validated_data.get('is_active'):
            MetaAppConfig.objects.filter(is_active=True).update(is_active=False)
        serializer.save()

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.instance
        if serializer.validated_data.get('is_active') and not instance.is_active:
            MetaAppConfig.objects.filter(is_active=True).exclude(pk=instance.pk).update(is_active=False)
        serializer.save()

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def set_active(self, request, pk=None):
        config_to_activate = self.get_object()
        if config_to_activate.is_active:
            return Response({"message": "Configuration is already active."}, status=status.HTTP_200_OK)
        with transaction.atomic():
            MetaAppConfig.objects.filter(is_active=True).exclude(pk=config_to_activate.pk).update(is_active=False)
            config_to_activate.is_active = True
            config_to_activate.save(update_fields=['is_active', 'updated_at'])
        return Response(self.get_serializer(config_to_activate).data, status=status.HTTP_200_OK)

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