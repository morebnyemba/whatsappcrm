# whatsappcrm_backend/flows/services.py

import logging
import json
import re
from typing import List, Dict, Any, Optional, Union, Literal # For Pydantic type hinting

from django.utils import timezone
from django.db import transaction
from pydantic import BaseModel, ValidationError, field_validator, root_validator, Field # For Pydantic v1, root_validator is different

from conversations.models import Contact, Message
from .models import Flow, FlowStep, FlowTransition, ContactFlowState
from customer_data.models import CustomerProfile
try:
    from media_manager.models import MediaAsset # For asset_pk lookup
    MEDIA_ASSET_ENABLED = True
except ImportError:
    MEDIA_ASSET_ENABLED = False
    logger.warning("MediaAsset model not found. Media steps will only support direct ID/Link.")


logger = logging.getLogger(__name__)

# --- Pydantic Models for Configuration Validation ---
# These should ideally be in a separate 'schemas.py' or 'types.py' file for better organization.

class BasePydanticConfig(BaseModel):
    class Config:
        extra = 'allow'
        # For Pydantic v2 an alias for validate_assignment is validate_assignment
        # For Pydantic v1, it was validate_assignment = True
        # validate_assignment = True # Ensure values are validated on assignment

# --- Configs for 'send_message' step ---
class TextMessageContent(BasePydanticConfig): # Renamed from TextMessagePayload to avoid confusion with WA payload
    body: str = Field(..., min_length=1, max_length=4096) # WhatsApp limit
    preview_url: bool = False

class MediaMessageContent(BasePydanticConfig): # Renamed
    asset_pk: Optional[int] = None
    id: Optional[str] = None      # WhatsApp Media ID
    link: Optional[str] = None    # Public URL
    caption: Optional[str] = Field(default=None, max_length=1024) # WhatsApp limit for caption
    filename: Optional[str] = None # Primarily for documents

    # Pydantic v2 model_validator
    # @model_validator(mode='after')
    # def check_media_source_v2(cls, values):
    # For Pydantic v1 root_validator
    @root_validator(pre=False, skip_on_failure=True)
    def check_media_source(cls, values):
        asset_pk, media_id, link = values.get('asset_pk'), values.get('id'), values.get('link')
        if not MEDIA_ASSET_ENABLED and asset_pk: # If MediaAsset not enabled, asset_pk is invalid
             raise ValueError("'asset_pk' provided but MediaAsset system is not enabled/imported.")
        if not (asset_pk or media_id or link):
            raise ValueError("One of 'asset_pk', 'id', or 'link' must be provided for media.")
        if asset_pk and not MEDIA_ASSET_ENABLED:
            logger.warning("MediaAsset functionality is not available, 'asset_pk' will be ignored if direct id/link is present.")
        return values

class InteractiveButtonReply(BasePydanticConfig):
    id: str = Field(..., min_length=1, max_length=256)
    title: str = Field(..., min_length=1, max_length=20)

class InteractiveButton(BasePydanticConfig): # This is the object in the buttons array
    type: Literal["reply"] = "reply"
    reply: InteractiveButtonReply

class InteractiveButtonAction(BasePydanticConfig):
    buttons: List[InteractiveButton] = Field(..., min_items=1, max_items=3)

class InteractiveHeader(BasePydanticConfig):
    type: Literal["text", "video", "image", "document"]
    text: Optional[str] = Field(default=None, max_length=60)
    # TODO: Add Pydantic models for media objects (image, video, document) if used in headers
    # image: Optional[MediaObject] = None 
    # video: Optional[MediaObject] = None
    # document: Optional[MediaObject] = None

class InteractiveBody(BasePydanticConfig):
    text: str = Field(..., min_length=1, max_length=1024)

class InteractiveFooter(BasePydanticConfig):
    text: str = Field(..., min_length=1, max_length=60)

class InteractiveMessagePayload(BasePydanticConfig): # The actual payload for 'interactive' type
    type: Literal["button", "list", "product", "product_list"] # Add others as WhatsApp supports
    header: Optional[InteractiveHeader] = None
    body: InteractiveBody
    footer: Optional[InteractiveFooter] = None
    action: Union[InteractiveButtonAction, "InteractiveListAction"] # Forward reference for ListAction
    # TODO: Add action types for product/product_list

class InteractiveListRow(BasePydanticConfig):
    id: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=24)
    description: Optional[str] = Field(default=None, max_length=72)

class InteractiveListSection(BasePydanticConfig):
    title: Optional[str] = Field(default=None, max_length=24)
    rows: List[InteractiveListRow] = Field(..., min_items=1, max_items=10)

class InteractiveListAction(BasePydanticConfig):
    button: str = Field(..., min_length=1, max_length=20) # Button text
    sections: List[InteractiveListSection] = Field(..., min_items=1) # Max 10 sections by WA

InteractiveMessagePayload.model_rebuild() # Pydantic v2: For forward references
# For Pydantic v1: InteractiveMessagePayload.update_forward_refs() 


class TemplateLanguage(BasePydanticConfig):
    code: str # e.g., "en_US", "en"

class TemplateParameter(BasePydanticConfig): # Simplified, actual can be complex
    type: Literal["text", "currency", "date_time", "image", "document", "video", "payload"]
    text: Optional[str] = None
    # TODO: Define Pydantic models for currency, date_time, image, document, video objects
    currency: Optional[Dict[str, Any]] = None # e.g. {"fallback_value": "$10.99", "code": "USD", "amount_1000": 10990}
    date_time: Optional[Dict[str, Any]] = None # e.g. {"fallback_value": "February 25, 1977"}
    image: Optional[Dict[str, Any]] = None    # e.g. {"id": "your-media-id"} or {"link": "url"}
    document: Optional[Dict[str, Any]] = None
    video: Optional[Dict[str, Any]] = None
    payload: Optional[str] = None # For quick_reply/URL button parameters

class TemplateComponent(BasePydanticConfig): # Also simplified
    type: Literal["header", "body", "button"]
    sub_type: Optional[Literal['url', 'quick_reply', 'call_button', 'catalog_button', 'mpm_button']] = None # For buttons
    parameters: Optional[List[TemplateParameter]] = None
    index: Optional[int] = None # For buttons, 0-indexed

class TemplateMessageContent(BasePydanticConfig): # Renamed
    name: str
    language: TemplateLanguage
    components: Optional[List[TemplateComponent]] = None

