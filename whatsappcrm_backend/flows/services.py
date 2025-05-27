# whatsappcrm_backend/flows/services.py

import logging
import json
import re
from typing import List, Dict, Any, Optional, Union, Literal

from django.utils import timezone
from django.db import transaction
from pydantic import BaseModel, ValidationError, field_validator, root_validator, Field

from conversations.models import Contact, Message # Assuming direct import is fine
from .models import Flow, FlowStep, FlowTransition, ContactFlowState
from customer_data.models import CustomerProfile # Assuming this import is correct
try:
    from media_manager.models import MediaAsset # Assuming direct import
    MEDIA_ASSET_ENABLED = True
except ImportError:
    MEDIA_ASSET_ENABLED = False

logger = logging.getLogger(__name__)

if not MEDIA_ASSET_ENABLED:
    logger.warning("MediaAsset model not found or could not be imported. MediaAsset functionality (e.g., 'asset_pk') will be disabled in flows.")

# --- Pydantic Models (As provided by you, with minor clarifications/enhancements) ---
class BasePydanticConfig(BaseModel):
    class Config:
        extra = 'allow' # Allows extra fields not defined, useful for flexible configs
                        # Consider 'ignore' to drop them, or 'forbid' to raise error if strictness is needed.

class TextMessageContent(BasePydanticConfig):
    body: str = Field(..., min_length=1, max_length=4096)
    preview_url: bool = False

class MediaMessageContent(BasePydanticConfig):
    asset_pk: Optional[int] = None
    id: Optional[str] = None # WhatsApp Media ID
    link: Optional[str] = None # Publicly accessible URL
    caption: Optional[str] = Field(default=None, max_length=1024)
    filename: Optional[str] = None # Used specifically for document type messages

    @root_validator(pre=False, skip_on_failure=True)
    def check_media_source(cls, values):
        asset_pk, media_id, link = values.get('asset_pk'), values.get('id'), values.get('link')
        if not MEDIA_ASSET_ENABLED and asset_pk:
            # This error will be caught by the Pydantic validation in _execute_step_actions
            raise ValueError("'asset_pk' provided but MediaAsset system is not enabled/imported.")
        if not (asset_pk or media_id or link):
            raise ValueError("One of 'asset_pk', 'id' (WhatsApp Media ID), or 'link' must be provided for media.")
        return values

class InteractiveButtonReply(BasePydanticConfig):
    id: str = Field(..., min_length=1, max_length=256)
    title: str = Field(..., min_length=1, max_length=20)

class InteractiveButton(BasePydanticConfig):
    type: Literal["reply"] = "reply" # WhatsApp only supports 'reply' type buttons in interactive messages
    reply: InteractiveButtonReply

class InteractiveButtonAction(BasePydanticConfig):
    buttons: List[InteractiveButton] = Field(..., min_items=1, max_items=3) # Max 3 buttons

class InteractiveHeader(BasePydanticConfig):
    type: Literal["text", "video", "image", "document"]
    text: Optional[str] = Field(default=None, max_length=60) # Required if type is 'text'
    # For media types in header, WA expects an object like:
    # image: Optional[Dict[str, str]] = None # e.g. {"link": "URL"} or {"id": "MEDIA_ID"}
    # document: Optional[Dict[str, str]] = None
    # video: Optional[Dict[str, str]] = None
    # These would need to be added if media headers are used, matching MediaMessageContent source logic.

class InteractiveBody(BasePydanticConfig):
    text: str = Field(..., min_length=1, max_length=1024)

class InteractiveFooter(BasePydanticConfig):
    text: str = Field(..., min_length=1, max_length=60)

class InteractiveListRow(BasePydanticConfig):
    id: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=24)
    description: Optional[str] = Field(default=None, max_length=72)

class InteractiveListSection(BasePydanticConfig):
    title: Optional[str] = Field(default=None, max_length=24)
    rows: List[InteractiveListRow] = Field(..., min_items=1, max_items=10) # Max 10 rows per section

class InteractiveListAction(BasePydanticConfig):
    button: str = Field(..., min_length=1, max_length=20) # Text of the button that opens the list
    sections: List[InteractiveListSection] = Field(..., min_items=1) # Min 1 section

class InteractiveMessagePayload(BasePydanticConfig): # Represents the 'interactive' object in WA API
    type: Literal["button", "list", "product", "product_list"]
    header: Optional[InteractiveHeader] = None
    body: InteractiveBody # Body is required for button and list types
    footer: Optional[InteractiveFooter] = None
    action: Union[InteractiveButtonAction, InteractiveListAction] # Extend with product/product_list actions if needed

class TemplateLanguage(BasePydanticConfig):
    code: str # e.g., "en_US", "es"

class TemplateParameter(BasePydanticConfig):
    type: Literal["text", "currency", "date_time", "image", "document", "video", "payload"]
    text: Optional[str] = None # For type 'text' and for URL button display text or payload button text part
    currency: Optional[Dict[str, Any]] = None # For type 'currency', e.g., {"fallback_value": "$10.99", "code": "USD", "amount_1000": 10990}
    date_time: Optional[Dict[str, Any]] = None # For type 'date_time', e.g., {"fallback_value": "Tomorrow"}
    image: Optional[Dict[str, Any]] = None # For type 'image', e.g., {"link": "URL"} or {"id": "MEDIA_ID"}
    document: Optional[Dict[str, Any]] = None # {"link": "URL", "filename":"fname.pdf"} or {"id": "MEDIA_ID", "filename":"fname.pdf"}
    video: Optional[Dict[str, Any]] = None # {"link": "URL"} or {"id": "MEDIA_ID"}
    payload: Optional[str] = None # For quick_reply button's postback payload

class TemplateComponent(BasePydanticConfig):
    type: Literal["header", "body", "button"]
    sub_type: Optional[Literal['url', 'quick_reply', 'call_button', 'catalog_button', 'mpm_button']] = None # For 'button' type
    parameters: Optional[List[TemplateParameter]] = None
    index: Optional[int] = None # For 'button' type with 'url' sub_type, to append to static URL in template

class TemplateMessageContent(BasePydanticConfig): # Represents the 'template' object for WA API
    name: str # Name of the pre-approved template
    language: TemplateLanguage # Language object, e.g. {"code": "en_US"}
    components: Optional[List[TemplateComponent]] = None

class ContactName(BasePydanticConfig):
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
    country_code: Optional[str] = None # ISO 3166-1 Alpha-2 code
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactEmail(BasePydanticConfig):
    email: Optional[str] = None
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactPhone(BasePydanticConfig):
    phone: Optional[str] = None # E.164 format preferably
    type: Optional[Literal['CELL', 'MAIN', 'IPHONE', 'HOME', 'WORK']] = None
    wa_id: Optional[str] = None # WhatsApp ID, if known

class ContactOrg(BasePydanticConfig):
    company: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None

class ContactUrl(BasePydanticConfig):
    url: Optional[str] = None # Standard URL
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactObject(BasePydanticConfig): # Represents one 'contact' object in the 'contacts' array for WA API
    addresses: Optional[List[ContactAddress]] = Field(default_factory=list)
    birthday: Optional[str] = None # YYYY-MM-DD format
    emails: Optional[List[ContactEmail]] = Field(default_factory=list)
    name: ContactName # Required
    org: Optional[ContactOrg] = None
    phones: Optional[List[ContactPhone]] = Field(default_factory=list)
    urls: Optional[List[ContactUrl]] = Field(default_factory=list)

class LocationMessageContent(BasePydanticConfig): # Represents the 'location' object for WA API
    longitude: float
    latitude: float
    name: Optional[str] = None
    address: Optional[str] = None

