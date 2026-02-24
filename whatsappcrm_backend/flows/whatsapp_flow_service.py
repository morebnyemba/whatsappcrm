# whatsappcrm_backend/flows/whatsapp_flow_service.py

import requests
import json
import logging
import time
from typing import Optional, Dict, Any, List
from django.utils import timezone
from django.conf import settings

from .models import WhatsAppFlow, WhatsAppFlowResponse
from meta_integration.models import MetaAppConfig
from conversations.models import Contact

logger = logging.getLogger(__name__)


class WhatsAppFlowService:
    """
    Service for managing WhatsApp interactive flows with Meta's API.
    Handles creation, updating, publishing, and syncing flows with Meta.
    """

    def __init__(self, meta_config: MetaAppConfig):
        """
        Initialize the service with a Meta app configuration.

        Args:
            meta_config: The MetaAppConfig instance to use for API calls
        """
        self.meta_config = meta_config
        self.base_url = f"https://graph.facebook.com/{meta_config.api_version}"
        self.headers = {
            "Authorization": f"Bearer {meta_config.access_token}",
            "Content-Type": "application/json",
        }

    def list_flows(self) -> List[Dict[str, Any]]:
        """
        Lists all flows from Meta's platform for this WhatsApp Business Account.

        Returns:
            List of flow dictionaries containing id, name, and other flow details
        """
        url = f"{self.base_url}/{self.meta_config.waba_id}/flows"
        all_flows = []

        try:
            while url:
                response = requests.get(url, headers=self.headers, timeout=20)
                response.raise_for_status()

                result = response.json()
                flows = result.get('data', [])
                all_flows.extend(flows)

                paging = result.get('paging', {})
                url = paging.get('next')

            logger.info(f"Retrieved {len(all_flows)} flows from Meta")
            return all_flows

        except requests.exceptions.RequestException as e:
            logger.error(f"Error listing flows from Meta: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    logger.error(f"Error details: {error_details}")
                except (ValueError, json.JSONDecodeError):
                    logger.error(f"Response: {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing flows: {e}", exc_info=True)
            return []

    def find_flow_by_name(self, flow_name: str) -> Optional[str]:
        """
        Finds a flow on Meta by its name and returns the flow_id if found.

        Args:
            flow_name: The name of the flow to find (with version suffix)

        Returns:
            The flow_id if found, None otherwise
        """
        flows = self.list_flows()

        for flow in flows:
            if flow.get('name') == flow_name:
                flow_id = flow.get('id')
                logger.info(f"Found existing flow on Meta: '{flow_name}' with ID: {flow_id}")
                return flow_id

        logger.info(f"No existing flow found on Meta with name: '{flow_name}'")
        return None

    def create_flow(self, whatsapp_flow: WhatsAppFlow) -> bool:
        """
        Creates a new flow on Meta's platform.

        Args:
            whatsapp_flow: The WhatsAppFlow instance to create on Meta

        Returns:
            bool: True if successful, False otherwise
        """
        url = f"{self.base_url}/{self.meta_config.waba_id}/flows"

        version_suffix = getattr(settings, 'META_SYNC_VERSION_SUFFIX', 'v1_03')
        flow_name = whatsapp_flow.friendly_name or whatsapp_flow.name
        flow_name_with_version = f"{flow_name}_{version_suffix}"

        payload = {
            "name": flow_name_with_version,
            "categories": ["OTHER"]
        }

        try:
            whatsapp_flow.sync_status = 'syncing'
            whatsapp_flow.save(update_fields=['sync_status'])

            # Check if flow already exists on Meta
            existing_flow_id = self.find_flow_by_name(flow_name_with_version)
            if existing_flow_id:
                logger.info(f"Flow '{flow_name_with_version}' already exists on Meta with ID: {existing_flow_id}")
                whatsapp_flow.flow_id = existing_flow_id
                whatsapp_flow.sync_status = 'synced'
                whatsapp_flow.sync_error = None
                whatsapp_flow.last_synced_at = timezone.now()
                whatsapp_flow.save(update_fields=['flow_id', 'sync_status', 'sync_error', 'last_synced_at'])
                return True

            response = requests.post(url, headers=self.headers, json=payload, timeout=20)
            response.raise_for_status()

            result = response.json()
            flow_id = result.get('id')

            if flow_id:
                whatsapp_flow.flow_id = flow_id
                whatsapp_flow.sync_status = 'synced'
                whatsapp_flow.sync_error = None
                whatsapp_flow.last_synced_at = timezone.now()
                whatsapp_flow.save(update_fields=['flow_id', 'sync_status', 'sync_error', 'last_synced_at'])
                logger.info(f"Created flow on Meta: '{flow_name_with_version}' with ID: {flow_id}")
                return True
            else:
                whatsapp_flow.sync_status = 'error'
                whatsapp_flow.sync_error = f"No flow_id in response: {result}"
                whatsapp_flow.save(update_fields=['sync_status', 'sync_error'])
                logger.error(f"Failed to create flow on Meta: no flow_id in response")
                return False

        except requests.exceptions.RequestException as e:
            error_msg = f"Error creating flow on Meta: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg += f" - Details: {error_details}"
                except (ValueError, json.JSONDecodeError):
                    error_msg += f" - Response: {e.response.text}"
            whatsapp_flow.sync_status = 'error'
            whatsapp_flow.sync_error = error_msg
            whatsapp_flow.save(update_fields=['sync_status', 'sync_error'])
            logger.error(error_msg)
            return False
        except Exception as e:
            whatsapp_flow.sync_status = 'error'
            whatsapp_flow.sync_error = str(e)
            whatsapp_flow.save(update_fields=['sync_status', 'sync_error'])
            logger.error(f"Unexpected error creating flow: {e}", exc_info=True)
            return False

    def update_flow_json(self, whatsapp_flow: WhatsAppFlow) -> bool:
        """
        Updates the flow JSON on Meta's platform.

        Args:
            whatsapp_flow: The WhatsAppFlow instance with updated flow_json

        Returns:
            bool: True if successful, False otherwise
        """
        if not whatsapp_flow.flow_id:
            logger.error(f"Cannot update flow JSON: flow_id not set for '{whatsapp_flow.name}'")
            return False

        url = f"{self.base_url}/{whatsapp_flow.flow_id}/assets"

        try:
            flow_json_str = json.dumps(whatsapp_flow.flow_json)

            response = requests.post(
                url,
                headers={
                    "Authorization": self.headers["Authorization"],
                },
                files={
                    "file": ("flow.json", flow_json_str, "application/json"),
                    "name": (None, "flow.json"),
                    "asset_type": (None, "FLOW_JSON"),
                },
                timeout=30
            )
            response.raise_for_status()

            result = response.json()
            if result.get('success'):
                whatsapp_flow.sync_error = None
                whatsapp_flow.last_synced_at = timezone.now()
                whatsapp_flow.save(update_fields=['sync_error', 'last_synced_at'])
                logger.info(f"Updated flow JSON on Meta for '{whatsapp_flow.name}' (ID: {whatsapp_flow.flow_id})")
                return True
            else:
                error_msg = f"Failed to update flow JSON: {result}"
                whatsapp_flow.sync_error = error_msg
                whatsapp_flow.save(update_fields=['sync_error'])
                logger.error(error_msg)
                return False

        except requests.exceptions.RequestException as e:
            error_msg = f"Error updating flow JSON: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg += f" - Details: {error_details}"
                except (ValueError, json.JSONDecodeError):
                    error_msg += f" - Response: {e.response.text}"
            whatsapp_flow.sync_error = error_msg
            whatsapp_flow.save(update_fields=['sync_error'])
            logger.error(error_msg)
            return False
        except Exception as e:
            whatsapp_flow.sync_error = str(e)
            whatsapp_flow.save(update_fields=['sync_error'])
            logger.error(f"Unexpected error updating flow JSON: {e}", exc_info=True)
            return False

    def publish_flow(self, whatsapp_flow: WhatsAppFlow) -> bool:
        """
        Publishes a flow on Meta's platform, making it available to users.

        Args:
            whatsapp_flow: The WhatsAppFlow instance to publish

        Returns:
            bool: True if successful, False otherwise
        """
        if not whatsapp_flow.flow_id:
            logger.error(f"Cannot publish flow: flow_id not set for '{whatsapp_flow.name}'")
            return False

        url = f"{self.base_url}/{whatsapp_flow.flow_id}/publish"

        try:
            response = requests.post(url, headers=self.headers, timeout=20)
            response.raise_for_status()

            result = response.json()
            if result.get('success'):
                whatsapp_flow.sync_status = 'published'
                whatsapp_flow.sync_error = None
                whatsapp_flow.last_synced_at = timezone.now()
                whatsapp_flow.save(update_fields=['sync_status', 'sync_error', 'last_synced_at'])
                logger.info(f"Published flow '{whatsapp_flow.name}' (ID: {whatsapp_flow.flow_id})")
                return True
            else:
                error_msg = f"Failed to publish flow: {result}"
                whatsapp_flow.sync_error = error_msg
                whatsapp_flow.save(update_fields=['sync_error'])
                logger.error(error_msg)
                return False

        except requests.exceptions.RequestException as e:
            error_msg = f"Error publishing flow: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg += f" - Details: {error_details}"
                except (ValueError, json.JSONDecodeError):
                    error_msg += f" - Response: {e.response.text}"
            whatsapp_flow.sync_error = error_msg
            whatsapp_flow.save(update_fields=['sync_error'])
            logger.error(error_msg)
            return False
        except Exception as e:
            whatsapp_flow.sync_error = str(e)
            whatsapp_flow.save(update_fields=['sync_error'])
            logger.error(f"Unexpected error publishing flow: {e}", exc_info=True)
            return False

    def sync_flow(self, whatsapp_flow: WhatsAppFlow) -> bool:
        """
        Full sync: creates flow on Meta (if needed), uploads flow JSON,
        and optionally publishes.

        Args:
            whatsapp_flow: The WhatsAppFlow instance to sync

        Returns:
            bool: True if successful, False otherwise
        """
        # Step 1: Create flow on Meta if not already created
        if not whatsapp_flow.flow_id:
            if not self.create_flow(whatsapp_flow):
                return False

        # Step 2: Upload the flow JSON
        time.sleep(1)  # Brief delay to avoid rate limiting
        if not self.update_flow_json(whatsapp_flow):
            return False

        whatsapp_flow.sync_status = 'synced'
        whatsapp_flow.save(update_fields=['sync_status'])
        logger.info(f"Flow '{whatsapp_flow.name}' synced successfully")
        return True

    def delete_flow(self, whatsapp_flow: WhatsAppFlow) -> bool:
        """
        Deletes a flow from Meta's platform.

        Args:
            whatsapp_flow: The WhatsAppFlow instance to delete from Meta

        Returns:
            bool: True if successful, False otherwise
        """
        if not whatsapp_flow.flow_id:
            logger.warning(f"Cannot delete flow from Meta: no flow_id for '{whatsapp_flow.name}'")
            return False

        url = f"{self.base_url}/{whatsapp_flow.flow_id}"

        try:
            response = requests.delete(url, headers=self.headers, timeout=20)
            response.raise_for_status()

            logger.info(f"Deleted flow from Meta: '{whatsapp_flow.name}' (ID: {whatsapp_flow.flow_id})")
            whatsapp_flow.flow_id = None
            whatsapp_flow.sync_status = 'draft'
            whatsapp_flow.sync_error = None
            whatsapp_flow.save(update_fields=['flow_id', 'sync_status', 'sync_error'])
            return True

        except requests.exceptions.RequestException as e:
            error_msg = f"Error deleting flow from Meta: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg += f" - Details: {error_details}"
                except (ValueError, json.JSONDecodeError):
                    error_msg += f" - Response: {e.response.text}"
            logger.error(error_msg)
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting flow: {e}", exc_info=True)
            return False

    @staticmethod
    def create_flow_message_data(
        flow_id: str,
        screen: str,
        flow_cta: str,
        body_text: str,
        header_text: str = None,
        footer_text: str = None,
        flow_token: str = None,
    ) -> Dict[str, Any]:
        """
        Creates the interactive message payload for sending a WhatsApp Flow.

        Args:
            flow_id: The Meta flow ID
            screen: The initial screen to show
            flow_cta: Call-to-action button text
            body_text: Body text of the message
            header_text: Optional header text
            footer_text: Optional footer text
            flow_token: Optional token for tracking the flow session

        Returns:
            Dict containing the interactive message payload
        """
        interactive_payload = {
            "type": "flow",
            "body": {"text": body_text},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": flow_token or "",
                    "flow_id": flow_id,
                    "flow_cta": flow_cta,
                    "flow_action": "navigate",
                    "flow_action_payload": {
                        "screen": screen
                    }
                }
            }
        }

        if header_text:
            interactive_payload["header"] = {"type": "text", "text": header_text}

        if footer_text:
            interactive_payload["footer"] = {"text": footer_text}

        return interactive_payload

    @staticmethod
    def process_flow_response(response_data: Dict[str, Any], contact: Contact,
                               whatsapp_flow: WhatsAppFlow) -> WhatsAppFlowResponse:
        """
        Processes and stores a flow response from a user.

        Args:
            response_data: The response payload from Meta webhook
            contact: The contact who submitted the response
            whatsapp_flow: The WhatsApp flow instance

        Returns:
            WhatsAppFlowResponse: The created response instance
        """
        flow_token = response_data.get('flow_token', '')

        flow_response = WhatsAppFlowResponse.objects.create(
            whatsapp_flow=whatsapp_flow,
            contact=contact,
            flow_token=flow_token,
            response_data=response_data,
            is_processed=False
        )

        logger.info(f"Created flow response {flow_response.id} for contact {contact.id}")
        return flow_response