class ContactName(BasePydanticConfig): # For sending contact cards
    formatted_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    suffix: Optional[str] = None
    prefix: Optional[str] = None

class ContactAddress(BasePydanticConfig):
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactEmail(BasePydanticConfig):
    email: Optional[str] = None
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactPhone(BasePydanticConfig):
    phone: Optional[str] = None # Phone number with country code
    type: Optional[Literal['CELL', 'MAIN', 'IPHONE', 'HOME', 'WORK']] = None
    wa_id: Optional[str] = None # WhatsApp ID

class ContactOrg(BasePydanticConfig):
    company: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None

class ContactUrl(BasePydanticConfig):
    url: Optional[str] = None
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactObject(BasePydanticConfig): # Single contact object for the 'contacts' array
    addresses: Optional[List[ContactAddress]] = None
    birthday: Optional[str] = None # YYYY-MM-DD
    emails: Optional[List[ContactEmail]] = None
    name: ContactName
    org: Optional[ContactOrg] = None
    phones: Optional[List[ContactPhone]] = None
    urls: Optional[List[ContactUrl]] = None

class LocationMessageContent(BasePydanticConfig): # Renamed
    longitude: float
    latitude: float
    name: Optional[str] = None
    address: Optional[str] = None

# This is the FlowStep.config content for step_type 'send_message'
class StepConfigSendMessage(BasePydanticConfig):
    message_type: Literal["text", "image", "document", "audio", "video", "sticker", "interactive", "template", "contacts", "location"]
    text: Optional[TextMessageContent] = None
    image: Optional[MediaMessageContent] = None
    document: Optional[MediaMessageContent] = None
    audio: Optional[MediaMessageContent] = None
    video: Optional[MediaMessageContent] = None
    sticker: Optional[MediaMessageContent] = None
    interactive: Optional[InteractiveMessagePayload] = None
    template: Optional[TemplateMessageContent] = None
    contacts: Optional[List[ContactObject]] = None # Array of contact objects
    location: Optional[LocationMessageContent] = None

    @root_validator(pre=False, skip_on_failure=True) # Pydantic v2: @model_validator(mode='after')
    def check_payload_exists_for_type(cls, values):
        msg_type = values.get('message_type')
        payload_specific_to_type = values.get(msg_type)

        if msg_type and payload_specific_to_type is None:
             raise ValueError(f"Payload for message_type '{msg_type}' is missing or null.")
        
        # Specific check for interactive messages needing a subtype
        if msg_type == 'interactive':
            interactive_payload = values.get('interactive')
            if not interactive_payload or not interactive_payload.type: # interactive.type is its subtype
                raise ValueError("For 'interactive' messages, the 'interactive' payload must exist and specify its own 'type' (e.g., 'button', 'list').")
        return values

# --- Config for 'question' step ---
class ReplyConfig(BasePydanticConfig):
    save_to_variable: str
    expected_type: Literal["text", "email", "number", "interactive_id"] # Add more as needed
    validation_regex: Optional[str] = None

class StepConfigQuestion(BasePydanticConfig):
    message_config: Dict[str, Any] # This should be validated as a StepConfigSendMessage structure
    reply_config: ReplyConfig

    @field_validator('message_config') # Pydantic v2
    # For Pydantic v1: @validator('message_config')
    def validate_message_config_structure(cls, v):
        try:
            StepConfigSendMessage.model_validate(v) # Pydantic v2
            # For Pydantic v1: StepConfigSendMessage.parse_obj(v)
            return v
        except ValidationError as e:
            raise ValueError(f"message_config for question is invalid: {e.errors()}")

# --- Config for 'action' step ---
class ActionItemConfig(BasePydanticConfig):
    action_type: Literal["set_context_variable", "update_contact_field", "update_customer_profile", "switch_flow"]
    variable_name: Optional[str] = None
    value_template: Optional[Any] = None # Can be string, number, bool, list, dict
    field_path: Optional[str] = None
    fields_to_update: Optional[Dict[str, Any]] = None # For update_customer_profile
    target_flow_name: Optional[str] = None # For switch_flow
    initial_context_template: Optional[Dict[str, Any]] = Field(default_factory=dict)
    message_to_evaluate_for_new_flow: Optional[str] = None

    @root_validator(pre=False, skip_on_failure=True) # Pydantic v2: @model_validator(mode='after')
    def check_action_fields(cls, values):
        action_type = values.get('action_type')
        if action_type == 'set_context_variable':
            if values.get('variable_name') is None or values.get('value_template') is None: # value_template can be None, check for key presence if it can be None
                raise ValueError("For set_context_variable, 'variable_name' and 'value_template' are required.")
        elif action_type == 'update_contact_field':
            if not values.get('field_path') or values.get('value_template') is None:
                raise ValueError("For update_contact_field, 'field_path' and 'value_template' are required.")
        elif action_type == 'update_customer_profile':
            if not values.get('fields_to_update') or not isinstance(values.get('fields_to_update'), dict):
                raise ValueError("For update_customer_profile, 'fields_to_update' (a dictionary) is required.")
        elif action_type == 'switch_flow':
            if not values.get('target_flow_name'):
                raise ValueError("For switch_flow, 'target_flow_name' is required.")
        return values

class StepConfigAction(BasePydanticConfig):
    actions_to_run: List[ActionItemConfig] = Field(default_factory=list)

# --- Config for 'human_handover' step ---
class StepConfigHumanHandover(BasePydanticConfig):
    pre_handover_message_text: Optional[str] = None
    notification_details: Optional[str] = None # Simple string for now, could be more structured

# --- Config for 'end_flow' step ---
class StepConfigEndFlow(BasePydanticConfig):
    # End flow can optionally send a final message.
    # This should conform to StepConfigSendMessage structure.
    message_config: Optional[Dict[str, Any]] = None # Using Dict for now

    @field_validator('message_config') # Pydantic v2
    # For Pydantic v1: @validator('message_config')
    def validate_message_config_structure(cls, v):
        if v is None: return None # It's optional
        try:
            StepConfigSendMessage.model_validate(v) # Pydantic v2
            # For Pydantic v1: StepConfigSendMessage.parse_obj(v)
            return v
        except ValidationError as e:
            raise ValueError(f"message_config for end_flow is invalid: {e.errors()}")