class StepConfigSendMessage(BasePydanticConfig):
    message_type: Literal["text", "image", "document", "audio", "video", "sticker", "interactive", "template", "contacts", "location"]
    # Direct payload fields matching message_type string
    text: Optional[TextMessageContent] = None
    image: Optional[MediaMessageContent] = None
    document: Optional[MediaMessageContent] = None
    audio: Optional[MediaMessageContent] = None
    video: Optional[MediaMessageContent] = None
    sticker: Optional[MediaMessageContent] = None # Sticker usually only takes 'id' or 'link'
    interactive: Optional[InteractiveMessagePayload] = None
    template: Optional[TemplateMessageContent] = None
    contacts: Optional[List[ContactObject]] = None # Array of contact objects, min 1
    location: Optional[LocationMessageContent] = None

    @root_validator(pre=False, skip_on_failure=True)
    def check_payload_exists_for_type(cls, values):
        msg_type = values.get('message_type')
        payload_specific_to_type = values.get(msg_type)

        if msg_type and payload_specific_to_type is None:
            raise ValueError(f"Payload for message_type '{msg_type}' (expected field '{msg_type}') is missing or null.")

        # Ensure all other message type payloads are None
        defined_payload_fields = {"text", "image", "document", "audio", "video", "sticker", "interactive", "template", "contacts", "location"}
        for field_name in defined_payload_fields:
            if field_name != msg_type and values.get(field_name) is not None:
                # This ensures FlowStep config is clean and only contains relevant payload.
                raise ValueError(f"Field '{field_name}' should not be present (or must be null) when message_type is '{msg_type}'.")

        if msg_type == 'interactive':
            interactive_payload = values.get('interactive') # This is InteractiveMessagePayload object
            if not interactive_payload or not getattr(interactive_payload, 'type', None):
                raise ValueError("For 'interactive' messages, the 'interactive' payload object must exist and itself specify an interactive 'type' (e.g., 'button', 'list').")
            
            interactive_internal_type = interactive_payload.type # 'button' or 'list'
            interactive_action = interactive_payload.action
            
            if interactive_internal_type == "button" and not isinstance(interactive_action, InteractiveButtonAction):
                raise ValueError("For interactive message type 'button', the 'action' field must be a valid InteractiveButtonAction.")
            if interactive_internal_type == "list" and not isinstance(interactive_action, InteractiveListAction):
                raise ValueError("For interactive message type 'list', the 'action' field must be a valid InteractiveListAction.")
            # Add similar checks for 'product', 'product_list' if you implement them
        return values

class ReplyConfig(BasePydanticConfig):
    save_to_variable: str = Field(..., min_length=1)
    expected_type: Literal["text", "email", "number", "interactive_id", "any"] = "any"
    validation_regex: Optional[str] = None

class StepConfigQuestion(BasePydanticConfig):
    message_config: Dict[str, Any] # This will be validated by StepConfigSendMessage
    reply_config: ReplyConfig

    @field_validator('message_config')
    def validate_message_config_structure(cls, v_dict):
        try:
            StepConfigSendMessage.model_validate(v_dict)
            return v_dict 
        except ValidationError as e:
            logger.error(f"Invalid message_config for question step: {e.errors()}", exc_info=False)
            raise ValueError(f"message_config for question is invalid: {e.errors()}")

class ActionItemConfig(BasePydanticConfig):
    action_type: Literal["set_context_variable", "update_contact_field", "update_customer_profile", "switch_flow"]
    variable_name: Optional[str] = None
    value_template: Optional[Any] = None 
    field_path: Optional[str] = None 
    fields_to_update: Optional[Dict[str, Any]] = None 
    target_flow_name: Optional[str] = None
    initial_context_template: Optional[Dict[str, Any]] = Field(default_factory=dict)
    message_to_evaluate_for_new_flow: Optional[str] = None 

    @root_validator(pre=False, skip_on_failure=True)
    def check_action_fields(cls, values):
        action_type = values.get('action_type')
        if action_type == 'set_context_variable':
            if values.get('variable_name') is None or 'value_template' not in values: 
                raise ValueError("For set_context_variable, 'variable_name' and 'value_template' are required.")
        elif action_type == 'update_contact_field':
            if not values.get('field_path') or 'value_template' not in values:
                raise ValueError("For update_contact_field, 'field_path' and 'value_template' are required.")
        elif action_type == 'update_customer_profile':
            if not values.get('fields_to_update') or not isinstance(values.get('fields_to_update'), dict):
                raise ValueError("For update_customer_profile, 'fields_to_update' (a dictionary) is required.")
        elif action_type == 'switch_flow':
            if not values.get('target_flow_name'):
                raise ValueError("For switch_flow, 'target_flow_name' is required.")
        return values

class StepConfigAction(BasePydanticConfig):
    actions_to_run: List[ActionItemConfig] = Field(default_factory=list, min_items=1)

class StepConfigHumanHandover(BasePydanticConfig):
    pre_handover_message_text: Optional[str] = None
    notification_details: Optional[str] = Field(default="Contact requires human assistance from flow.")

class StepConfigEndFlow(BasePydanticConfig):
    message_config: Optional[Dict[str, Any]] = None 

    @field_validator('message_config')
    def validate_message_config_structure(cls, v_dict):
        if v_dict is None:
            return None
        try:
            StepConfigSendMessage.model_validate(v_dict)
            return v_dict
        except ValidationError as e:
            logger.error(f"Invalid message_config for end_flow step: {e.errors()}", exc_info=False)
            raise ValueError(f"message_config for end_flow is invalid: {e.errors()}")

InteractiveMessagePayload.model_rebuild() # For Pydantic v1, ensure forward refs are handled
                                        # For Pydantic v2, this might not be strictly necessary depending on definition order


def _get_value_from_context_or_contact(variable_path: str, flow_context: dict, contact: Contact) -> Any:
    logger.debug(f"Resolving variable path: '{variable_path}' for contact {contact.whatsapp_id} (ID: {contact.id})")
    if not variable_path:
        logger.debug("Empty variable_path received.")
        return None

    parts = variable_path.split('.')
    source_object_name = parts[0]
    current_value = None

    if source_object_name == 'flow_context':
        current_value = flow_context
        path_to_traverse = parts[1:]
        logger.debug(f"Accessing flow_context. Path to traverse: {path_to_traverse}. Current context keys: {list(flow_context.keys())}")
    elif source_object_name == 'contact':
        current_value = contact
        path_to_traverse = parts[1:]
        logger.debug(f"Accessing contact attributes. Path to traverse: {path_to_traverse}")
    elif source_object_name == 'customer_profile':
        try:
            # Assuming 'customer_profile' is the related name from Contact to CustomerProfile
            current_value = contact.customer_profile 
            path_to_traverse = parts[1:]
            logger.debug(f"Accessing customer_profile attributes for contact {contact.id}. Path to traverse: {path_to_traverse}")
        except CustomerProfile.DoesNotExist:
            logger.debug(f"CustomerProfile does not exist for contact {contact.id} when trying to access '{variable_path}'")
            return None
        except AttributeError: 
            logger.warning(f"Contact {contact.id} has no 'customer_profile' related object (or it's None) for path '{variable_path}'")
            return None
    else: 
        current_value = flow_context
        path_to_traverse = parts # Assume full path is relative to flow_context
        logger.debug(f"Defaulting to flow_context for path '{variable_path}'. Path to traverse: {path_to_traverse}. Current context keys: {list(flow_context.keys())}")

    for i, part in enumerate(path_to_traverse):
        if current_value is None:
            logger.debug(f"Intermediate value became None at part '{part}' (index {i}) for path '{variable_path}'.")
            return None
        try:
            if isinstance(current_value, dict):
                current_value = current_value.get(part)
            elif hasattr(current_value, part):
                attr_or_method = getattr(current_value, part)
                if callable(attr_or_method):
                    try:
                        num_args = -1
                        if hasattr(attr_or_method, '__func__'): # Bound method
                            num_args = attr_or_method.__func__.__code__.co_argcount
                            # Expects 1 for 'self' if it's a simple no-arg instance method
                            if num_args == 1: 
                                current_value = attr_or_method()
                                logger.debug(f"Called method '{part}' from path '{variable_path}'.")
                            else: 
                                logger.debug(f"Method '{part}' requires {num_args-1} args (plus self), returning method itself for path '{variable_path}'.")
                                current_value = attr_or_method # Return method, don't call if args needed
                        elif hasattr(attr_or_method, '__code__'): # Regular function/static method
                            num_args = attr_or_method.__code__.co_argcount
                            if num_args == 0: 
                                current_value = attr_or_method()
                                logger.debug(f"Called function/static method '{part}' from path '{variable_path}'.")
                            else: 
                                logger.debug(f"Function '{part}' requires {num_args} args, returning function itself for path '{variable_path}'.")
                                current_value = attr_or_method
                        else: 
                            logger.debug(f"Unknown callable type for '{part}', returning as is for path '{variable_path}'.")
                            current_value = attr_or_method
                    except AttributeError as ae_callable:
                        logger.debug(f"AttributeError inspecting callable '{part}': {ae_callable}. Returning as is for path '{variable_path}'.")
                        current_value = attr_or_method 
                    except TypeError as te_callable: 
                        logger.warning(f"TypeError calling method/function '{part}' for path '{variable_path}': {te_callable}. Returning as is.")
                        current_value = attr_or_method 
                else: # Not callable, just an attribute
                    current_value = attr_or_method
            else: 
                logger.debug(f"Part '{part}' not found in current object for path '{variable_path}'. Current object type: {type(current_value)}, value: {str(current_value)[:100]}")
                return None
        except Exception as e: # Catch any other exception during attribute access
            logger.warning(f"Unexpected error accessing part '{part}' of path '{variable_path}': {e}", exc_info=True)
            return None
            
    resolved_val_str = str(current_value)
    logger.debug(f"Resolved path '{variable_path}' to value: '{resolved_val_str[:100]}{'...' if len(resolved_val_str) > 100 else ''}' (Type: {type(current_value)})")
    return current_value

