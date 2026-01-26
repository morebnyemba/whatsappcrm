# whatsappcrm_backend/conversations/services.py

import logging
from .models import Contact
from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)

def get_or_create_contact_by_wa_id(wa_id: str, name: str = None, meta_app_config: MetaAppConfig = None):
    """
    Retrieves or creates a Contact based on their WhatsApp ID.
    Updates the name if a new one is provided for an existing contact.
    Associates the contact with a MetaAppConfig if provided.
    
    Args:
        wa_id: WhatsApp ID of the contact
        name: Display name of the contact
        meta_app_config: Associated MetaAppConfig (the phone number the contact messages)
    
    Returns:
        Tuple of (contact, created) where created is True if contact was newly created
    """
    if not wa_id:
        logger.error("get_or_create_contact_by_wa_id called with an empty wa_id. Cannot proceed.")
        return None, False

    defaults = {}
    if name:
        defaults['name'] = name
    if meta_app_config:
        defaults['associated_app_config'] = meta_app_config

    contact, created = Contact.objects.update_or_create(
        whatsapp_id=wa_id,
        defaults=defaults
    )

    if created:
        config_name = meta_app_config.name if meta_app_config else 'None'
        logger.info(f"Created new contact: {name or 'Unknown'} ({wa_id}) associated with config: {config_name}")
    else:
        updates = []
        # Update name if it changed
        if name and contact.name != name:
            logger.info(f"Updating contact name for {wa_id} from '{contact.name}' to '{name}'.")
            contact.name = name
            updates.append('name')
        
        # Update associated_app_config if different and provided
        if meta_app_config and contact.associated_app_config_id != meta_app_config.id:
            old_config_name = contact.associated_app_config.name if contact.associated_app_config else 'None'
            logger.info(f"Updating contact {wa_id} associated config from '{old_config_name}' to '{meta_app_config.name}'.")
            contact.associated_app_config = meta_app_config
            updates.append('associated_app_config')
        
        if updates:
            contact.save(update_fields=updates)

    return contact, created