# --- Utility functions ( _get_value_from_context_or_contact, _resolve_value, _resolve_template_components ) ---
# These remain the same as provided in message #56. For brevity, not re-pasting here.
# Assume they are defined above this point.

def _get_value_from_context_or_contact(variable_path: str, flow_context: dict, contact: Contact):
    if not variable_path: return None
    parts = variable_path.split('.')
    current_value = None
    if parts[0] == 'flow_context':
        current_value = flow_context
        path_to_traverse = parts[1:]
    elif parts[0] == 'contact':
        current_value = contact
        path_to_traverse = parts[1:]
    else: # Default to flow_context if no prefix
        current_value = flow_context
        path_to_traverse = parts
    for i, part in enumerate(path_to_traverse):
        try:
            if isinstance(current_value, dict):
                current_value = current_value.get(part)
            elif hasattr(current_value, part):
                attr_or_method = getattr(current_value, part)
                current_value = attr_or_method() if callable(attr_or_method) else attr_or_method
            else: return None
        except Exception as e:
            logger.warning(f"Error accessing path '{'.'.join(path_to_traverse[:i+1])}': {e}")
            return None
        if current_value is None and i < len(path_to_traverse) - 1: return None
    return current_value

def _resolve_value(template_value, flow_context: dict, contact: Contact):
    if isinstance(template_value, str):
        def replace_match(match):
            var_path = match.group(1).strip()
            val = _get_value_from_context_or_contact(var_path, flow_context, contact)
            return str(val) if val is not None else '' # Return empty string for None to avoid "None" in messages
        
        resolved_string = template_value
        # Limit iterations to prevent potential runaway if placeholders reference each other in a loop
        for _ in range(10): # Max 10 levels of nesting/recursion for placeholders
            new_string = re.sub(r"{{\s*([\w.]+)\s*}}", replace_match, resolved_string)
            if new_string == resolved_string: break
            resolved_string = new_string
        return resolved_string
    elif isinstance(template_value, dict):
        return {k: _resolve_value(v, flow_context, contact) for k, v in template_value.items()}
    elif isinstance(template_value, list):
        return [_resolve_value(item, flow_context, contact) for item in template_value]
    return template_value

def _resolve_template_components(components_config: list, flow_context: dict, contact: Contact) -> list:
    if not components_config or not isinstance(components_config, list): return []
    try:
        # Perform a deep copy to avoid modifying original config during resolution
        resolved_components_list = json.loads(json.dumps(components_config))
        for component in resolved_components_list:
            if isinstance(component.get('parameters'), list):
                for param in component['parameters']:
                    if param.get('type') == 'text' and 'text' in param:
                        param['text'] = _resolve_value(param['text'], flow_context, contact)
                    elif param.get('type') == 'currency' and param.get('currency'):
                        param['currency']['fallback_value'] = _resolve_value(param['currency'].get('fallback_value'), flow_context, contact)
                        # amount_1000 is usually a number, not templated, but code can be
                        param['currency']['code'] = _resolve_value(param['currency'].get('code'), flow_context, contact)
                    elif param.get('type') == 'date_time' and param.get('date_time'):
                        param['date_time']['fallback_value'] = _resolve_value(param['date_time'].get('fallback_value'), flow_context, contact)
                    elif param.get('type') in ['image', 'video', 'document'] and param.get(param['type']):
                        media_obj = param[param['type']]
                        if 'link' in media_obj:
                             media_obj['link'] = _resolve_value(media_obj['link'], flow_context, contact)
                        # IDs are usually static, but if templated:
                        # if 'id' in media_obj:
                        #    media_obj['id'] = _resolve_value(media_obj['id'], flow_context, contact)
                    elif param.get('type') == 'payload' and 'payload' in param: # For quick reply/URL button payloads
                        param['payload'] = _resolve_value(param['payload'], flow_context, contact)
        return resolved_components_list
    except Exception as e:
        logger.error(f"Error resolving template components: {e}. Config: {components_config}", exc_info=True)
        return components_config # Return original on error to avoid crash


# --- Main Service Function ---
# (process_message_for_flow, _start_specific_flow, _handle_active_flow_step, _trigger_new_flow,
#  _evaluate_transition_condition, _transition_to_step)
# These functions will now use the Pydantic-enhanced _execute_step_actions.
# Their core logic for flow control, state management, and transition evaluation remains
# largely the same as defined in message #55 / #56.
# For brevity, I will re-paste them and integrate Pydantic where `_execute_step_actions` is called
# or where configs are prepared for it.

def _clear_contact_flow_state(contact: Contact, error: bool = False):
    deleted_count, _ = ContactFlowState.objects.filter(contact=contact).delete()
    if deleted_count > 0:
        logger.info(f"Cleared flow state for contact {contact.whatsapp_id}." + (" Due to an error." if error else ""))