def _resolve_value(template_value: Any, flow_context: dict, contact: Contact) -> Any:
    if isinstance(template_value, str):
        variable_pattern = re.compile(r"{{\s*([\w.]+)\s*}}")
        resolved_string = template_value
        
        for i in range(10): 
            original_string_for_iteration = resolved_string
            matches = list(variable_pattern.finditer(resolved_string))
            if not matches:
                break 

            new_parts = []
            last_end = 0
            for match in matches:
                new_parts.append(resolved_string[last_end:match.start()])
                var_path = match.group(1).strip()
                val = _get_value_from_context_or_contact(var_path, flow_context, contact)
                new_parts.append(str(val) if val is not None else '') 
                last_end = match.end()
            
            new_parts.append(resolved_string[last_end:])
            resolved_string = "".join(new_parts)

            if resolved_string == original_string_for_iteration : # No change in this iteration, break
                # This handles cases where all variables resolved to empty strings, or variables were not found.
                break
            if not variable_pattern.search(resolved_string): # No more patterns left
                break
            if i == 9:
                logger.warning(f"Template string resolution reached max iterations (10) for input: '{template_value}'. Result: '{resolved_string}'")
        return resolved_string
    elif isinstance(template_value, dict):
        return {k: _resolve_value(v, flow_context, contact) for k, v in template_value.items()}
    elif isinstance(template_value, list):
        return [_resolve_value(item, flow_context, contact) for item in template_value]
    return template_value

def _resolve_template_components(components_config: list, flow_context: dict, contact: Contact) -> list:
    if not components_config or not isinstance(components_config, list):
        logger.debug("_resolve_template_components: No components to resolve or invalid format.")
        return []
    try:
        resolved_components_list = json.loads(json.dumps(components_config)) # Deep copy
        logger.debug(f"Resolving template components. Initial count: {len(resolved_components_list)}. Initial data (sample): {str(resolved_components_list)[:200]}")

        for i, component in enumerate(resolved_components_list):
            if not isinstance(component, dict):
                logger.warning(f"Component at index {i} is not a dictionary, skipping: {component}")
                continue

            logger.debug(f"Resolving component {i}: Type '{component.get('type')}', SubType: '{component.get('sub_type')}'")
            if isinstance(component.get('parameters'), list):
                for j, param in enumerate(component['parameters']):
                    if not isinstance(param, dict):
                        logger.warning(f"Parameter at index {j} in component {i} is not a dictionary, skipping: {param}")
                        continue
                    
                    param_type = param.get('type')
                    logger.debug(f"Resolving component {i}, param {j}, type '{param_type}'. Param data: {param}")

                    if 'text' in param and isinstance(param['text'], str):
                        original_text = param['text']
                        param['text'] = _resolve_value(param['text'], flow_context, contact)
                        if original_text != param['text']: logger.debug(f"Resolved param text from '{original_text}' to: '{param['text']}'")
                    
                    if param_type in ['image', 'video', 'document'] and isinstance(param.get(param_type), dict):
                        media_obj = param[param_type]
                        if 'link' in media_obj and isinstance(media_obj['link'], str):
                            original_link = media_obj['link']
                            media_obj['link'] = _resolve_value(media_obj['link'], flow_context, contact)
                            if original_link != media_obj['link']: logger.debug(f"Resolved media link from '{original_link}' to: {media_obj['link']}")
                    
                    if component.get('type') == 'button' and param.get('type') == 'payload' and 'payload' in param and isinstance(param['payload'], str):
                        original_payload = param['payload']
                        param['payload'] = _resolve_value(param['payload'], flow_context, contact)
                        if original_payload != param['payload']: logger.debug(f"Resolved button payload from '{original_payload}' to: {param['payload']}")

                    if param_type == 'currency' and isinstance(param.get('currency'), dict) and 'fallback_value' in param['currency'] and isinstance(param['currency']['fallback_value'], str) :
                        original_fb_val = param['currency']['fallback_value']
                        param['currency']['fallback_value'] = _resolve_value(param['currency']['fallback_value'], flow_context, contact)
                        if original_fb_val != param['currency']['fallback_value']: logger.debug(f"Resolved currency fallback from '{original_fb_val}' to: {param['currency']['fallback_value']}")

                    if param_type == 'date_time' and isinstance(param.get('date_time'), dict) and 'fallback_value' in param['date_time'] and isinstance(param['date_time']['fallback_value'], str):
                        original_fb_val = param['date_time']['fallback_value']
                        param['date_time']['fallback_value'] = _resolve_value(param['date_time']['fallback_value'], flow_context, contact)
                        if original_fb_val != param['date_time']['fallback_value']: logger.debug(f"Resolved date_time fallback from '{original_fb_val}' to: {param['date_time']['fallback_value']}")
            
        logger.debug(f"Finished resolving template components. Final data (sample): {str(resolved_components_list)[:200]}")
        return resolved_components_list
    except Exception as e:
        logger.error(f"Error during _resolve_template_components: {e}. Original Config: {components_config}", exc_info=True)
        return components_config # Return original on error


def _clear_contact_flow_state(contact: Contact, error: bool = False, reason: str = ""):
    deleted_count, _ = ContactFlowState.objects.filter(contact=contact).delete()
    log_message = f"Cleared flow state for contact {contact.whatsapp_id} (ID: {contact.id})."
    if reason:
        log_message += f" Reason: {reason}."
    if error:
        log_message += " Due to an error." # Append only if error is true
    if deleted_count > 0:
        logger.info(log_message)
    else:
        log_suffix = reason or ("N/A" if not error else "Error, but no state found")
        logger.debug(f"No flow state to clear for contact {contact.whatsapp_id} (ID: {contact.id}). Reason: {log_suffix}.")

