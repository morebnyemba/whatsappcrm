# whatsappcrm_backend/meta_integration/utils.py

import requests
import json
import logging
# from django.conf import settings # No longer using settings for API creds
from .models import MetaAppConfig # Import the model
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

def get_active_meta_config_for_sending():
    """
    Helper function to get an active MetaAppConfig for sending messages.
    This returns the first active config. For specific config selection,
    pass the config directly to send_whatsapp_message().
    """
    try:
        return MetaAppConfig.objects.get_active_config()
    except ObjectDoesNotExist:
        logger.critical("CRITICAL: No active Meta App Configuration found. Message sending will fail.")
        return None
    except Exception as e:
        logger.error(f"Error retrieving active MetaAppConfig: {e}", exc_info=True)
        return None


def get_config_by_phone_number_id(phone_number_id: str):
    """
    Get a MetaAppConfig by its phone_number_id.
    
    Args:
        phone_number_id: The phone number ID to look up
        
    Returns:
        MetaAppConfig instance or None
    """
    try:
        return MetaAppConfig.objects.get_config_by_phone_number_id(phone_number_id)
    except Exception as e:
        logger.error(f"Error retrieving MetaAppConfig by phone_number_id {phone_number_id}: {e}", exc_info=True)
        return None

def send_whatsapp_message(to_phone_number: str, message_type: str, data: dict, config: MetaAppConfig = None):
    """
    Sends a WhatsApp message using the Meta Graph API.
    Uses MetaAppConfig from the database.

    Args:
        to_phone_number (str): The recipient's WhatsApp ID (phone number).
        message_type (str): Type of message ('text', 'interactive', 'template', 'image', etc.).
        data (dict): The payload specific to the message type.
        config (MetaAppConfig, optional): The MetaAppConfig instance to use. 
                                          If None, tries to fetch the active one.
    Returns:
        dict: The JSON response from Meta API, or None if an error occurs.
    """
    if not config:
        config = get_active_meta_config_for_sending()

    if not config:
        logger.error("Cannot send WhatsApp message: No active MetaAppConfig available.")
        return None

    api_version = config.api_version
    phone_number_id = config.phone_number_id
    access_token = config.access_token

    # No need to check settings from django.conf anymore
    # if not all([api_version, phone_number_id, access_token]):
    #     logger.error("Meta API settings (version, phone_number_id, access_token) are not configured in the active DB record.")
    #     return None

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": message_type,
        message_type: data,
    }

    if message_type == "text" and "preview_url" in data:
        if not isinstance(data["preview_url"], bool):
            logger.warning(f"Correcting preview_url to boolean for text message. Original: {data['preview_url']}")
            data["preview_url"] = str(data["preview_url"]).lower() == 'true'
        payload[message_type]["preview_url"] = data["preview_url"]

    logger.debug(f"Sending WhatsApp message via config '{config.name}'. URL: {url}, Payload: {json.dumps(payload)}")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        
        response_json = response.json()
        logger.info(f"Message sent successfully to {to_phone_number} via config '{config.name}'. Response: {response_json}")
        # Store wamid for tracking if needed (e.g., response_json['messages'][0]['id'])
        return response_json
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error sending message to {to_phone_number} via config '{config.name}': {e.response.status_code} - {e.response.text}")
        try:
            error_details = e.response.json()
            logger.error(f"Meta API error details: {error_details}")
        except json.JSONDecodeError:
            logger.error("Could not decode Meta API error response as JSON.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending message to {to_phone_number} via config '{config.name}': {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while sending message to {to_phone_number} via config '{config.name}': {e}", exc_info=True)
        
    return None

# --- Helper functions to construct message payloads (remain the same) ---
# create_text_message_data, create_interactive_reply_buttons_data, etc.
# (These functions are already in the previous utils.py, no change needed for them here)
def create_text_message_data(text_body: str, preview_url: bool = False) -> dict:
    """Creates the data payload for a simple text message."""
    return {"body": text_body, "preview_url": preview_url}

def create_interactive_reply_buttons_data(body_text: str, buttons: list, header: dict = None, footer_text: str = None) -> dict:
    """
    Creates the data payload for an interactive message with reply buttons.
    """
    action = {"buttons": buttons}
    interactive_payload = {
        "type": "button",
        "body": {"text": body_text},
        "action": action,
    }
    if header:
        interactive_payload["header"] = header
    if footer_text:
        interactive_payload["footer"] = {"text": footer_text}
    return interactive_payload

def create_interactive_list_message_data(body_text: str, button_text: str, sections: list, header: dict = None, footer_text: str = None) -> dict:
    """
    Creates the data payload for an interactive list message.
    """
    action = {"button": button_text, "sections": sections}
    interactive_payload = {
        "type": "list",
        "body": {"text": body_text},
        "action": action,
    }
    if header:
        interactive_payload["header"] = header
    if footer_text:
        interactive_payload["footer"] = {"text": footer_text}
    return interactive_payload


def send_read_receipt_api(wamid: str, config: MetaAppConfig, show_typing_indicator: bool = False):
    """
    Sends a read receipt for a message to WhatsApp.
    
    Args:
        wamid: WhatsApp Message ID to mark as read
        config: MetaAppConfig instance to use for API call
        show_typing_indicator: Reserved for future use. Currently not implemented.
    
    Returns:
        dict: API response with {"success": True} or None on error
    """
    if not config:
        logger.error("Cannot send read receipt: No MetaAppConfig provided.")
        return None
    
    api_version = config.api_version
    phone_number_id = config.phone_number_id
    access_token = config.access_token
    
    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": wamid
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        logger.info(f"Read receipt sent for WAMID {wamid}")
        
        # Note: show_typing_indicator parameter is reserved for future implementation
        if show_typing_indicator:
            logger.debug("Typing indicator feature not yet implemented")
        
        return {"success": True}
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send read receipt for WAMID {wamid}: {e}")
        if hasattr(e.response, 'text'):
            logger.error(f"Meta API error response: {e.response.text}")
        return None