def _execute_step_actions(step: FlowStep, contact: Contact, flow_context: dict, is_re_execution: bool = False):
    actions_to_perform = []
    raw_step_config = step.config or {} 
    current_step_context = flow_context.copy() 

    logger.debug(
        f"Executing actions for step '{step.name}' (type: {step.step_type}) "
        f"for contact {contact.whatsapp_id}. Raw Config: {raw_step_config}"
    )

    if step.step_type == 'send_message':
        try:
            send_message_config = StepConfigSendMessage.model_validate(raw_step_config) # Pydantic v2
            actual_message_type = send_message_config.message_type
            data_payload_for_api = {} 
            final_api_data_structure = {} # This will be the content of 'data' for send_whatsapp_message

            if actual_message_type == "text" and send_message_config.text:
                text_content = send_message_config.text
                resolved_body = _resolve_value(text_content.body, current_step_context, contact)
                final_api_data_structure = {'body': resolved_body, 'preview_url': text_content.preview_url}
            
            elif actual_message_type in ['image', 'document', 'audio', 'video', 'sticker'] and getattr(send_message_config, actual_message_type):
                media_conf: MediaMessagePayload = getattr(send_message_config, actual_message_type)
                media_data_to_send = {}
                
                if MEDIA_ASSET_ENABLED and media_conf.asset_pk:
                    try:
                        asset = MediaAsset.objects.get(pk=media_conf.asset_pk)
                        if asset.status == 'synced' and asset.whatsapp_media_id and not asset.is_whatsapp_id_potentially_expired():
                            media_data_to_send['id'] = asset.whatsapp_media_id
                            logger.info(f"Using MediaAsset {asset.pk} ('{asset.name}') with WA ID: {asset.whatsapp_media_id}")
                        else: # Asset not usable, try direct id/link from config as fallback
                            logger.warning(f"MediaAsset {asset.pk} ('{asset.name}') not usable. Status: {asset.status}. Trying direct id/link from config.")
                            if media_conf.id: media_data_to_send['id'] = _resolve_value(media_conf.id, current_step_context, contact)
                            elif media_conf.link: media_data_to_send['link'] = _resolve_value(media_conf.link, current_step_context, contact)
                    except MediaAsset.DoesNotExist:
                        logger.error(f"MediaAsset pk={media_conf.asset_pk} not found. Trying direct id/link from config.")
                        if media_conf.id: media_data_to_send['id'] = _resolve_value(media_conf.id, current_step_context, contact)
                        elif media_conf.link: media_data_to_send['link'] = _resolve_value(media_conf.link, current_step_context, contact)
                elif media_conf.id:
                    media_data_to_send['id'] = _resolve_value(media_conf.id, current_step_context, contact)
                elif media_conf.link:
                    media_data_to_send['link'] = _resolve_value(media_conf.link, current_step_context, contact)

                if not media_data_to_send:
                    logger.error(f"No valid media source for {actual_message_type} in step '{step.name}'.")
                else:
                    if media_conf.caption:
                        media_data_to_send['caption'] = _resolve_value(media_conf.caption, current_step_context, contact)
                    if actual_message_type == 'document' and media_conf.filename:
                        media_data_to_send['filename'] = _resolve_value(media_conf.filename, current_step_context, contact)
                    # WhatsApp API expects payload like: {"image": {"id": "..."}} or {"document": {"link": "...", "filename": "..."}}
                    final_api_data_structure = {actual_message_type: media_data_to_send} 
            
            elif actual_message_type == "interactive" and send_message_config.interactive:
                interactive_payload_dict = send_message_config.interactive.model_dump(exclude_none=True, by_alias=True) # Pydantic v2
                interactive_type_from_payload = interactive_payload_dict.get('type') # button, list etc.
                
                validated_sub_payload = None
                if interactive_type_from_payload == 'button':
                    validated_sub_payload = InteractiveButtonMessagePayload.model_validate(interactive_payload_dict).model_dump(exclude_none=True, by_alias=True) # Pydantic v2
                elif interactive_type_from_payload == 'list':
                    validated_sub_payload = InteractiveListMessagePayload.model_validate(interactive_payload_dict).model_dump(exclude_none=True, by_alias=True) # Pydantic v2
                # TODO: Add other interactive types (product, product_list)
                
                if validated_sub_payload:
                    resolved_interactive_str = _resolve_value(json.dumps(validated_sub_payload), current_step_context, contact)
                    final_api_data_structure = json.loads(resolved_interactive_str) # This is the direct data for 'interactive' type
                else:
                    logger.warning(f"Unknown or unhandled interactive message subtype '{interactive_type_from_payload}' in step '{step.name}'.")

            elif actual_message_type == "template" and send_message_config.template:
                template_payload_dict = send_message_config.template.model_dump(exclude_none=True, by_alias=True) # Pydantic v2
                if 'components' in template_payload_dict and template_payload_dict['components']:
                    template_payload_dict['components'] = _resolve_template_components(
                        template_payload_dict['components'], current_step_context, contact
                    )
                final_api_data_structure = template_payload_dict
            
            elif actual_message_type == "contacts" and send_message_config.contacts:
                contacts_list_of_dicts = [c.model_dump(exclude_none=True, by_alias=True) for c in send_message_config.contacts] # Pydantic v2
                resolved_contacts = _resolve_value(contacts_list_of_dicts, current_step_context, contact)
                final_api_data_structure = {"contacts": resolved_contacts}

            elif actual_message_type == "location" and send_message_config.location:
                location_dict = send_message_config.location.model_dump(exclude_none=True, by_alias=True) # Pydantic v2
                final_api_data_structure = {"location": _resolve_value(location_dict, current_step_context, contact)}

            if final_api_data_structure:
                actions_to_perform.append({
                    'type': 'send_whatsapp_message',
                    'recipient_wa_id': contact.whatsapp_id,
                    'message_type': actual_message_type, # This matches the key in the 'data' payload for WA API
                    'data': final_api_data_structure
                })
            elif actual_message_type:
                 logger.warning(f"No data payload generated for message_type '{actual_message_type}' in step '{step.name}'. Pydantic Config: {send_message_config.model_dump_json(indent=2) if send_message_config else None}")

        except ValidationError as e:
            logger.error(f"Pydantic validation error for 'send_message' step '{step.name}' config: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e:
            logger.error(f"Unexpected error processing 'send_message' step '{step.name}': {e}", exc_info=True)

    elif step.step_type == 'question':
        try:
            question_config = StepConfigQuestion.model_validate(raw_step_config) # Pydantic v2
            if question_config.message_config:
                try:
                    # Validate the nested message_config as if it were a StepConfigSendMessage
                    temp_msg_pydantic_config = StepConfigSendMessage.model_validate(question_config.message_config) # Pydantic v2
                    dummy_send_step = FlowStep(name=f"{step.name}_prompt", step_type="send_message", config=temp_msg_pydantic_config.model_dump()) # Pydantic v2
                    send_actions, _ = _execute_step_actions(dummy_send_step, contact, current_step_context)
                    actions_to_perform.extend(send_actions)
                except ValidationError as ve:
                    logger.error(f"Pydantic validation error for 'message_config' within 'question' step '{step.name}': {ve.errors()}", exc_info=False)
            
            if question_config.reply_config:
                current_step_context['_question_awaiting_reply_for'] = {
                    'variable_name': question_config.reply_config.save_to_variable,
                    'expected_type': question_config.reply_config.expected_type,
                    'validation_regex': question_config.reply_config.validation_regex,
                    'original_question_step_id': step.id 
                }
                logger.debug(f"Step '{step.name}' is a question, awaiting reply for: {question_config.reply_config.save_to_variable}")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'question' step '{step.name}' failed: {e.errors()}", exc_info=False)

    elif step.step_type == 'action':
        try:
            action_step_config = StepConfigAction.model_validate(raw_step_config) # Pydantic v2
            for action_item_conf in action_step_config.actions_to_run:
                action_type = action_item_conf.action_type
                if action_type == 'set_context_variable':
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    current_step_context[action_item_conf.variable_name] = resolved_value
                    logger.info(f"Action: Set context var '{action_item_conf.variable_name}' to '{resolved_value}'.")
                elif action_type == 'update_contact_field':
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    _update_contact_data(contact, action_item_conf.field_path, resolved_value)
                elif action_type == 'update_customer_profile':
                    _update_customer_profile_data(contact, action_item_conf.fields_to_update, current_step_context) # fields_to_update is already a dict
                elif action_type == 'switch_flow':
                    resolved_initial_context = _resolve_value(action_item_conf.initial_context_template, current_step_context, contact)
                    resolved_msg_body = _resolve_value(action_item_conf.message_to_evaluate_for_new_flow, current_step_context, contact) if action_item_conf.message_to_evaluate_for_new_flow else None
                    actions_to_perform.append({
                        'type': '_internal_command_switch_flow',
                        'target_flow_name': action_item_conf.target_flow_name,
                        'initial_context': resolved_initial_context if isinstance(resolved_initial_context, dict) else {},
                        'new_flow_trigger_message_body': resolved_msg_body
                    })
                    logger.info(f"Action: Queued switch to flow '{action_item_conf.target_flow_name}'.")
                    break 
                else:
                    logger.warning(f"Unknown action_type '{action_type}' in step '{step.name}'.")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'action' step '{step.name}' failed: {e.errors()}", exc_info=False)

    elif step.step_type == 'end_flow':
        try:
            end_flow_config = StepConfigEndFlow.model_validate(raw_step_config) # Pydantic v2
            if end_flow_config.message_config:
                # Validate and process this message_config similar to a 'send_message' step's config
                try:
                    final_msg_pydantic_config = StepConfigSendMessage.model_validate(end_flow_config.message_config) # Pydantic v2
                    dummy_end_msg_step = FlowStep(name=f"{step.name}_final_msg", step_type="send_message", config=final_msg_pydantic_config.model_dump()) # Pydantic v2
                    send_actions, _ = _execute_step_actions(dummy_end_msg_step, contact, current_step_context)
                    actions_to_perform.extend(send_actions)
                except ValidationError as ve:
                     logger.error(f"Pydantic validation for 'message_config' in 'end_flow' step '{step.name}': {ve.errors()}", exc_info=False)
            logger.info(f"Executing 'end_flow' step '{step.name}'.")
            # Actual state clearing is handled by process_message_for_flow or _transition_to_step
            actions_to_perform.append({'type': '_internal_command_clear_flow_state'})
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'end_flow' step '{step.name}' config: {e.errors()}", exc_info=False)

    elif step.step_type == 'human_handover':
        try:
            handover_config = StepConfigHumanHandover.model_validate(raw_step_config) # Pydantic v2
            logger.info(f"Executing 'human_handover' step '{step.name}'.")
            if handover_config.pre_handover_message_text and not is_re_execution:
                resolved_msg = _resolve_value(handover_config.pre_handover_message_text, current_step_context, contact)
                actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_msg}})
            
            contact.needs_human_intervention = True
            contact.intervention_requested_at = timezone.now()
            contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
            logger.info(f"Contact {contact.whatsapp_id} flagged for human intervention.")
            notification_info = handover_config.notification_details or f"Contact {contact.name or contact.whatsapp_id} requires help."
            logger.info(f"HUMAN INTERVENTION NOTIFICATION: {notification_info}. Context: {current_step_context}")
            # TODO: Implement actual agent notification logic
            actions_to_perform.append({'type': '_internal_command_clear_flow_state'}) # Signal state clear
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'human_handover' step '{step.name}' failed: {e.errors()}", exc_info=False)

    elif step.step_type in ['condition', 'wait_for_reply', 'start_flow_node']:
        logger.debug(f"'{step.step_type}' step '{step.name}' processed. No direct actions from this function.")
    else:
        logger.warning(f"Unhandled step_type: '{step.step_type}' for step '{step.name}'.")

    return actions_to_perform, current_step_context