# --- Main Step Execution Logic ---
def _execute_step_actions(step: FlowStep, contact: Contact, flow_context: dict, is_re_execution: bool = False) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    actions_to_perform = []
    raw_step_config = step.config or {}
    current_step_context = flow_context.copy()

    logger.debug(
        f"Executing actions for step '{step.name}' (ID: {step.id}, Type: {step.step_type}) "
        f"for contact {contact.whatsapp_id} (ID: {contact.id}). Is re-execution: {is_re_execution}. "
        f"Raw Config: {json.dumps(raw_step_config) if isinstance(raw_step_config, dict) else str(raw_step_config)}"
    )

    if step.step_type == 'send_message':
        try:
            send_message_config = StepConfigSendMessage.model_validate(raw_step_config)
            actual_message_type = send_message_config.message_type
            final_api_data_structure = {} 
            logger.debug(f"Step '{step.name}': Validated send_message config. Type: '{actual_message_type}'.")

            payload_field_value = getattr(send_message_config, actual_message_type, None)

            if payload_field_value is None: # Should have been caught by root_validator if field was missing
                logger.error(f"Step '{step.name}': Payload field '{actual_message_type}' is None after Pydantic validation. This is unexpected. Raw Config: {raw_step_config}")
                # Fallback or raise an error, as the root validator should prevent this.
                # This indicates a discrepancy between model structure and validator logic if reached.
            
            elif actual_message_type == "text":
                text_content: TextMessageContent = payload_field_value
                resolved_body = _resolve_value(text_content.body, current_step_context, contact)
                logger.debug(f"Step '{step.name}': Resolved text body: '{resolved_body[:100]}{'...' if len(resolved_body) > 100 else ''}'")
                final_api_data_structure = {'body': resolved_body, 'preview_url': text_content.preview_url}

            elif actual_message_type in ['image', 'document', 'audio', 'video', 'sticker']:
                media_conf: MediaMessageContent = payload_field_value
                media_data_to_send = {}
                valid_source_found = False
                if MEDIA_ASSET_ENABLED and media_conf.asset_pk:
                    try:
                        # Ensure company is used if your MediaAsset model is company-specific
                        asset_company = contact.company if hasattr(contact, 'company') else None
                        asset_qs = MediaAsset.objects
                        if asset_company: asset_qs = asset_qs.filter(company=asset_company)
                        
                        asset = asset_qs.get(pk=media_conf.asset_pk)
                        if asset.status == 'synced' and asset.whatsapp_media_id and not asset.is_whatsapp_id_potentially_expired():
                            media_data_to_send['id'] = asset.whatsapp_media_id
                            valid_source_found = True
                            logger.info(f"Step '{step.name}': Using MediaAsset {asset.pk} ('{asset.name}') with WA ID: {asset.whatsapp_media_id}.")
                        else:
                            logger.warning(f"Step '{step.name}': MediaAsset {asset.pk} ('{asset.name}') not usable (Status: {asset.status}, WA ID: {asset.whatsapp_media_id}, Expired: {asset.is_whatsapp_id_potentially_expired()}). Trying direct id/link.")
                    except MediaAsset.DoesNotExist:
                        logger.error(f"Step '{step.name}': MediaAsset pk={media_conf.asset_pk} (Company: {contact.company.name if hasattr(contact, 'company') and contact.company else 'N/A'}) not found. Trying direct id/link.")
                    except Exception as e_asset:
                         logger.error(f"Step '{step.name}': Error accessing MediaAsset pk={media_conf.asset_pk}: {e_asset}", exc_info=True)

                if not valid_source_found: # asset_pk not used or failed
                    if media_conf.id:
                        media_data_to_send['id'] = _resolve_value(media_conf.id, current_step_context, contact)
                        valid_source_found = True
                        logger.debug(f"Step '{step.name}': Using direct media ID '{media_data_to_send['id']}'.")
                    elif media_conf.link:
                        media_data_to_send['link'] = _resolve_value(media_conf.link, current_step_context, contact)
                        valid_source_found = True
                        logger.debug(f"Step '{step.name}': Using direct media link '{media_data_to_send['link']}'.")
                
                if not valid_source_found:
                    logger.error(f"Step '{step.name}': No valid media source (asset_pk, id, or link) for '{actual_message_type}'. Message part will be missing.")
                else:
                    if media_conf.caption:
                        media_data_to_send['caption'] = _resolve_value(media_conf.caption, current_step_context, contact)
                    if actual_message_type == 'document' and media_conf.filename: # Filename only for documents
                        media_data_to_send['filename'] = _resolve_value(media_conf.filename, current_step_context, contact)
                    final_api_data_structure = media_data_to_send 

            elif actual_message_type == "interactive":
                interactive_payload_obj: InteractiveMessagePayload = payload_field_value
                interactive_payload_dict = interactive_payload_obj.model_dump(exclude_none=True, by_alias=True) # Use by_alias if model uses aliases
                resolved_interactive_dict = _resolve_value(interactive_payload_dict, current_step_context, contact)
                logger.debug(f"Step '{step.name}': Resolved interactive payload: {json.dumps(resolved_interactive_dict, indent=2)}")
                final_api_data_structure = resolved_interactive_dict

            elif actual_message_type == "template":
                template_payload_obj: TemplateMessageContent = payload_field_value
                template_payload_dict = template_payload_obj.model_dump(exclude_none=True, by_alias=True)
                if 'components' in template_payload_dict and template_payload_dict['components']: # Components are optional
                    template_payload_dict['components'] = _resolve_template_components(
                        template_payload_dict['components'], current_step_context, contact
                    )
                logger.debug(f"Step '{step.name}': Resolved template payload: {json.dumps(template_payload_dict, indent=2)}")
                final_api_data_structure = template_payload_dict 
            
            elif actual_message_type == "contacts":
                contacts_list_of_objects: List[ContactObject] = payload_field_value
                contacts_list_of_dicts = [c.model_dump(exclude_none=True, by_alias=True) for c in contacts_list_of_objects]
                resolved_contacts_list = _resolve_value(contacts_list_of_dicts, current_step_context, contact)
                logger.debug(f"Step '{step.name}': Resolved contacts payload: {json.dumps(resolved_contacts_list, indent=2)}")
                final_api_data_structure = {"contacts": resolved_contacts_list} # WA API expects {"contacts": [...]}

            elif actual_message_type == "location":
                location_obj: LocationMessageContent = payload_field_value
                location_dict = location_obj.model_dump(exclude_none=True, by_alias=True)
                resolved_location_dict = _resolve_value(location_dict, current_step_context, contact)
                logger.debug(f"Step '{step.name}': Resolved location payload: {json.dumps(resolved_location_dict, indent=2)}")
                final_api_data_structure = resolved_location_dict # This is the 'location' object for WA API

            if final_api_data_structure: 
                logger.info(f"Step '{step.name}': Prepared '{actual_message_type}' message data. Snippet: {str(final_api_data_structure)[:250]}...")
                actions_to_perform.append({
                    'type': 'send_whatsapp_message',
                    'recipient_wa_id': contact.whatsapp_id,
                    'message_type': actual_message_type, 
                    'data': final_api_data_structure 
                })
            elif actual_message_type: 
                logger.warning(
                    f"Step '{step.name}': No data payload was generated for message_type '{actual_message_type}'. "
                    f"This could be due to missing media sources, templates resolving to empty, or the specific payload field being None after validation. "
                    f"Validated Pydantic Config: {send_message_config.model_dump_json(indent=2) if send_message_config else 'None'}"
                )
        except ValidationError as e:
            logger.error(f"Pydantic validation error for 'send_message' step '{step.name}' (ID: {step.id}) config: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e:
            logger.error(f"Unexpected error processing 'send_message' step '{step.name}' (ID: {step.id}): {e}", exc_info=True)

    elif step.step_type == 'question':
        try:
            question_config = StepConfigQuestion.model_validate(raw_step_config)
            logger.debug(f"Validated 'question' step '{step.name}' (ID: {step.id}) config.")
            if question_config.message_config and not is_re_execution:
                logger.info(f"Processing message_config for question step '{step.name}'.")
                try:
                    # The message_config itself is the raw_config for a StepConfigSendMessage
                    # No need to model_dump from a Pydantic object if it's already a dict from the DB
                    dummy_send_step = FlowStep(
                        name=f"{step.name}_prompt_message", 
                        step_type="send_message", 
                        config=question_config.message_config # Pass the dict directly
                    )
                    send_actions, _ = _execute_step_actions(dummy_send_step, contact, current_step_context.copy()) 
                    actions_to_perform.extend(send_actions)
                    logger.debug(f"Generated {len(send_actions)} send actions for question prompt of step '{step.name}'.")
                except ValidationError as ve: # This would be if message_config itself is invalid for StepConfigSendMessage
                    logger.error(f"Pydantic validation error for 'message_config' (of type StepConfigSendMessage) within 'question' step '{step.name}': {ve.errors()}", exc_info=False)
                except Exception as ex_msg_conf:
                    logger.error(f"Error processing message_config for 'question' step '{step.name}': {ex_msg_conf}", exc_info=True)
            
            if question_config.reply_config:
                current_step_context['_question_awaiting_reply_for'] = {
                    'variable_name': question_config.reply_config.save_to_variable,
                    'expected_type': question_config.reply_config.expected_type,
                    'validation_regex': question_config.reply_config.validation_regex,
                    'original_question_step_id': step.id 
                }
                logger.info(f"Step '{step.name}': Awaiting reply for '{question_config.reply_config.save_to_variable}'. Type: '{question_config.reply_config.expected_type}'.")
        except ValidationError as e: # Error validating StepConfigQuestion itself
            logger.error(f"Pydantic validation for 'question' step '{step.name}' (ID: {step.id}) failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_q_step:
            logger.error(f"Unexpected error in 'question' step '{step.name}' (ID: {step.id}): {e_q_step}", exc_info=True)

    elif step.step_type == 'action':
        try:
            action_step_config = StepConfigAction.model_validate(raw_step_config)
            logger.debug(f"Validated 'action' step '{step.name}' (ID: {step.id}) config with {len(action_step_config.actions_to_run)} actions.")
            for i, action_item_conf in enumerate(action_step_config.actions_to_run):
                action_type = action_item_conf.action_type
                logger.info(f"Step '{step.name}': Executing action item {i+1}/{len(action_step_config.actions_to_run)} of type '{action_type}'.")
                if action_type == 'set_context_variable' and action_item_conf.variable_name is not None:
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    current_step_context[action_item_conf.variable_name] = resolved_value
                    logger.info(f"Step '{step.name}': Context variable '{action_item_conf.variable_name}' set to: '{str(resolved_value)[:100]}'.")
                
                elif action_type == 'update_contact_field' and action_item_conf.field_path is not None:
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    _update_contact_data(contact, action_item_conf.field_path, resolved_value) 
                
                elif action_type == 'update_customer_profile' and action_item_conf.fields_to_update is not None:
                    if isinstance(action_item_conf.fields_to_update, dict):
                        resolved_fields_to_update = _resolve_value(action_item_conf.fields_to_update, current_step_context, contact)
                        _update_customer_profile_data(contact, resolved_fields_to_update, current_step_context) 
                    else:
                        logger.error(f"Step '{step.name}': Action 'update_customer_profile' has invalid 'fields_to_update' (not a dict): {action_item_conf.fields_to_update}")
                
                elif action_type == 'switch_flow' and action_item_conf.target_flow_name is not None:
                    resolved_initial_context = _resolve_value(action_item_conf.initial_context_template or {}, current_step_context, contact)
                    resolved_msg_body = _resolve_value(action_item_conf.message_to_evaluate_for_new_flow, current_step_context, contact) if action_item_conf.message_to_evaluate_for_new_flow else None
                    
                    logger.info(f"Step '{step.name}': Queuing switch to flow '{action_item_conf.target_flow_name}'. Initial context: {resolved_initial_context}, Trigger message: '{resolved_msg_body}'")
                    actions_to_perform.append({
                        'type': '_internal_command_switch_flow',
                        'target_flow_name': action_item_conf.target_flow_name,
                        'initial_context': resolved_initial_context if isinstance(resolved_initial_context, dict) else {},
                        'new_flow_trigger_message_body': resolved_msg_body
                    })
                    logger.debug(f"Step '{step.name}': Switch flow action encountered. Further actions in this step will be skipped.")
                    break 
                else:
                    logger.warning(f"Step '{step.name}': Unknown or misconfigured action_item_type '{action_type}'. Config: {action_item_conf.model_dump_json(indent=2)}")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'action' step '{step.name}' (ID: {step.id}) failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_act_step:
            logger.error(f"Unexpected error in 'action' step '{step.name}' (ID: {step.id}): {e_act_step}", exc_info=True)

    elif step.step_type == 'end_flow':
        try:
            end_flow_config = StepConfigEndFlow.model_validate(raw_step_config)
            logger.info(f"Executing 'end_flow' step '{step.name}' (ID: {step.id}) for contact {contact.whatsapp_id}.")
            if end_flow_config.message_config:
                logger.debug(f"Step '{step.name}': End_flow step has a final message to send.")
                try:
                    dummy_end_msg_step = FlowStep(name=f"{step.name}_final_msg", step_type="send_message", config=end_flow_config.message_config)
                    send_actions, _ = _execute_step_actions(dummy_end_msg_step, contact, current_step_context.copy())
                    actions_to_perform.extend(send_actions)
                    logger.debug(f"Generated {len(send_actions)} send actions for end_flow message of step '{step.name}'.")
                except ValidationError as ve: # Should be caught by StepConfigEndFlow's validator on message_config
                    logger.error(f"Pydantic validation error for 'message_config' in 'end_flow' step '{step.name}': {ve.errors()}", exc_info=False)
                except Exception as ex_end_msg:
                     logger.error(f"Error processing message_config for 'end_flow' step '{step.name}': {ex_end_msg}", exc_info=True)
            
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Flow ended at step {step.name} (ID: {step.id})'})
            logger.info(f"Step '{step.name}': Flow ended for contact {contact.whatsapp_id}. Flow state will be cleared.")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'end_flow' step '{step.name}' (ID: {step.id}) config: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_end_step:
            logger.error(f"Unexpected error in 'end_flow' step '{step.name}' (ID: {step.id}): {e_end_step}", exc_info=True)

    elif step.step_type == 'human_handover':
        try:
            handover_config = StepConfigHumanHandover.model_validate(raw_step_config)
            logger.info(f"Executing 'human_handover' step '{step.name}' (ID: {step.id}) for contact {contact.whatsapp_id}.")
            if handover_config.pre_handover_message_text and not is_re_execution: 
                resolved_msg = _resolve_value(handover_config.pre_handover_message_text, current_step_context, contact)
                logger.debug(f"Step '{step.name}': Sending pre-handover message: '{resolved_msg}'")
                actions_to_perform.append({
                    'type': 'send_whatsapp_message', 
                    'recipient_wa_id': contact.whatsapp_id, 
                    'message_type': 'text', 
                    'data': {'body': resolved_msg}
                })
            
            contact.needs_human_intervention = True
            contact.intervention_requested_at = timezone.now()
            contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
            logger.info(f"Contact {contact.whatsapp_id} (Name: {contact.name or 'N/A'}) flagged for human intervention from step '{step.name}'.")
            
            notification_info = _resolve_value(
                handover_config.notification_details, # Default is in Pydantic model
                current_step_context,
                contact
            )
            logger.info(f"HUMAN_INTERVENTION_ALERT: Contact: {contact.whatsapp_id} (ID: {contact.id}), Name: {contact.name or 'N/A'}, Details: {notification_info}, Context: {json.dumps(current_step_context)}")
            
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Human handover at step {step.name} (ID: {step.id})'})
            logger.info(f"Step '{step.name}': Human handover initiated for contact {contact.whatsapp_id}. Flow state will be cleared.")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'human_handover' step '{step.name}' (ID: {step.id}) failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_hh_step:
            logger.error(f"Unexpected error in 'human_handover' step '{step.name}' (ID: {step.id}): {e_hh_step}", exc_info=True)

    elif step.step_type in ['condition', 'wait_for_reply', 'start_flow_node']:
        logger.debug(f"Step '{step.name}' (ID: {step.id}, Type: '{step.step_type}') is structural. No direct actions executed by _execute_step_actions.")
    else:
        logger.warning(f"Unhandled step_type: '{step.step_type}' for step '{step.name}' (ID: {step.id}). No actions executed.")

    logger.debug(f"Finished executing actions for step '{step.name}' (ID: {step.id}). Generated {len(actions_to_perform)} actions. Resulting context (snippet): {str(current_step_context)[:200]}...")
    return actions_to_perform, current_step_context


def _handle_active_flow_step(contact_flow_state: ContactFlowState, contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    current_step = contact_flow_state.current_step
    flow_context = contact_flow_state.flow_context_data if isinstance(contact_flow_state.flow_context_data, dict) else {}
    actions_to_perform = []

    logger.info(
        f"Handling active flow for contact {contact.whatsapp_id} (ID: {contact.id}). Current Flow: '{contact_flow_state.current_flow.name}', "
        f"Step: '{current_step.name}' (ID: {current_step.id}, Type: {current_step.step_type})."
    )
    logger.debug(f"Incoming message type: {message_data.get('type')}, data: {str(message_data)[:200]}. Current flow context (snippet): {str(flow_context)[:200]}")

    question_expectation = flow_context.get('_question_awaiting_reply_for')
    is_processing_reply_for_current_question = False # Flag to indicate if we are handling a reply for the current question step

    if current_step.step_type == 'question' and \
       isinstance(question_expectation, dict) and \
       question_expectation.get('original_question_step_id') == current_step.id:
        
        is_processing_reply_for_current_question = True # We are indeed processing a reply for *this* question
        variable_to_save_name = question_expectation.get('variable_name')
        expected_reply_type = question_expectation.get('expected_type')
        validation_regex_ctx = question_expectation.get('validation_regex')
        
        user_text = message_data.get('text', {}).get('body', '').strip() if message_data.get('type') == 'text' else None
        interactive_reply_id = None
        if message_data.get('type') == 'interactive':
            interactive_payload = message_data.get('interactive', {})
            interactive_type_from_payload = interactive_payload.get('type') 
            if interactive_type_from_payload == 'button_reply':
                interactive_reply_id = interactive_payload.get('button_reply', {}).get('id')
            elif interactive_type_from_payload == 'list_reply':
                interactive_reply_id = interactive_payload.get('list_reply', {}).get('id')
        
        logger.debug(f"Processing reply for question '{current_step.name}'. Expected type: '{expected_reply_type}'. User text: '{user_text}', Interactive ID: '{interactive_reply_id}'.")

        reply_is_valid = False
        value_to_save = None

        if expected_reply_type == 'text' and user_text is not None:
            value_to_save = user_text
            reply_is_valid = True 
            if validation_regex_ctx and not re.match(validation_regex_ctx, user_text):
                reply_is_valid = False; value_to_save = None
                logger.debug(f"Text reply '{user_text}' for question '{current_step.name}' did not match regex '{validation_regex_ctx}'.")
        elif expected_reply_type == 'email':
            email_r = validation_regex_ctx or r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if user_text and re.match(email_r, user_text):
                value_to_save = user_text; reply_is_valid = True
            else: logger.debug(f"Email reply '{user_text}' for question '{current_step.name}' did not match regex '{email_r}'.")
        elif expected_reply_type == 'number' and user_text is not None:
            try:
                num_val = float(user_text) if '.' in user_text or (validation_regex_ctx and '.' in validation_regex_ctx) else int(user_text)
                if validation_regex_ctx and not re.match(validation_regex_ctx, user_text): 
                     logger.debug(f"Number string reply '{user_text}' for question '{current_step.name}' did not match regex '{validation_regex_ctx}'.")
                else: value_to_save = num_val; reply_is_valid = True
            except ValueError: logger.debug(f"Could not parse '{user_text}' as a number for question '{current_step.name}'.")
        elif expected_reply_type == 'interactive_id' and interactive_reply_id is not None:
            value_to_save = interactive_reply_id; reply_is_valid = True
            if validation_regex_ctx and not re.match(validation_regex_ctx, interactive_reply_id):
                reply_is_valid = False; value_to_save = None
                logger.debug(f"Interactive ID reply '{interactive_reply_id}' for question '{current_step.name}' did not match regex '{validation_regex_ctx}'.")
        elif expected_reply_type == 'any':
             if user_text is not None: value_to_save = user_text
             elif interactive_reply_id is not None: value_to_save = interactive_reply_id
             elif message_data: # Capture other types of message data if 'any' is expected
                 # Decide what to save: could be the type, a specific payload part, or whole message_data.
                 # For simplicity, let's try to get common parts or fallback to type string.
                 if message_data.get('type') in ['image', 'video', 'audio', 'document', 'sticker']:
                     value_to_save = message_data.get(message_data.get('type'), {}).get('id') or message_data.get(message_data.get('type'), {}).get('link') or message_data.get('type')
                 elif message_data.get('type') == 'location':
                     value_to_save = message_data.get('location', {}) # The location object
                 else:
                     value_to_save = str(message_data)[:255] # Truncate if saving whole dict
             else: value_to_save = None 
             reply_is_valid = value_to_save is not None 

        if reply_is_valid:
            if variable_to_save_name:
                flow_context[variable_to_save_name] = value_to_save
                logger.info(f"Saved valid reply for var '{variable_to_save_name}' in Q-step '{current_step.name}'. Value (type {type(value_to_save)}): '{str(value_to_save)[:100]}'.")
            else:
                logger.info(f"Valid reply received for Q-step '{current_step.name}', but no 'save_to_variable' defined. Value (type {type(value_to_save)}): '{str(value_to_save)[:100]}'.")
            flow_context.pop('_fallback_count', None) # Reset fallback count on valid reply
            # Now, the flow can proceed to evaluate transitions based on this valid reply / updated context
        else: # Reply is NOT valid for the question
            logger.info(f"Reply for question step '{current_step.name}' was not valid. Expected type: '{expected_reply_type}'.")
            fallback_config = current_step.config.get('fallback_config', {}) if isinstance(current_step.config, dict) else {}
            max_retries = fallback_config.get('max_retries', 1) 
            current_fallback_count = flow_context.get('_fallback_count', 0)

            if current_fallback_count < max_retries:
                logger.info(f"Invalid reply for Q '{current_step.name}'. Re-prompting (Attempt {current_fallback_count + 1} of {max_retries}).")
                flow_context['_fallback_count'] = current_fallback_count + 1
                
                re_prompt_message_text = fallback_config.get('re_prompt_message_text')
                if re_prompt_message_text: 
                    resolved_re_prompt_text = _resolve_value(re_prompt_message_text, flow_context, contact)
                    actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_re_prompt_text}})
                else: 
                    logger.debug(f"No custom re-prompt message for Q '{current_step.name}'. Re-sending original question message.")
                    step_actions, updated_context_from_re_execution = _execute_step_actions(current_step, contact, flow_context.copy(), is_re_execution=True)
                    actions_to_perform.extend(step_actions)
                    flow_context = updated_context_from_re_execution 
                
                contact_flow_state.flow_context_data = flow_context
                contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])
                logger.debug(f"Q '{current_step.name}' re-prompt actions generated. Flow context updated. Returning to wait for new reply.")
                return actions_to_perform # Stop further processing in this cycle, wait for new reply to the re-prompt
            else: 
                logger.info(f"Max retries ({max_retries}) reached for Q '{current_step.name}'. Executing action after max retries.")
                flow_context.pop('_fallback_count', None) # Reset for future if step is revisited
                action_after_max_retries = fallback_config.get('action_after_max_retries', 'human_handover') 
                
                if action_after_max_retries == 'human_handover':
                    logger.info(f"Max retries for Q '{current_step.name}'. Fallback: Initiating human handover for {contact.whatsapp_id}.")
                    handover_message_text = fallback_config.get('handover_message_text', "Sorry, I'm having trouble understanding. Let me connect you to an agent.")
                    resolved_handover_msg = _resolve_value(handover_message_text, flow_context, contact)
                    actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_handover_msg}})
                    actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Max retries for Q {current_step.name}'})
                    contact.needs_human_intervention = True; contact.intervention_requested_at = timezone.now()
                    contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
                    return actions_to_perform # Handover is terminal for the flow
                elif action_after_max_retries == 'end_flow':
                    logger.info(f"Max retries for Q '{current_step.name}'. Fallback: Ending flow for {contact.whatsapp_id}.")
                    actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Max retries for Q {current_step.name}, ending flow.'})
                    if fallback_config.get('end_flow_message_text'):
                         actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': _resolve_value(fallback_config['end_flow_message_text'], flow_context, contact)}})
                    return actions_to_perform # End flow is terminal
                else: # If 'action_after_max_retries' specifies a step name or other command, it would need more logic.
                      # For now, if not handover/end, it will fall through to evaluate general transitions.
                    logger.info(f"Max retries for Q '{current_step.name}'. Action '{action_after_max_retries}' not handover/end. Proceeding to evaluate transitions if any.")
                    # The reply is still considered "not processed for transition" so general transitions can take over
                    is_processing_reply_for_current_question = False # Allow general transitions to run now

    # Evaluate transitions if:
    # - Not a question step OR
    # - It was a question step, and the reply was valid (is_processing_reply_for_current_question is True, but reply_is_valid was True) OR
    # - It was a question step, reply was invalid, max retries hit, and no terminal action (handover/end) was taken.
    
    if not is_processing_reply_for_current_question or (is_processing_reply_for_current_question and reply_is_valid): # Simplified: if it was a question and invalid, its specific fallbacks were handled.
        transitions = FlowTransition.objects.filter(current_step=current_step).select_related('next_step').order_by('priority')
        next_step_to_transition_to = None
        
        logger.debug(f"Evaluating {transitions.count()} general transitions for step '{current_step.name}'.")
        for transition in transitions:
            if _evaluate_transition_condition(transition, contact, message_data, flow_context.copy(), incoming_message_obj):
                next_step_to_transition_to = transition.next_step
                logger.info(f"Transition ID {transition.id} (Priority: {transition.priority}) condition met: From '{current_step.name}' to '{next_step_to_transition_to.name}'.")
                break 
        
        if next_step_to_transition_to:
            actions_from_next_step, _ = _transition_to_step(
                contact_flow_state, next_step_to_transition_to, flow_context, contact, message_data
            )
            actions_to_perform.extend(actions_from_next_step)
        # If no transition taken and it was not a question step that handled its own invalid reply path leading to an exit/re-prompt:
        elif not (current_step.step_type == 'question' and is_processing_reply_for_current_question and not reply_is_valid):
            logger.info(f"No general transition conditions met from step '{current_step.name}' for contact {contact.whatsapp_id}. Applying general fallback if any.")
            fallback_config = current_step.config.get('fallback_config', {}) if isinstance(current_step.config, dict) else {}
            
            if fallback_config.get('fallback_message_text'):
                resolved_fallback_text = _resolve_value(fallback_config['fallback_message_text'], flow_context, contact)
                logger.debug(f"Step '{current_step.name}': Sending general fallback message: {resolved_fallback_text}")
                actions_to_perform.append({
                    'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                    'message_type': 'text', 'data': {'body': resolved_fallback_text}
                })
                if fallback_config.get('handover_after_message', False):
                    logger.info(f"Step '{current_step.name}': General fallback initiating human handover after message for {contact.whatsapp_id}.")
                    actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'General fallback handover at {current_step.name}'})
                    contact.needs_human_intervention = True; contact.intervention_requested_at = timezone.now()
                    contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
            
            elif fallback_config.get('action') == 'human_handover':
                logger.info(f"Step '{current_step.name}': General fallback initiating human handover directly for {contact.whatsapp_id}.")
                pre_handover_msg = fallback_config.get('pre_handover_message_text', "Let me connect you to an agent for further assistance.")
                resolved_msg = _resolve_value(pre_handover_msg, flow_context, contact)
                actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_msg}})
                actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'General fallback direct handover at {current_step.name}'})
                contact.needs_human_intervention = True; contact.intervention_requested_at = timezone.now()
                contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
            else:
                # Only send default "didn't understand" if no other actions were generated by this point.
                # This avoids sending it if a question step handled its own invalid reply with a re-prompt.
                if not actions_to_perform:
                    logger.info(f"Step '{current_step.name}': No specific general fallback action. Sending default 'did not understand' message.")
                    actions_to_perform.append({
                        'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                        'message_type': 'text', 'data': {'body': "Sorry, I could not process that. Please try 'menu' or rephrase your request."}
                    })
    return actions_to_perform


