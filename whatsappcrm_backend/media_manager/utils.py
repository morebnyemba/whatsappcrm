# media_manager/utils.py
import requests
import logging
import os # For os.path.basename

logger = logging.getLogger(__name__)

def actual_upload_to_whatsapp_api(
    file_path: str,
    mime_type: str,
    phone_number_id: str,
    access_token: str,
    api_version: str = "v22.0" # Default to v22.0 or use the one from MetaAppConfig
) -> str | None:
    """
    Uploads a media file to WhatsApp servers and returns the media ID.
    Returns None if the upload fails.
    """
    if not os.path.exists(file_path):
        logger.error(f"[WhatsApp API Upload] File not found at path: {file_path}")
        return None

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/media"
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    
    # It's crucial to open the file in binary mode 'rb'
    try:
        with open(file_path, 'rb') as f:
            files_payload = {
                'file': (os.path.basename(file_path), f, mime_type),
                'messaging_product': (None, 'whatsapp'),
                # 'type': (None, mime_type) # Including type is optional but can be helpful
            }
            
            logger.info(
                f"[WhatsApp API Upload] Attempting to upload {file_path} (type: {mime_type}) "
                f"to WhatsApp for Phone ID {phone_number_id} using API {api_version}."
            )
            response = requests.post(url, headers=headers, files=files_payload, timeout=60) # 60-second timeout

        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        
        response_data = response.json()
        media_id = response_data.get("id")
        
        if media_id:
            logger.info(f"[WhatsApp API Upload] Successfully uploaded media. WhatsApp Media ID: {media_id}")
            return media_id
        else:
            logger.error(
                f"[WhatsApp API Upload] Upload succeeded (status {response.status_code}) but no media ID in response. "
                f"Response: {response_data}"
            )
            return None

    except requests.exceptions.HTTPError as e:
        error_content = "No response content"
        if e.response is not None:
            try:
                error_content = e.response.json() # Try to get JSON error details
            except ValueError: # If response is not JSON
                error_content = e.response.text
        logger.error(
            f"[WhatsApp API Upload] HTTP error: {e}. Status: {e.response.status_code if e.response else 'N/A'}. "
            f"Content: {error_content}",
            exc_info=True # Include stack trace
        )
    except requests.exceptions.Timeout:
        logger.error(f"[WhatsApp API Upload] Request timed out while uploading {file_path}.", exc_info=True)
    except requests.exceptions.RequestException as e:
        logger.error(f"[WhatsApp API Upload] Request exception: {e}", exc_info=True)
    except IOError as e:
        logger.error(f"[WhatsApp API Upload] IO error reading file {file_path}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[WhatsApp API Upload] An unexpected error occurred: {e}", exc_info=True)
    
    return None