# --- All other helper functions from message #56 and #55 ---
# _handle_active_flow_step, _trigger_new_flow, _evaluate_transition_condition,
# _transition_to_step, _update_contact_data, _update_customer_profile_data
# These need to be pasted here, ensuring their calls to _execute_step_actions
# are compatible with what _execute_step_actions now returns and how configs are handled.

def _handle_active_flow_step(contact_flow_state: ContactFlowState, contact: Contact, message_data: dict, incoming_message_obj: Message):
    current_step = contact_flow_state.current_step
    flow_context = contact_flow_state.flow_context_data if contact_flow_state.flow_context_data is not None else {}
    actions = []
    logger.debug(f"Evaluating transitions for step '{current_step.name}' (type: {current_step.step_type}) for contact {contact.whatsapp_id}")
    transitions = FlowTransition.objects.filter(current_step=current_step).select_related('next_step').order_by('priority')
    next_step_to_transition_to = None
    for transition in transitions:
        if _evaluate_transition_condition(transition, contact, message_data, flow_context, incoming_message_obj):
            next_step_to_transition_to = transition.next_step
            logger.info(f"Transition condition met: From '{current_step.name}' to '{next_step_to_transition_to.name}'.")
            break
    if next_step_to_transition_to:
        # _transition_to_step now returns actions and the *final* context after the new step's execution
        actions, _ = _transition_to_step( # We don't need the returned context here directly
            contact_flow_state, next_step_to_transition_to, flow_context, contact, message_data
        )
    else: # No transition condition met - Fallback logic
        fallback_config = current_step.config.get('fallback_config', {})
        max_fallbacks = fallback_config.get('max_retries', 2) 
        current_fallback_count = flow_context.get('_fallback_count', 0)

        if fallback_config.get('action') == 're_prompt' and \
           current_step.step_type in ['send_message', 'question'] and \
           current_fallback_count < max_fallbacks:
            logger.info(f"Re-prompting step '{current_step.name}' (Attempt {current_fallback_count + 1}).")
            # Update context within the atomic transaction of process_message_for_flow
            flow_context['_fallback_count'] = current_fallback_count + 1 
            # Re-saving of context is handled by process_message_for_flow based on returned context
            # from _execute_step_actions
            step_actions, updated_context = _execute_step_actions(current_step, contact, flow_context, is_re_execution=True)
            actions.extend(step_actions)
            # Update flow_context_data if changed by re-execution
            if ContactFlowState.objects.filter(pk=contact_flow_state.pk).exists():
                contact_flow_state.flow_context_data = updated_context
                contact_flow_state.save(update_fields=['flow_context_data'])

        elif fallback_config.get('fallback_message_text'):
            resolved_fallback_text = _resolve_value(fallback_config['fallback_message_text'], flow_context, contact)
            actions.append({
                'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                'message_type': 'text', 'data': {'body': resolved_fallback_text}
            })
            # Consider if a handover should happen after this message
            if fallback_config.get('handover_after_message', False):
                 actions.append({'type': '_internal_command_clear_flow_state'}) # Signal handover
                 contact.needs_human_intervention = True
                 contact.intervention_requested_at = timezone.now()
                 contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
                 logger.info(f"Fallback message sent, initiating human handover for {contact.whatsapp_id}.")


        elif fallback_config.get('action') == 'human_handover' or \
             (current_step.step_type in ['question'] and current_fallback_count >= max_fallbacks):
            logger.info(f"Fallback: Initiating human handover for {contact.whatsapp_id}.")
            pre_handover_msg = fallback_config.get('pre_handover_message_text', "I'm unable to proceed. Let me connect you to an agent.")
            if pre_handover_msg: # Only send if defined
                 resolved_msg = _resolve_value(pre_handover_msg, flow_context, contact)
                 actions.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_msg}})
            actions.append({'type': '_internal_command_clear_flow_state'}) # Signal handover
            contact.needs_human_intervention = True
            contact.intervention_requested_at = timezone.now()
            contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
        else:
            logger.info(f"No transition met for step '{current_step.name}' and no specific fallback action taken for {contact.whatsapp_id}.")
            # Potentially send a generic "I don't understand" message if nothing else is configured.
            # actions.append({'type': 'send_whatsapp_message', ... 'body': "Sorry, I didn't understand that."})

    return actions