def _trigger_new_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    actions_to_perform = []
    initial_flow_context = {} 
    message_text_body = None
    
    if message_data.get('type') == 'text':
        message_text_body = message_data.get('text', {}).get('body', '').lower().strip()
        logger.debug(f"_trigger_new_flow: Attempting with text: '{message_text_body}' for contact {contact.whatsapp_id} (ID: {contact.id}).")
    else:
        logger.debug(f"_trigger_new_flow: Attempting with non-text message type: '{message_data.get('type')}' for contact {contact.whatsapp_id} (ID: {contact.id}).")

    triggered_flow = None
    # Ensure contact.company is loaded if it's a ForeignKey, or handle if it might be None
    contact_company = getattr(contact, 'company', None)
    if not contact_company:
        logger.error(f"Contact {contact.id} does not have an associated company. Cannot trigger company-specific flows.")
        return actions_to_perform # Or handle as per your app's logic for contacts without a company

    active_flows = Flow.objects.filter(is_active=True, company=contact_company).order_by('name') 
    logger.debug(f"Found {active_flows.count()} active flows for company '{contact_company.name if contact_company else 'N/A'}'.")

    if message_text_body: 
        for flow_candidate in active_flows:
            # Assuming trigger_keywords is List[Union[str, Dict[str, str]]]
            # Example: ["hi", {"keyword": "order status", "mode": "exact"}]
            trigger_keywords_config = flow_candidate.trigger_keywords
            if not isinstance(trigger_keywords_config, list):
                if trigger_keywords_config: # Log if it's some other truthy non-list value
                     logger.warning(f"Flow '{flow_candidate.name}' has non-list trigger_keywords: {trigger_keywords_config}")
                continue

            for keyword_entry in trigger_keywords_config: 
                keyword_str = ""
                match_mode = "contains" # Default
                
                if isinstance(keyword_entry, str):
                    keyword_str = keyword_entry
                elif isinstance(keyword_entry, dict):
                    keyword_str = keyword_entry.get("keyword", "")
                    match_mode = keyword_entry.get("mode", "contains").lower() # Normalize mode
                    if match_mode not in ["exact", "prefix", "contains", "regex"]:
                        logger.warning(f"Invalid match_mode '{match_mode}' for keyword '{keyword_str}' in flow '{flow_candidate.name}'. Defaulting to 'contains'.")
                        match_mode = "contains"
                
                if isinstance(keyword_str, str) and keyword_str.strip():
                    processed_keyword_for_match = keyword_str.strip().lower() if match_mode != "regex" else keyword_str.strip()
                    text_for_match = message_text_body # Already lowercased and stripped

                    triggered = False
                    if match_mode == "exact" and processed_keyword_for_match == text_for_match:
                        triggered = True
                    elif match_mode == "prefix" and text_for_match.startswith(processed_keyword_for_match):
                        triggered = True
                    elif match_mode == "contains" and processed_keyword_for_match in text_for_match:
                        triggered = True
                    elif match_mode == "regex":
                        try:
                            if re.search(processed_keyword_for_match, message_data.get('text', {}).get('body', '').strip()): # Use original case for regex
                                triggered = True
                        except re.error as re_err:
                            logger.error(f"Invalid regex '{processed_keyword_for_match}' for flow '{flow_candidate.name}': {re_err}")
                    
                    if triggered:
                        triggered_flow = flow_candidate
                        logger.info(f"Keyword '{processed_keyword_for_match}' (mode: {match_mode}) triggered flow '{flow_candidate.name}' (ID: {flow_candidate.id}) for contact {contact.whatsapp_id}.")
                        break 
            if triggered_flow:
                break
    
    if triggered_flow:
        entry_point_step = FlowStep.objects.filter(flow=triggered_flow, is_entry_point=True).first()
        if entry_point_step:
            logger.info(f"Starting flow '{triggered_flow.name}' for contact {contact.whatsapp_id} (ID: {contact.id}) at entry step '{entry_point_step.name}' (ID: {entry_point_step.id}).")
            _clear_contact_flow_state(contact, reason=f"Starting new flow {triggered_flow.name} (ID: {triggered_flow.id})") 
            
            initial_flow_context = {} # Reset for this trigger
            if isinstance(triggered_flow.default_flow_context, dict):
                initial_flow_context.update(triggered_flow.default_flow_context)
                logger.debug(f"Applied default_flow_context from flow '{triggered_flow.name}': {triggered_flow.default_flow_context}")
            
            # Optionally, add trigger message info to context
            # initial_flow_context['trigger_message'] = {'type': message_data.get('type'), 'body': message_text_body}

            contact_flow_state = ContactFlowState.objects.create(
                contact=contact,
                current_flow=triggered_flow,
                current_step=entry_point_step,
                flow_context_data=initial_flow_context, 
                started_at=timezone.now(),
                company=contact_company # Store company on the state
            )
            logger.debug(f"Created ContactFlowState (pk={contact_flow_state.pk}) for contact {contact.whatsapp_id}. Initial context: {initial_flow_context}")

            step_actions, context_after_entry_step = _execute_step_actions(entry_point_step, contact, initial_flow_context.copy())
            actions_to_perform.extend(step_actions)
            
            current_db_state = ContactFlowState.objects.filter(pk=contact_flow_state.pk).first()
            if current_db_state:
                if current_db_state.flow_context_data != context_after_entry_step: 
                    logger.debug(f"Context for flow '{triggered_flow.name}' changed by entry step '{entry_point_step.name}'. Old: {current_db_state.flow_context_data}, New: {context_after_entry_step}")
                    current_db_state.flow_context_data = context_after_entry_step
                    current_db_state.save(update_fields=['flow_context_data', 'last_updated_at'])
            else:
                logger.info(f"Flow state for contact {contact.whatsapp_id} was cleared by the entry step '{entry_point_step.name}' itself. Context not saved for this state object.")
        else:
            logger.error(f"Flow '{triggered_flow.name}' (ID: {triggered_flow.id}) for company '{contact_company.name if contact_company else 'N/A'}' is active but has no entry point step defined.")
    else:
        logger.info(f"No active flow triggered for contact {contact.whatsapp_id} (Company: {contact_company.name if contact_company else 'N/A'}). Incoming (type: {message_data.get('type')}, text: '{message_text_body[:100] if message_text_body else 'N/A'}').")

    return actions_to_perform

