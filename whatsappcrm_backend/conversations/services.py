# whatsappcrm_backend/conversations/services.py

import logging
from .models import Contact
from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)

def get_or_create_contact_by_wa_id(wa_id: str, name: str = None, meta_app_config: MetaAppConfig = None):
    """
    Retrieves or creates a Contact based on their WhatsApp ID.
    Updates the name if a new one is provided for an existing contact.
    
    Args:
        wa_id: WhatsApp ID of the contact
        name: Display name of the contact
        meta_app_config: Associated MetaAppConfig (if applicable)
    
    Returns:
        Tuple of (contact, created) where created is True if contact was newly created
    """
    if not wa_id:
        logger.error("get_or_create_contact_by_wa_id called with an empty wa_id. Cannot proceed.")
        return None, False

    defaults = {}
    if name:
        defaults['name'] = name

    contact, created = Contact.objects.update_or_create(
        whatsapp_id=wa_id,
        defaults=defaults
    )

    if created:
        logger.info(f"Created new contact: {name or 'Unknown'} ({wa_id})")
    else:
        # Update name if it changed
        if name and contact.name != name:
            logger.info(f"Updating contact name for {wa_id} from '{contact.name}' to '{name}'.")
            contact.name = name
            contact.save(update_fields=['name'])

    return contact, created