def _trigger_new_flow(contact: Contact, message_data: dict, incoming_message_obj: Message):
    actions = []
    flow_context = {} 
    message_text_body = None
    if message_data.get('type') == 'text':
        message_text_body = message_data.get('text', {}).get('body', '').lower().strip()
    
    triggered_flow = None
    # Consider adding a priority to Flows if multiple could be triggered by same keyword
    active_flows = Flow.objects.filter(is_active=True).order_by('name') # Consistent ordering

    for flow_candidate in active_flows:
        if message_text_body and isinstance(flow_candidate.trigger_keywords, list):
            for keyword in flow_candidate.trigger_keywords:
                if isinstance(keyword, str) and keyword.lower() in message_text_body: # "contains" match
                    triggered_flow = flow_candidate
                    logger.info(f"Keyword '{keyword}' triggered flow '{flow_candidate.name}' for contact {contact.whatsapp_id}.")
                    break
        if triggered_flow:
            break
    
    if triggered_flow:
        entry_point_step = FlowStep.objects.filter(flow=triggered_flow, is_entry_point=True).first()
        if entry_point_step:
            logger.info(f"Starting flow '{triggered_flow.name}' for contact {contact.whatsapp_id} at entry step '{entry_point_step.name}'.")
            contact_flow_state, created = ContactFlowState.objects.update_or_create(
                contact=contact,
                defaults={
                    'current_flow': triggered_flow,
                    'current_step': entry_point_step,
                    'flow_context_data': flow_context, # Starts empty
                    'started_at': timezone.now(),
                    'last_updated_at': timezone.now()
                }
            )
            if not created:
                logger.warning(f"Overwriting existing flow state for contact {contact.whatsapp_id} to start new flow '{triggered_flow.name}'.")
                contact_flow_state.current_flow = triggered_flow
                contact_flow_state.current_step = entry_point_step
                contact_flow_state.flow_context_data = flow_context
                contact_flow_state.started_at = timezone.now()
                contact_flow_state.last_updated_at = timezone.now()
                contact_flow_state.save()

            step_actions, updated_flow_context = _execute_step_actions(entry_point_step, contact, flow_context)
            actions.extend(step_actions)
            if contact_flow_state.flow_context_data != updated_flow_context:
                contact_flow_state.flow_context_data = updated_flow_context
                contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])
        else:
            logger.error(f"Flow '{triggered_flow.name}' is active but has no entry point step defined.")
    else:
        logger.info(f"No active flow triggered for contact {contact.whatsapp_id} with message: {message_text_body[:100] if message_text_body else message_data.get('type')}")
    return actions