# --- process_message_for_flow and supporting functions ---
# (Make sure the wamid fix is in process_message_for_flow as provided in the previous response)
@transaction.atomic 
def process_message_for_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    actions_to_perform = []
    logger.info(
        f"Processing message for flow. Contact: {contact.whatsapp_id} (ID: {contact.id}), "
        f"Message Type: {message_data.get('type')}, "
        f"Message WAMID: {incoming_message_obj.wamid if incoming_message_obj and hasattr(incoming_message_obj, 'wamid') else 'N/A'}."
    )

    try:
        contact_flow_state = ContactFlowState.objects.select_for_update().select_related(
            'current_flow', 'current_step', 'company' # Include company
        ).get(contact=contact, company=contact.company) # Ensure company match
        
        logger.info(
            f"Contact {contact.whatsapp_id} is currently in flow '{contact_flow_state.current_flow.name}' (ID: {contact_flow_state.current_flow.id}), "
            f"step '{contact_flow_state.current_step.name}' (ID: {contact_flow_state.current_step.id}) for company '{contact_flow_state.company.name if contact_flow_state.company else 'N/A'}."
        )
        actions_to_perform = _handle_active_flow_step(
            contact_flow_state, contact, message_data, incoming_message_obj
        )
    except ContactFlowState.DoesNotExist:
        logger.info(f"No active flow state for contact {contact.whatsapp_id} (Company: {contact.company.name if hasattr(contact, 'company') and contact.company else 'N/A'}). Attempting to trigger a new flow.")
        actions_to_perform = _trigger_new_flow(contact, message_data, incoming_message_obj)
    except Exception as e:
        logger.error(
            f"CRITICAL error in process_message_for_flow for contact {contact.whatsapp_id} (Message WAMID: {incoming_message_obj.wamid if incoming_message_obj and hasattr(incoming_message_obj, 'wamid') else 'N/A'}): {e}", 
            exc_info=True
        )
        _clear_contact_flow_state(contact, error=True, reason=f"Critical error in process_message_for_flow: {str(e)[:100]}")
        actions_to_perform = [{
            'type': 'send_whatsapp_message',
            'recipient_wa_id': contact.whatsapp_id,
            'message_type': 'text',
            'data': {'body': 'I encountered an unexpected issue. Please try again in a moment. If the problem persists, contact support.'}
        }]
        return actions_to_perform 
        
    current_contact_flow_state_after_initial_handling = ContactFlowState.objects.filter(contact=contact, company=contact.company).first()
    
    if current_contact_flow_state_after_initial_handling:
        is_waiting_for_reply_from_current_step = False
        current_step = current_contact_flow_state_after_initial_handling.current_step
        current_context = current_contact_flow_state_after_initial_handling.flow_context_data if isinstance(current_contact_flow_state_after_initial_handling.flow_context_data, dict) else {}

        if current_step.step_type == 'question':
            question_expectation = current_context.get('_question_awaiting_reply_for')
            if isinstance(question_expectation, dict) and question_expectation.get('original_question_step_id') == current_step.id:
                is_waiting_for_reply_from_current_step = True
                logger.debug(f"Contact {contact.whatsapp_id}: Current step '{current_step.name}' is a question still awaiting reply. No auto-transitions will be processed now.")
        
        if not is_waiting_for_reply_from_current_step and \
           not any(a.get('type') == '_internal_command_clear_flow_state' for a in actions_to_perform) and \
           not any(a.get('type') == '_internal_command_switch_flow' for a in actions_to_perform):
            
            logger.info(f"Contact {contact.whatsapp_id}: Checking for automatic transitions from step '{current_step.name}'.")
            additional_auto_actions = _process_automatic_transitions(current_contact_flow_state_after_initial_handling, contact)
            if additional_auto_actions:
                logger.info(f"Contact {contact.whatsapp_id}: Appending {len(additional_auto_actions)} actions from automatic transitions.")
                actions_to_perform.extend(additional_auto_actions)
        else:
            logger.debug(f"Contact {contact.whatsapp_id}: Skipping automatic transitions. Waiting for reply: {is_waiting_for_reply_from_current_step}, Flow Clear/Switch commanded: {any(a.get('type') in ['_internal_command_clear_flow_state', '_internal_command_switch_flow'] for a in actions_to_perform)}")
    else:
        logger.info(f"Contact {contact.whatsapp_id}: No active flow state after initial processing. No automatic transitions to run.")
            
    final_actions_for_meta_view = []
    processed_switch_command = False # Ensure only one switch is processed if multiple were somehow queued
    
    temp_actions_to_process = list(actions_to_perform) # Iterate over a copy if list can be modified

    for action in temp_actions_to_process:
        if processed_switch_command and action.get('type') != 'send_whatsapp_message':
            # If a switch happened, only allow send_whatsapp_message actions that came FROM the new flow's entry.
            # This logic might need to be inside the switch block if it replaces actions_to_perform entirely.
            logger.debug(f"Skipping action {action.get('type')} after flow switch already processed.")
            continue

        action_type = action.get('type')
        logger.debug(f"Final processing of action: {action_type} for contact {contact.whatsapp_id} (ID: {contact.id}). Action detail: {str(action)[:150]}")

        if action_type == '_internal_command_clear_flow_state':
            logger.info(f"Internal command: Flow state already handled or will be by no state found. Reason: {action.get('reason', 'N/A')}")
        
        elif action_type == '_internal_command_switch_flow':
            if processed_switch_command:
                logger.warning(f"Contact {contact.whatsapp_id}: Multiple switch flow commands detected. Only processing the first one.")
                continue

            target_flow_name = action.get('target_flow_name')
            logger.info(f"Processing internal command to switch flow for contact {contact.whatsapp_id} to '{target_flow_name}'.")
            
            _clear_contact_flow_state(contact, reason=f"Switching to flow {target_flow_name}")

            initial_context_for_new_flow = action.get('initial_context', {}) 
            new_flow_trigger_msg_body = action.get('new_flow_trigger_message_body')
            
            synthetic_message_data = {
                'type': 'text', 
                'text': {'body': new_flow_trigger_msg_body or f"__internal_trigger_{target_flow_name}"}
            }
            
            # _trigger_new_flow creates new state and returns actions from new flow's entry point
            switched_flow_actions = _trigger_new_flow(contact, synthetic_message_data, incoming_message_obj) 
            
            newly_created_state_after_switch = ContactFlowState.objects.filter(contact=contact).first()
            if newly_created_state_after_switch and initial_context_for_new_flow and isinstance(initial_context_for_new_flow, dict):
                logger.debug(f"Applying initial context to newly switched flow state (pk={newly_created_state_after_switch.pk}). Current context: {newly_created_state_after_switch.flow_context_data}, Initial to apply: {initial_context_for_new_flow}")
                if not isinstance(newly_created_state_after_switch.flow_context_data, dict): # Should be initialized as dict
                    newly_created_state_after_switch.flow_context_data = {} 
                newly_created_state_after_switch.flow_context_data.update(initial_context_for_new_flow) # Merge initial context
                newly_created_state_after_switch.save(update_fields=['flow_context_data', 'last_updated_at'])
                logger.info(f"Applied initial context to new flow '{target_flow_name}' state for {contact.whatsapp_id}: {initial_context_for_new_flow}")
            
            # The actions from the *new* flow's entry point are now the primary actions.
            final_actions_for_meta_view = switched_flow_actions 
            processed_switch_command = True 
            logger.info(f"Flow switch for {contact.whatsapp_id} to '{target_flow_name}' completed. Actions from new flow: {len(final_actions_for_meta_view)}")
            break # Important: Stop processing previous list of actions, as we've switched.

        elif action_type == 'send_whatsapp_message':
            if not processed_switch_command: # Only add if not part of a switch that replaced the action list
                final_actions_for_meta_view.append(action)
        else:
            logger.warning(f"Unhandled action type '{action_type}' encountered during final action processing for contact {contact.whatsapp_id}. Action: {action}")
            
    logger.info(f"Finished processing message for contact {contact.whatsapp_id} (ID: {contact.id}). Total {len(final_actions_for_meta_view)} actions to be sent to meta_integration.")
    logger.debug(f"Final actions for {contact.whatsapp_id}: {json.dumps(final_actions_for_meta_view, indent=2)}")
    return final_actions_for_meta_view