def _evaluate_transition_condition(transition: FlowTransition, contact: Contact, message_data: dict, flow_context: dict, incoming_message_obj: Message) -> bool:
    # This function is from message #56 - it's quite comprehensive.
    # For Pydantic integration here, you'd define Pydantic models for each condition_type's config
    # and parse transition.condition_config into the appropriate model.
    config = transition.condition_config
    if not isinstance(config, dict):
        logger.warning(f"Transition {transition.id} has invalid condition_config (not a dict): {config}")
        return False
    condition_type = config.get('type')
    logger.debug(f"Evaluating condition type '{condition_type}' for transition {transition.id} of step '{transition.current_step.name}'. Context: {flow_context}, Message Type: {message_data.get('type')}")

    if condition_type == 'always_true': return True

    user_text = ""
    if message_data.get('type') == 'text' and isinstance(message_data.get('text'), dict):
        user_text = message_data.get('text', {}).get('body', '').strip()

    interactive_reply_id = None
    nfm_response_data = None # For NFM (Non-Facebook Message) replies
    if message_data.get('type') == 'interactive' and isinstance(message_data.get('interactive'), dict):
        interactive_payload = message_data.get('interactive', {})
        interactive_type_from_payload = interactive_payload.get('type') # button_reply, list_reply, nfm_reply
        if interactive_type_from_payload == 'button_reply' and isinstance(interactive_payload.get('button_reply'), dict):
            interactive_reply_id = interactive_payload.get('button_reply', {}).get('id')
        elif interactive_type_from_payload == 'list_reply' and isinstance(interactive_payload.get('list_reply'), dict):
            interactive_reply_id = interactive_payload.get('list_reply', {}).get('id')
        elif interactive_type_from_payload == 'nfm_reply' and isinstance(interactive_payload.get('nfm_reply'), dict):
            nfm_payload = interactive_payload.get('nfm_reply', {})
            response_json_str = nfm_payload.get('response_json')
            if response_json_str:
                try: nfm_response_data = json.loads(response_json_str)
                except json.JSONDecodeError: logger.warning(f"Could not parse nfm_reply response_json for transition {transition.id}")

    # Condition type implementations
    if condition_type == 'user_reply_matches_keyword':
        keyword = config.get('keyword', '').strip()
        case_sensitive = config.get('case_sensitive', False)
        return (keyword == user_text) if case_sensitive else (keyword.lower() == user_text.lower())
    elif condition_type == 'user_reply_contains_keyword':
        keyword = config.get('keyword', '').strip()
        case_sensitive = config.get('case_sensitive', False)
        return (keyword in user_text) if case_sensitive else (keyword.lower() in user_text.lower())
    elif condition_type == 'interactive_reply_id_equals':
        return interactive_reply_id == config.get('reply_id')
    elif condition_type == 'message_type_is':
        return message_data.get('type') == config.get('message_type')
    elif condition_type == 'user_reply_matches_regex':
        regex = config.get('regex')
        if regex and user_text:
            try: return bool(re.match(regex, user_text))
            except re.error as e: logger.error(f"Invalid regex in transition {transition.id}: {regex}. Error: {e}"); return False
        return False
    elif condition_type == 'user_reply_is_email':
        email_regex = config.get('regex', r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        if user_text:
            try: return bool(re.match(email_regex, user_text))
            except re.error as e: logger.error(f"Invalid email regex in transition {transition.id}: {email_regex}. Error: {e}"); return False
        return False
    elif condition_type == 'user_reply_is_number':
        if not user_text: return False
        try:
            num_value = float(user_text) if config.get('allow_decimal', False) else int(user_text)
            if config.get('min_value') is not None and num_value < config.get('min_value'): return False
            if config.get('max_value') is not None and num_value > config.get('max_value'): return False
            return True
        except ValueError: return False
    elif condition_type == 'variable_equals':
        actual_value = _get_value_from_context_or_contact(config.get('variable_name'), flow_context, contact)
        # Ensure consistent type for comparison, often string comparison is safest for context vars
        return str(actual_value) == str(config.get('value'))
    elif condition_type == 'variable_exists':
        return _get_value_from_context_or_contact(config.get('variable_name'), flow_context, contact) is not None
    elif condition_type == 'variable_contains':
        actual_value = _get_value_from_context_or_contact(config.get('variable_name'), flow_context, contact)
        expected_item = config.get('value')
        if isinstance(actual_value, str) and isinstance(expected_item, str): return expected_item in actual_value
        if isinstance(actual_value, list): return expected_item in actual_value
        return False
    elif condition_type == 'nfm_response_field_equals' and nfm_response_data:
        field_path, expected_value = config.get('field_path'), config.get('value')
        actual_val_from_nfm = nfm_response_data
        if field_path:
            for part in field_path.split('.'):
                if isinstance(actual_val_from_nfm, dict): actual_val_from_nfm = actual_val_from_nfm.get(part)
                else: actual_val_from_nfm = None; break
        return actual_val_from_nfm == expected_value
    
    # --- Question Reply Validation Logic (part of _evaluate_transition_condition) ---
    question_expectation = flow_context.get('_question_awaiting_reply_for')
    if question_expectation and isinstance(question_expectation, dict):
        expected_reply_type = question_expectation.get('expected_type')
        validation_regex_ctx = question_expectation.get('validation_regex')
        variable_to_save_name = question_expectation.get('variable_name')
        reply_is_valid_for_question = False
        value_to_save_from_reply = None

        if expected_reply_type == 'text':
            value_to_save_from_reply = user_text
            reply_is_valid_for_question = bool(user_text) # Basic check: not empty for text
        elif expected_reply_type == 'email':
            email_r = validation_regex_ctx or r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if user_text and re.match(email_r, user_text):
                value_to_save_from_reply = user_text; reply_is_valid_for_question = True
        elif expected_reply_type == 'number':
            if user_text:
                try:
                    # Consider if question config should specify float/int for number type
                    value_to_save_from_reply = float(user_text) if '.' in user_text or (validation_regex_ctx and '.' in validation_regex_ctx) else int(user_text)
                    reply_is_valid_for_question = True
                except ValueError: pass
        elif expected_reply_type == 'interactive_id':
            value_to_save_from_reply = interactive_reply_id
            reply_is_valid_for_question = interactive_reply_id is not None
        
        # Apply custom regex from question step if type validation didn't make it valid yet
        if validation_regex_ctx and not reply_is_valid_for_question and user_text:
            if re.match(validation_regex_ctx, user_text):
                value_to_save_from_reply = user_text # Or try to convert based on expected type if regex is just for format
                reply_is_valid_for_question = True
        
        if condition_type == 'question_reply_is_valid' and variable_to_save_name:
            should_be_valid_config = config.get('value', True) # Transition expects reply to be valid (or invalid)
            if reply_is_valid_for_question == should_be_valid_config:
                if reply_is_valid_for_question: # Only save if the reply was actually valid
                    flow_context[variable_to_save_name] = value_to_save_from_reply
                    logger.info(f"Saved valid reply for '{variable_to_save_name}': {value_to_save_from_reply}")
                # If should_be_valid_config is False, and reply_is_valid_for_question is False, condition is met.
                return True 
            return False # Reply validity did not match what transition expected

    elif condition_type == 'user_requests_human': # From message #55
        human_request_keywords = config.get('keywords', ['help', 'support', 'agent', 'human', 'operator'])
        if user_text and isinstance(human_request_keywords, list):
            user_text_lower = user_text.lower()
            for keyword in human_request_keywords:
                if isinstance(keyword, str) and keyword.lower() in user_text_lower:
                    logger.info(f"User requested human agent with keyword: '{keyword}'")
                    return True
        return False

    logger.warning(f"Unknown or unhandled condition type: '{condition_type}' for transition {transition.id} or conditions not met.")
    return False


def _transition_to_step(contact_flow_state: ContactFlowState, next_step: FlowStep, current_flow_context: dict, contact: Contact, message_data: dict):
    logger.info(f"Transitioning contact {contact.whatsapp_id} from '{contact_flow_state.current_step.name}' to '{next_step.name}' in flow '{contact_flow_state.current_flow.name}'.")
    
    if contact_flow_state.current_step.step_type == 'question':
        current_flow_context.pop('_question_awaiting_reply_for', None)
        current_flow_context.pop('_fallback_count', None) # Also reset fallback count from question
        logger.debug(f"Cleared question expectation and fallback count for '{contact_flow_state.current_step.name}'.")

    # Update state to new step
    original_flow_pk = contact_flow_state.current_flow.pk # Save in case state is cleared
    contact_flow_state.current_step = next_step
    contact_flow_state.last_updated_at = timezone.now()
    # IMPORTANT: flow_context_data is not saved yet, _execute_step_actions will update it.

    actions_from_new_step, final_context_after_new_step = _execute_step_actions(
        next_step, contact, current_flow_context.copy() # Pass a copy of context
    )
    
    # Check if contact is still in ANY flow after executing actions (might have been cleared by end_flow/human_handover/switch_flow)
    # Re-fetch the state, as _execute_step_actions might have cleared it or switched flows.
    updated_contact_flow_state = ContactFlowState.objects.filter(contact=contact).first()

    if updated_contact_flow_state:
        if updated_contact_flow_state.current_flow_id == original_flow_pk and updated_contact_flow_state.current_step_id == next_step.id:
            # Still in the same flow and intended next step, save the context from this step's execution
            updated_contact_flow_state.flow_context_data = final_context_after_new_step
            updated_contact_flow_state.save()
            logger.debug(f"Saved updated context for contact {contact.whatsapp_id} at step '{next_step.name}'.")
        elif updated_contact_flow_state.current_flow_id != original_flow_pk:
            logger.info(f"Contact {contact.whatsapp_id} switched to a new flow ('{updated_contact_flow_state.current_flow.name}'). Old flow context not saved here.")
        else:
            # State exists but not for this flow/step, could be an edge case or error in logic
            logger.warning(f"ContactFlowState for {contact.whatsapp_id} exists but current_step/flow does not match transition target. State: {updated_contact_flow_state}")
    else:
        logger.info(f"ContactFlowState for contact {contact.whatsapp_id} was cleared or switched during step '{next_step.name}' execution. No context saved for old state.")
        
    return actions_from_new_step, final_context_after_new_step # Return actions and the context that was relevant for *this* step's execution


def _update_contact_data(contact: Contact, field_path: str, value_to_set):
    # ... (same as in message #56) ...
    if not field_path: logger.warning("Empty field_path for _update_contact_data."); return
    parts = field_path.split('.')
    if parts[0] == 'custom_fields':
        if not isinstance(contact.custom_fields, dict): contact.custom_fields = {}
        current_level = contact.custom_fields
        for i, key in enumerate(parts[1:-1]):
            current_level = current_level.setdefault(key, {})
            if not isinstance(current_level, dict): logger.error(f"Path error in custom_fields: '{key}' not a dict."); return
        if len(parts) > 1:
            current_level[parts[-1]] = value_to_set
            contact.save(update_fields=['custom_fields'])
            logger.info(f"Updated contact {contact.whatsapp_id} custom_fields.{'.'.join(parts[1:])} = {value_to_set}")
        elif isinstance(value_to_set, dict): # replace entire custom_fields
            contact.custom_fields = value_to_set
            contact.save(update_fields=['custom_fields'])
        else: logger.warning("Cannot replace custom_fields with non-dict.")
    elif hasattr(contact, parts[0]) and len(parts) == 1:
        field_name = parts[0]
        if field_name.lower() in ['id', 'pk', 'whatsapp_id']: logger.warning(f"Denied update to protected field {field_name}."); return
        setattr(contact, field_name, value_to_set)
        contact.save(update_fields=[field_name])
        logger.info(f"Updated contact {contact.whatsapp_id} field {field_name} = {value_to_set}")
    else: logger.warning(f"Field path '{field_path}' not found or not updatable on Contact.")

def _update_customer_profile_data(contact: Contact, fields_to_update_config: dict, flow_context: dict):
    # ... (same as in message #56, ensure CustomerProfile is imported) ...
    if not fields_to_update_config: return
    profile, created = CustomerProfile.objects.get_or_create(contact=contact)
    if created: logger.info(f"Created CustomerProfile for contact {contact.whatsapp_id}")
    changed_fields = []
    for field_path, value_template in fields_to_update_config.items():
        resolved_value = _resolve_value(value_template, flow_context, contact)
        parts = field_path.split('.')
        try:
            if len(parts) == 1:
                if hasattr(profile, parts[0]) and parts[0].lower() not in ['id', 'pk', 'contact', 'contact_id']:
                    setattr(profile, parts[0], resolved_value)
                    if parts[0] not in changed_fields: changed_fields.append(parts[0])
                else: logger.warning(f"CustomerProfile field '{parts[0]}' not found or protected.")
            elif parts[0] in ['preferences', 'custom_attributes'] and len(parts) > 1:
                json_field_name = parts[0]
                json_data = getattr(profile, json_field_name)
                if not isinstance(json_data, dict): json_data = {}
                current_level = json_data
                for key in parts[1:-1]:
                    current_level = current_level.setdefault(key, {})
                    if not isinstance(current_level, dict): logger.warning(f"Path error in profile {json_field_name} at '{key}'."); current_level = None; break
                if current_level is not None:
                    current_level[parts[-1]] = resolved_value
                    setattr(profile, json_field_name, json_data)
                    if json_field_name not in changed_fields: changed_fields.append(json_field_name)
            else: logger.warning(f"Unsupported field path for CustomerProfile: {field_path}")
        except Exception as e: logger.error(f"Error updating CustomerProfile field '{field_path}': {e}", exc_info=True)
    if changed_fields:
        profile.last_updated_from_conversation = timezone.now()
        if 'last_updated_from_conversation' not in changed_fields: changed_fields.append('last_updated_from_conversation')
        profile.save(update_fields=changed_fields)
        logger.info(f"CustomerProfile for {contact.whatsapp_id} updated fields: {changed_fields}")
    elif created: # If only created and no fields changed, still update timestamp
        profile.last_updated_from_conversation = timezone.now()
        profile.save(update_fields=['last_updated_from_conversation'])