# whatsappcrm_backend/flows/services.py

import logging
import json
import re
from typing import List, Dict, Any, Optional, Union, Literal

from django.utils import timezone
from django.db import transaction
from pydantic import BaseModel, ValidationError, field_validator, root_validator, Field

from conversations.models import Contact, Message
from .models import Flow, FlowStep, FlowTransition, ContactFlowState
from customer_data.models import CustomerProfile # Assuming this import is correct
try:
    from media_manager.models import MediaAsset
    MEDIA_ASSET_ENABLED = True
except ImportError:
    MEDIA_ASSET_ENABLED = False

logger = logging.getLogger(__name__)

if not MEDIA_ASSET_ENABLED:
    logger.warning("MediaAsset model not found or could not be imported. MediaAsset functionality (e.g., 'asset_pk') will be disabled in flows.")

# --- Pydantic Models (Unchanged from your provided version) ---
class BasePydanticConfig(BaseModel):
    class Config:
        extra = 'allow' # Keep 'allow' if you need to pass through extra fields not defined in models
                        # Consider 'ignore' if they should be silently dropped, or 'forbid' to raise errors

class TextMessageContent(BasePydanticConfig):
    body: str = Field(..., min_length=1, max_length=4096)
    preview_url: bool = False

class MediaMessageContent(BasePydanticConfig):
    asset_pk: Optional[int] = None
    id: Optional[str] = None
    link: Optional[str] = None
    caption: Optional[str] = Field(default=None, max_length=1024)
    filename: Optional[str] = None # Specifically for documents

    @root_validator(pre=False, skip_on_failure=True)
    def check_media_source(cls, values):
        asset_pk, media_id, link = values.get('asset_pk'), values.get('id'), values.get('link')
        if not MEDIA_ASSET_ENABLED and asset_pk:
            raise ValueError("'asset_pk' provided but MediaAsset system is not enabled/imported.")
        if not (asset_pk or media_id or link):
            raise ValueError("One of 'asset_pk', 'id', or 'link' must be provided for media.")
        return values

class InteractiveButtonReply(BasePydanticConfig):
    id: str = Field(..., min_length=1, max_length=256)
    title: str = Field(..., min_length=1, max_length=20)

class InteractiveButton(BasePydanticConfig):
    type: Literal["reply"] = "reply"
    reply: InteractiveButtonReply

class InteractiveButtonAction(BasePydanticConfig):
    buttons: List[InteractiveButton] = Field(..., min_items=1, max_items=3)

class InteractiveHeader(BasePydanticConfig):
    type: Literal["text", "video", "image", "document"]
    text: Optional[str] = Field(default=None, max_length=60)
    # For media types in header, WhatsApp expects an object with id or link:
    # e.g. image: Optional[Dict[str, str]] = None # {"link": "..."} or {"id": "..."}

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
    rows: List[InteractiveListRow] = Field(..., min_items=1, max_items=10)

class InteractiveListAction(BasePydanticConfig):
    button: str = Field(..., min_length=1, max_length=20) # Button text to open the list
    sections: List[InteractiveListSection] = Field(..., min_items=1)

class InteractiveMessagePayload(BasePydanticConfig): # Represents the 'interactive' object in WA API
    type: Literal["button", "list", "product", "product_list"] # product & product_list might need more fields
    header: Optional[InteractiveHeader] = None
    body: InteractiveBody # Body is required for button and list
    footer: Optional[InteractiveFooter] = None
    action: Union[InteractiveButtonAction, InteractiveListAction] # Add other action types if supporting product/product_list

class TemplateLanguage(BasePydanticConfig):
    code: str # e.g., "en_US"

class TemplateParameter(BasePydanticConfig):
    type: Literal["text", "currency", "date_time", "image", "document", "video", "payload"]
    text: Optional[str] = None
    currency: Optional[Dict[str, Any]] = None # e.g., {"fallback_value": "...", "code": "USD", "amount_1000": 1230}
    date_time: Optional[Dict[str, Any]] = None # e.g., {"fallback_value": "..."}
    image: Optional[Dict[str, Any]] = None # e.g., {"link": "..."} or {"id":"..."}
    document: Optional[Dict[str, Any]] = None
    video: Optional[Dict[str, Any]] = None
    payload: Optional[str] = None # For quick reply button postback payload

class TemplateComponent(BasePydanticConfig):
    type: Literal["header", "body", "button"]
    sub_type: Optional[Literal['url', 'quick_reply', 'call_button', 'catalog_button', 'mpm_button']] = None # For buttons
    parameters: Optional[List[TemplateParameter]] = None
    index: Optional[int] = None # For url buttons

class TemplateMessageContent(BasePydanticConfig): # Represents the 'template' object for WA API
    name: str # Name of the template
    language: TemplateLanguage
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
    country_code: Optional[str] = None
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactEmail(BasePydanticConfig):
    email: Optional[str] = None
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactPhone(BasePydanticConfig):
    phone: Optional[str] = None # E.164 format
    type: Optional[Literal['CELL', 'MAIN', 'IPHONE', 'HOME', 'WORK']] = None
    wa_id: Optional[str] = None # WhatsApp ID

class ContactOrg(BasePydanticConfig):
    company: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None

class ContactUrl(BasePydanticConfig):
    url: Optional[str] = None # Standard URL
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactObject(BasePydanticConfig): # Represents one 'contact' object in the 'contacts' array for WA API
    addresses: Optional[List[ContactAddress]] = None
    birthday: Optional[str] = None # YYYY-MM-DD
    emails: Optional[List[ContactEmail]] = None
    name: ContactName # Required
    org: Optional[ContactOrg] = None
    phones: Optional[List[ContactPhone]] = None
    urls: Optional[List[ContactUrl]] = None

class LocationMessageContent(BasePydanticConfig): # Represents the 'location' object for WA API
    longitude: float
    latitude: float
    name: Optional[str] = None
    address: Optional[str] = None

class StepConfigSendMessage(BasePydanticConfig):
    message_type: Literal["text", "image", "document", "audio", "video", "sticker", "interactive", "template", "contacts", "location"]
    # Direct payload fields matching message_type
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

    @root_validator(pre=False, skip_on_failure=True)
    def check_payload_exists_for_type(cls, values):
        msg_type = values.get('message_type')
        # Dynamically get the attribute corresponding to msg_type (e.g., values.get('text'), values.get('interactive'))
        payload_specific_to_type = values.get(msg_type)

        if msg_type and payload_specific_to_type is None:
            # This error means, e.g., message_type is "text" but "text" field is null/missing in the config
            raise ValueError(f"Payload for message_type '{msg_type}' (expected field '{msg_type}') is missing or null.")

        # Ensure all other message type payloads are None
        defined_payload_fields = {"text", "image", "document", "audio", "video", "sticker", "interactive", "template", "contacts", "location"}
        for field_name in defined_payload_fields:
            if field_name != msg_type and values.get(field_name) is not None:
                raise ValueError(f"Field '{field_name}' should not be present when message_type is '{msg_type}'.")

        if msg_type == 'interactive':
            interactive_payload = values.get('interactive') # This is InteractiveMessagePayload object
            if not interactive_payload or not getattr(interactive_payload, 'type', None):
                raise ValueError("For 'interactive' messages, the 'interactive' payload object must exist and itself specify an interactive 'type' (e.g., 'button', 'list').")
            # Further validation for interactive subtypes can be done within InteractiveMessagePayload if needed
            # e.g. if interactive_payload.type == "button", check interactive_payload.action is InteractiveButtonAction
            if interactive_payload.type == "button" and not isinstance(interactive_payload.action, InteractiveButtonAction):
                raise ValueError("For interactive message_type 'button', action must be of type 'InteractiveButtonAction'.")
            if interactive_payload.type == "list" and not isinstance(interactive_payload.action, InteractiveListAction):
                raise ValueError("For interactive message_type 'list', action must be of type 'InteractiveListAction'.")
        return values

class ReplyConfig(BasePydanticConfig):
    save_to_variable: str = Field(..., min_length=1)
    expected_type: Literal["text", "email", "number", "interactive_id", "any"] = "any" # Added "any"
    validation_regex: Optional[str] = None
    # allow_empty_reply: bool = False # Future consideration

class StepConfigQuestion(BasePydanticConfig):
    message_config: Dict[str, Any] # This will be validated by StepConfigSendMessage
    reply_config: ReplyConfig

    @field_validator('message_config')
    def validate_message_config_structure(cls, v_dict):
        try:
            # Validate that the dictionary can be parsed by StepConfigSendMessage
            StepConfigSendMessage.model_validate(v_dict)
            return v_dict # Return the original dict as per model type
        except ValidationError as e:
            logger.error(f"Invalid message_config for question step: {e.errors()}", exc_info=False) # Log with less noise
            raise ValueError(f"message_config for question is invalid: {e.errors()}")

class ActionItemConfig(BasePydanticConfig):
    action_type: Literal["set_context_variable", "update_contact_field", "update_customer_profile", "switch_flow"]
    variable_name: Optional[str] = None
    value_template: Optional[Any] = None # Can be string, dict, list for complex values
    field_path: Optional[str] = None # For update_contact_field, e.g. "name" or "custom_fields.some_key"
    fields_to_update: Optional[Dict[str, Any]] = None # For update_customer_profile
    target_flow_name: Optional[str] = None
    initial_context_template: Optional[Dict[str, Any]] = Field(default_factory=dict)
    message_to_evaluate_for_new_flow: Optional[str] = None # If flow switch needs to re-evaluate new message

    @root_validator(pre=False, skip_on_failure=True)
    def check_action_fields(cls, values):
        action_type = values.get('action_type')
        if action_type == 'set_context_variable':
            if values.get('variable_name') is None or 'value_template' not in values: # value_template can be null explicitly
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
    notification_details: Optional[str] = Field(default="Contact requires human assistance from flow.") # Default notification

class StepConfigEndFlow(BasePydanticConfig):
    message_config: Optional[Dict[str, Any]] = None # This will be validated by StepConfigSendMessage

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

# Rebuild models if necessary, useful for forward references in Union
InteractiveMessagePayload.model_rebuild()


def _get_value_from_context_or_contact(variable_path: str, flow_context: dict, contact: Contact) -> Any:
    logger.debug(f"Resolving variable path: '{variable_path}' for contact {contact.whatsapp_id}")
    if not variable_path:
        logger.debug("Empty variable_path received.")
        return None

    parts = variable_path.split('.')
    source_object_name = parts[0]
    current_value = None

    if source_object_name == 'flow_context':
        current_value = flow_context
        path_to_traverse = parts[1:]
        logger.debug(f"Accessing flow_context. Path to traverse: {path_to_traverse}")
    elif source_object_name == 'contact':
        current_value = contact
        path_to_traverse = parts[1:]
        logger.debug(f"Accessing contact attributes. Path to traverse: {path_to_traverse}")
    elif source_object_name == 'customer_profile':
        try:
            current_value = contact.customer_profile
            path_to_traverse = parts[1:]
            logger.debug(f"Accessing customer_profile attributes. Path to traverse: {path_to_traverse}")
        except CustomerProfile.DoesNotExist:
            logger.debug(f"CustomerProfile does not exist for contact {contact.id} when accessing '{variable_path}'")
            return None
        except AttributeError: # Should not happen if related_name is standard
            logger.warning(f"Contact {contact.id} has no customer_profile related object for path '{variable_path}'")
            return None
    else: # Default to flow_context if no prefix or unknown prefix
        current_value = flow_context
        path_to_traverse = parts
        logger.debug(f"Defaulting to flow_context for path '{variable_path}'. Path to traverse: {path_to_traverse}")

    for i, part in enumerate(path_to_traverse):
        if current_value is None:
            logger.debug(f"Intermediate value became None at part '{part}' for path '{variable_path}'.")
            return None
        try:
            if isinstance(current_value, dict):
                current_value = current_value.get(part)
            elif hasattr(current_value, part):
                attr_or_method = getattr(current_value, part)
                if callable(attr_or_method):
                    # More robust check for no-argument methods (excluding 'self')
                    try:
                        num_args = -1
                        # Check for bound method (__func__) or regular function (__code__)
                        if hasattr(attr_or_method, '__func__'):
                            num_args = attr_or_method.__func__.__code__.co_argcount
                            if num_args == 1: # Only 'self'
                                current_value = attr_or_method()
                            else: # Method takes other arguments, don't call
                                logger.debug(f"Method '{part}' requires arguments, returning method itself for path '{variable_path}'.")
                                current_value = attr_or_method
                        elif hasattr(attr_or_method, '__code__'):
                            num_args = attr_or_method.__code__.co_argcount
                            if num_args == 0: # No args
                                current_value = attr_or_method()
                            else: # Function takes arguments, don't call
                                logger.debug(f"Function '{part}' requires arguments, returning function itself for path '{variable_path}'.")
                                current_value = attr_or_method
                        else: # Unknown callable type
                            logger.debug(f"Unknown callable type for '{part}', returning as is for path '{variable_path}'.")
                            current_value = attr_or_method
                    except AttributeError:
                        logger.debug(f"AttributeError inspecting callable '{part}', returning as is for path '{variable_path}'.")
                        current_value = attr_or_method # Fallback
                    except TypeError as te: # Call failed
                        logger.warning(f"TypeError calling method/function '{part}' for path '{variable_path}': {te}. Returning as is.")
                        current_value = attr_or_method # Fallback
                else: # Not callable, just an attribute
                    current_value = attr_or_method
            else: # Part not found as a dict key or attribute
                logger.debug(f"Part '{part}' not found in current object for path '{variable_path}'. Current object type: {type(current_value)}")
                return None
        except Exception as e:
            logger.warning(f"Error accessing part '{part}' of path '{variable_path}': {e}", exc_info=True)
            return None
    logger.debug(f"Resolved path '{variable_path}' to value: '{str(current_value)[:100]}{'...' if len(str(current_value)) > 100 else ''}'")
    return current_value

def _resolve_value(template_value: Any, flow_context: dict, contact: Contact) -> Any:
    if isinstance(template_value, str):
        # Regex to find {{ variable.path }} with optional spaces
        variable_pattern = re.compile(r"{{\s*([\w.]+)\s*}}")
        resolved_string = template_value
        
        # Iteratively resolve to handle nested templates, with a safety break
        for i in range(10): # Max 10 iterations to prevent infinite loops
            found_match_in_iteration = False
            # Using finditer to handle multiple matches and their positions for accurate replacement
            matches = list(variable_pattern.finditer(resolved_string))
            if not matches:
                break # No more template variables found

            new_parts = []
            last_end = 0
            for match in matches:
                new_parts.append(resolved_string[last_end:match.start()])
                var_path = match.group(1).strip()
                val = _get_value_from_context_or_contact(var_path, flow_context, contact)
                new_parts.append(str(val) if val is not None else '') # Replace None with empty string
                last_end = match.end()
                found_match_in_iteration = True
            
            new_parts.append(resolved_string[last_end:])
            new_string_iteration = "".join(new_parts)

            if new_string_iteration == resolved_string and found_match_in_iteration: # No change but matches were processed
                # This can happen if all found variables resolved to empty strings and original string was also combination of such
                pass 
            elif new_string_iteration == resolved_string: # No effective change, break
                break

            resolved_string = new_string_iteration
            if not variable_pattern.search(resolved_string): # No more patterns left after substitutions
                break
            if i == 9:
                logger.warning(f"Template string resolution reached max iterations for: '{template_value}'")

        return resolved_string
    elif isinstance(template_value, dict):
        return {k: _resolve_value(v, flow_context, contact) for k, v in template_value.items()}
    elif isinstance(template_value, list):
        return [_resolve_value(item, flow_context, contact) for item in template_value]
    return template_value # Return as is if not string, dict, or list

def _resolve_template_components(components_config: list, flow_context: dict, contact: Contact) -> list:
    if not components_config or not isinstance(components_config, list):
        logger.debug("_resolve_template_components: No components to resolve or invalid format.")
        return []
    try:
        # Deep copy to avoid modifying the original config dicts if they are part of a step
        resolved_components_list = json.loads(json.dumps(components_config))
        logger.debug(f"Resolving template components. Initial: {resolved_components_list}")

        for i, component in enumerate(resolved_components_list):
            if not isinstance(component, dict):
                logger.warning(f"Component at index {i} is not a dictionary, skipping: {component}")
                continue

            # Resolve parameters if they exist
            if isinstance(component.get('parameters'), list):
                for j, param in enumerate(component['parameters']):
                    if not isinstance(param, dict):
                        logger.warning(f"Parameter at index {j} in component {i} is not a dictionary, skipping: {param}")
                        continue
                    
                    param_type = param.get('type')
                    logger.debug(f"Resolving component {i}, param {j}, type '{param_type}'")

                    if 'text' in param and isinstance(param['text'], str):
                        param['text'] = _resolve_value(param['text'], flow_context, contact)
                        logger.debug(f"Resolved param text to: {param['text']}")
                    
                    # Resolve media links within parameters
                    if param_type in ['image', 'video', 'document'] and isinstance(param.get(param_type), dict):
                        media_obj = param[param_type]
                        if 'link' in media_obj and isinstance(media_obj['link'], str):
                            original_link = media_obj['link']
                            media_obj['link'] = _resolve_value(media_obj['link'], flow_context, contact)
                            logger.debug(f"Resolved media link from '{original_link}' to: {media_obj['link']}")
                    
                    # Resolve button payloads
                    if component.get('type') == 'button' and param.get('type') == 'payload' and 'payload' in param and isinstance(param['payload'], str):
                        original_payload = param['payload']
                        param['payload'] = _resolve_value(param['payload'], flow_context, contact)
                        logger.debug(f"Resolved button payload from '{original_payload}' to: {param['payload']}")

                    # Resolve fallback values for currency and date_time
                    if param_type == 'currency' and isinstance(param.get('currency'), dict) and 'fallback_value' in param['currency'] and isinstance(param['currency']['fallback_value'], str) :
                        original_fb_val = param['currency']['fallback_value']
                        param['currency']['fallback_value'] = _resolve_value(param['currency']['fallback_value'], flow_context, contact)
                        logger.debug(f"Resolved currency fallback from '{original_fb_val}' to: {param['currency']['fallback_value']}")

                    if param_type == 'date_time' and isinstance(param.get('date_time'), dict) and 'fallback_value' in param['date_time'] and isinstance(param['date_time']['fallback_value'], str):
                        original_fb_val = param['date_time']['fallback_value']
                        param['date_time']['fallback_value'] = _resolve_value(param['date_time']['fallback_value'], flow_context, contact)
                        logger.debug(f"Resolved date_time fallback from '{original_fb_val}' to: {param['date_time']['fallback_value']}")
            
            # Resolve button URL template (index based payload for URL buttons)
            # WhatsApp API uses 'index' for URL buttons, parameter is 'text' but it's the suffix.
            # Let's assume the full URL is in the parameter's 'text' field if sub_type is 'url' for now,
            # or that value_template is used more directly for this.
            # This part might need more specific logic based on how URL button templates are structured.
            # For now, parameters of type 'text' within button components are handled above.

        logger.debug(f"Finished resolving template components. Final: {resolved_components_list}")
        return resolved_components_list
    except Exception as e:
        logger.error(f"Error resolving template components: {e}. Original Config: {components_config}", exc_info=True)
        return components_config # Return original on error to avoid breaking further


def _clear_contact_flow_state(contact: Contact, error: bool = False, reason: str = ""):
    deleted_count, _ = ContactFlowState.objects.filter(contact=contact).delete()
    log_message = f"Cleared flow state for contact {contact.whatsapp_id}."
    if reason:
        log_message += f" Reason: {reason}."
    if error:
        log_message += " Due to an error."
    if deleted_count > 0:
        logger.info(log_message)
    else:
        logger.debug(f"No flow state to clear for contact {contact.whatsapp_id} (reason: {reason or 'N/A'}).")


def _execute_step_actions(step: FlowStep, contact: Contact, flow_context: dict, is_re_execution: bool = False) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    actions_to_perform = []
    raw_step_config = step.config or {}
    # Use a copy of the context for this step's execution to avoid modifications
    # affecting parallel evaluations or re-executions if the original is passed around.
    current_step_context = flow_context.copy()

    logger.debug(
        f"Executing actions for step '{step.name}' (ID: {step.id}, Type: {step.step_type}) "
        f"for contact {contact.whatsapp_id}. Is re-execution: {is_re_execution}. "
        f"Raw Config: {json.dumps(raw_step_config) if isinstance(raw_step_config, dict) else str(raw_step_config)}"
    )

    if step.step_type == 'send_message':
        try:
            # Pydantic model expects keys like "text", "interactive", not "text_config"
            send_message_config = StepConfigSendMessage.model_validate(raw_step_config)
            actual_message_type = send_message_config.message_type
            
            # This will be the dict for the specific message type, e.g., content of 'text', 'interactive'
            final_api_data_structure = {} 

            logger.debug(f"Validated send_message config. Type: '{actual_message_type}'.")

            if actual_message_type == "text" and send_message_config.text:
                text_content = send_message_config.text
                resolved_body = _resolve_value(text_content.body, current_step_context, contact)
                logger.debug(f"Resolved text body for step '{step.name}': '{resolved_body[:100]}{'...' if len(resolved_body) > 100 else ''}'")
                final_api_data_structure = {'body': resolved_body, 'preview_url': text_content.preview_url}

            elif actual_message_type in ['image', 'document', 'audio', 'video', 'sticker']:
                media_conf: Optional[MediaMessageContent] = getattr(send_message_config, actual_message_type, None)
                if media_conf:
                    media_data_to_send = {}
                    valid_source_found = False
                    if MEDIA_ASSET_ENABLED and media_conf.asset_pk:
                        try:
                            asset = MediaAsset.objects.get(pk=media_conf.asset_pk, company=contact.company) # Ensure company match
                            if asset.status == 'synced' and asset.whatsapp_media_id and not asset.is_whatsapp_id_potentially_expired():
                                media_data_to_send['id'] = asset.whatsapp_media_id
                                valid_source_found = True
                                logger.info(f"Using MediaAsset {asset.pk} ('{asset.name}') with WA ID: {asset.whatsapp_media_id} for step '{step.name}'.")
                            else:
                                logger.warning(f"MediaAsset {asset.pk} ('{asset.name}') not usable (Status: {asset.status}, Synced: {asset.status == 'synced'}, WA ID: {asset.whatsapp_media_id}, Expired: {asset.is_whatsapp_id_potentially_expired()}). Trying direct id/link for step '{step.name}'.")
                        except MediaAsset.DoesNotExist:
                            logger.error(f"MediaAsset pk={media_conf.asset_pk} (company: {contact.company.name}) not found. Trying direct id/link for step '{step.name}'.")
                    
                    if not valid_source_found:
                        if media_conf.id:
                            media_data_to_send['id'] = _resolve_value(media_conf.id, current_step_context, contact)
                            valid_source_found = True
                            logger.debug(f"Using direct media ID '{media_data_to_send['id']}' for step '{step.name}'.")
                        elif media_conf.link:
                            media_data_to_send['link'] = _resolve_value(media_conf.link, current_step_context, contact)
                            valid_source_found = True
                            logger.debug(f"Using direct media link '{media_data_to_send['link']}' for step '{step.name}'.")
                    
                    if not valid_source_found:
                        logger.error(f"No valid media source (asset_pk, id, or link) provided for '{actual_message_type}' in step '{step.name}'. Message will not be sent.")
                    else:
                        if media_conf.caption:
                            media_data_to_send['caption'] = _resolve_value(media_conf.caption, current_step_context, contact)
                        if actual_message_type == 'document' and media_conf.filename:
                            media_data_to_send['filename'] = _resolve_value(media_conf.filename, current_step_context, contact)
                        # The key in the final payload for WA is the message type itself (e.g. "image": {...})
                        # But _execute_step_actions returns a generic 'data' field,
                        # the caller (_send_prepared_actions) will structure it correctly.
                        # So, final_api_data_structure here should BE the media object.
                        final_api_data_structure = media_data_to_send 
                else:
                    logger.error(f"'{actual_message_type}_config' is None in validated StepConfigSendMessage for step '{step.name}'. This indicates an issue with Pydantic model or config.")


            elif actual_message_type == "interactive" and send_message_config.interactive:
                interactive_payload_obj = send_message_config.interactive # This is InteractiveMessagePayload object
                # Dump to dict, then resolve any template strings within its structure
                interactive_payload_dict = interactive_payload_obj.model_dump(exclude_none=True, by_alias=True)
                # _resolve_value handles dicts and lists recursively
                resolved_interactive_dict = _resolve_value(interactive_payload_dict, current_step_context, contact)
                logger.debug(f"Resolved interactive payload for step '{step.name}': {json.dumps(resolved_interactive_dict, indent=2)}")
                final_api_data_structure = resolved_interactive_dict # This is the 'interactive' object for WA API

            elif actual_message_type == "template" and send_message_config.template:
                template_payload_obj = send_message_config.template # TemplateMessageContent object
                template_payload_dict = template_payload_obj.model_dump(exclude_none=True, by_alias=True)
                if 'components' in template_payload_dict and template_payload_dict['components']:
                    template_payload_dict['components'] = _resolve_template_components(
                        template_payload_dict['components'], current_step_context, contact
                    )
                logger.debug(f"Resolved template payload for step '{step.name}': {json.dumps(template_payload_dict, indent=2)}")
                final_api_data_structure = template_payload_dict # This is the 'template' object for WA API
            
            elif actual_message_type == "contacts" and send_message_config.contacts:
                contacts_list_of_objects = send_message_config.contacts
                contacts_list_of_dicts = [c.model_dump(exclude_none=True, by_alias=True) for c in contacts_list_of_objects]
                resolved_contacts_list = _resolve_value(contacts_list_of_dicts, current_step_context, contact)
                logger.debug(f"Resolved contacts payload for step '{step.name}': {json.dumps(resolved_contacts_list, indent=2)}")
                final_api_data_structure = {"contacts": resolved_contacts_list} # WA API expects {"contacts": [...]}

            elif actual_message_type == "location" and send_message_config.location:
                location_obj = send_message_config.location
                location_dict = location_obj.model_dump(exclude_none=True, by_alias=True)
                resolved_location_dict = _resolve_value(location_dict, current_step_context, contact)
                logger.debug(f"Resolved location payload for step '{step.name}': {json.dumps(resolved_location_dict, indent=2)}")
                final_api_data_structure = resolved_location_dict # This is the 'location' object for WA API

            if final_api_data_structure:
                logger.info(f"Prepared '{actual_message_type}' message data for step '{step.name}'. Data snippet: {str(final_api_data_structure)[:200]}...")
                actions_to_perform.append({
                    'type': 'send_whatsapp_message',
                    'recipient_wa_id': contact.whatsapp_id,
                    'message_type': actual_message_type, # e.g., "text", "interactive"
                    'data': final_api_data_structure # This is the specific payload for that type
                                                     # e.g. for text: {'body': ..., 'preview_url': ...}
                                                     # e.g. for interactive: {'type': 'list', 'header': ..., ...}
                })
            elif actual_message_type: # Type was valid, but no data structure generated (e.g. media source fail)
                logger.warning(
                    f"No data payload generated for message_type '{actual_message_type}' in step '{step.name}'. "
                    f"This might be due to missing media sources or unresolved templates resulting in empty required fields. "
                    f"Validated Pydantic Config (model dump): {send_message_config.model_dump_json(indent=2) if send_message_config else 'None'}"
                )
        except ValidationError as e:
            logger.error(f"Pydantic validation error for 'send_message' step '{step.name}' config: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
            # Optionally, could clear flow state here or let it be handled by a generic error handler later
        except Exception as e:
            logger.error(f"Unexpected error processing 'send_message' step '{step.name}': {e}", exc_info=True)

    elif step.step_type == 'question':
        try:
            question_config = StepConfigQuestion.model_validate(raw_step_config)
            logger.debug(f"Validated 'question' step '{step.name}' config.")
            # Send the question message part only if not re-executing for a fallback of the same question
            if question_config.message_config and not is_re_execution:
                logger.info(f"Processing message_config for question step '{step.name}'.")
                try:
                    # Validate and prepare message_config as if it's a regular send_message step
                    # The message_config itself is the raw_config for a StepConfigSendMessage
                    temp_msg_pydantic_config = StepConfigSendMessage.model_validate(question_config.message_config)
                    
                    # Create a temporary dummy FlowStep to reuse _execute_step_actions for message sending
                    # Ensure the dummy step's config is the *model_dump* of the validated temp_msg_pydantic_config
                    # because _execute_step_actions expects the raw dict config.
                    dummy_send_step = FlowStep(
                        name=f"{step.name}_prompt_message", 
                        step_type="send_message", 
                        config=temp_msg_pydantic_config.model_dump() # Use model_dump() to get dict form of validated config
                    )
                    send_actions, _ = _execute_step_actions(dummy_send_step, contact, current_step_context.copy()) # Pass copy of context
                    actions_to_perform.extend(send_actions)
                    logger.debug(f"Generated {len(send_actions)} send actions for question prompt of step '{step.name}'.")
                except ValidationError as ve:
                    logger.error(f"Pydantic validation error for 'message_config' within 'question' step '{step.name}': {ve.errors()}", exc_info=False)
                except Exception as ex_msg_conf:
                    logger.error(f"Error processing message_config for 'question' step '{step.name}': {ex_msg_conf}", exc_info=True)
            
            if question_config.reply_config:
                # This context key signals that the flow is now waiting for a reply for this question.
                # It will be checked when the next message comes in.
                current_step_context['_question_awaiting_reply_for'] = {
                    'variable_name': question_config.reply_config.save_to_variable,
                    'expected_type': question_config.reply_config.expected_type,
                    'validation_regex': question_config.reply_config.validation_regex,
                    'original_question_step_id': step.id # Store ID to ensure re-prompts match original question
                }
                logger.info(f"Step '{step.name}' is a question, awaiting reply to be saved in '{question_config.reply_config.save_to_variable}'. Expecting type: '{question_config.reply_config.expected_type}'.")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'question' step '{step.name}' failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_q_step:
            logger.error(f"Unexpected error in 'question' step '{step.name}': {e_q_step}", exc_info=True)


    elif step.step_type == 'action':
        try:
            action_step_config = StepConfigAction.model_validate(raw_step_config)
            logger.debug(f"Validated 'action' step '{step.name}' config with {len(action_step_config.actions_to_run)} actions.")
            for i, action_item_conf in enumerate(action_step_config.actions_to_run):
                action_type = action_item_conf.action_type
                logger.info(f"Executing action item {i+1}/{len(action_step_config.actions_to_run)} of type '{action_type}' for step '{step.name}'.")
                if action_type == 'set_context_variable' and action_item_conf.variable_name is not None:
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    current_step_context[action_item_conf.variable_name] = resolved_value
                    logger.info(f"Action result: Context variable '{action_item_conf.variable_name}' set to: '{str(resolved_value)[:100]}'.")
                
                elif action_type == 'update_contact_field' and action_item_conf.field_path is not None:
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    _update_contact_data(contact, action_item_conf.field_path, resolved_value) # This function logs internally
                
                elif action_type == 'update_customer_profile' and action_item_conf.fields_to_update is not None:
                    # Ensure fields_to_update is a dict before resolving, as _resolve_value expects it.
                    if isinstance(action_item_conf.fields_to_update, dict):
                        resolved_fields_to_update = _resolve_value(action_item_conf.fields_to_update, current_step_context, contact)
                        _update_customer_profile_data(contact, resolved_fields_to_update, current_step_context) # This logs internally
                    else:
                        logger.error(f"Action 'update_customer_profile' in step '{step.name}' has invalid 'fields_to_update' (not a dict): {action_item_conf.fields_to_update}")
                
                elif action_type == 'switch_flow' and action_item_conf.target_flow_name is not None:
                    resolved_initial_context = _resolve_value(action_item_conf.initial_context_template or {}, current_step_context, contact)
                    resolved_msg_body = _resolve_value(action_item_conf.message_to_evaluate_for_new_flow, current_step_context, contact) if action_item_conf.message_to_evaluate_for_new_flow else None
                    
                    logger.info(f"Action: Queuing switch to flow '{action_item_conf.target_flow_name}' from step '{step.name}'. Initial context: {resolved_initial_context}, Trigger message: '{resolved_msg_body}'")
                    actions_to_perform.append({
                        'type': '_internal_command_switch_flow',
                        'target_flow_name': action_item_conf.target_flow_name,
                        'initial_context': resolved_initial_context if isinstance(resolved_initial_context, dict) else {},
                        'new_flow_trigger_message_body': resolved_msg_body
                    })
                    # If a switch flow action is encountered, usually no further actions in THIS step should run
                    # The flow processing loop in `process_message_for_flow` will handle the switch.
                    logger.debug(f"Switch flow action encountered in step '{step.name}'. Subsequent actions in this step will be skipped if switch is processed first.")
                    break # Stop processing further actions in this step if switching flow
                else:
                    logger.warning(f"Unknown or misconfigured action_item_type '{action_type}' in step '{step.name}'. Config: {action_item_conf.model_dump_json()}")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'action' step '{step.name}' failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_act_step:
            logger.error(f"Unexpected error in 'action' step '{step.name}': {e_act_step}", exc_info=True)


    elif step.step_type == 'end_flow':
        try:
            end_flow_config = StepConfigEndFlow.model_validate(raw_step_config)
            logger.info(f"Executing 'end_flow' step '{step.name}'.")
            if end_flow_config.message_config:
                logger.debug(f"End_flow step '{step.name}' has a final message to send.")
                try:
                    final_msg_pydantic_config = StepConfigSendMessage.model_validate(end_flow_config.message_config)
                    dummy_end_msg_step = FlowStep(name=f"{step.name}_final_msg", step_type="send_message", config=final_msg_pydantic_config.model_dump())
                    send_actions, _ = _execute_step_actions(dummy_end_msg_step, contact, current_step_context.copy())
                    actions_to_perform.extend(send_actions)
                    logger.debug(f"Generated {len(send_actions)} send actions for end_flow message of step '{step.name}'.")
                except ValidationError as ve:
                    logger.error(f"Pydantic validation error for 'message_config' in 'end_flow' step '{step.name}': {ve.errors()}", exc_info=False)
                except Exception as ex_end_msg:
                     logger.error(f"Error processing message_config for 'end_flow' step '{step.name}': {ex_end_msg}", exc_info=True)
            
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Flow ended at step {step.name}'})
            logger.info(f"Flow ended for contact {contact.whatsapp_id} at step '{step.name}'. Flow state will be cleared.")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'end_flow' step '{step.name}' config: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_end_step:
            logger.error(f"Unexpected error in 'end_flow' step '{step.name}': {e_end_step}", exc_info=True)


    elif step.step_type == 'human_handover':
        try:
            handover_config = StepConfigHumanHandover.model_validate(raw_step_config)
            logger.info(f"Executing 'human_handover' step '{step.name}' for contact {contact.whatsapp_id}.")
            if handover_config.pre_handover_message_text and not is_re_execution: # Avoid sending pre-handover msg on re-prompt scenario if any
                resolved_msg = _resolve_value(handover_config.pre_handover_message_text, current_step_context, contact)
                logger.debug(f"Sending pre-handover message for step '{step.name}': '{resolved_msg}'")
                actions_to_perform.append({
                    'type': 'send_whatsapp_message', 
                    'recipient_wa_id': contact.whatsapp_id, 
                    'message_type': 'text', 
                    'data': {'body': resolved_msg}
                })
            
            contact.needs_human_intervention = True
            contact.intervention_requested_at = timezone.now()
            contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
            logger.info(f"Contact {contact.whatsapp_id} (Name: {contact.name}) flagged for human intervention from step '{step.name}'.")
            
            notification_info = _resolve_value(
                handover_config.notification_details or f"Contact {contact.name or contact.whatsapp_id} requires help (flow step: {step.name}).",
                current_step_context,
                contact
            )
            # This log is for backend/CRM systems to pick up, not for WhatsApp.
            logger.info(f"HUMAN_INTERVENTION_ALERT: Contact: {contact.whatsapp_id}, Name: {contact.name}, Details: {notification_info}, Context: {json.dumps(current_step_context)}")
            
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Human handover at step {step.name}'})
            logger.info(f"Human handover initiated for contact {contact.whatsapp_id}. Flow state will be cleared.")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'human_handover' step '{step.name}' failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_hh_step:
            logger.error(f"Unexpected error in 'human_handover' step '{step.name}': {e_hh_step}", exc_info=True)

    elif step.step_type in ['condition', 'wait_for_reply', 'start_flow_node']: # 'start_flow_node' is conceptual
        logger.debug(f"'{step.step_type}' step '{step.name}' is a structural node. No direct actions executed from this function; logic handled by flow control and transitions.")
    else:
        logger.warning(f"Unhandled step_type: '{step.step_type}' for step '{step.name}'. No actions executed.")

    logger.debug(f"Finished executing actions for step '{step.name}'. Generated {len(actions_to_perform)} actions. Updated context (snippet): {str(current_step_context)[:200]}...")
    return actions_to_perform, current_step_context


def _handle_active_flow_step(contact_flow_state: ContactFlowState, contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    current_step = contact_flow_state.current_step
    # Ensure flow_context is always a dict
    flow_context = contact_flow_state.flow_context_data if isinstance(contact_flow_state.flow_context_data, dict) else {}
    actions_to_perform = []

    logger.info(
        f"Handling active flow for contact {contact.whatsapp_id}. Current Flow: '{contact_flow_state.current_flow.name}', "
        f"Step: '{current_step.name}' (ID: {current_step.id}, Type: {current_step.step_type})."
    )
    logger.debug(f"Incoming message type: {message_data.get('type')}. Current flow context: {json.dumps(flow_context, indent=2)}")

    # Check if the current step is a question that was awaiting this reply
    question_expectation = flow_context.get('_question_awaiting_reply_for')
    if current_step.step_type == 'question' and \
       isinstance(question_expectation, dict) and \
       question_expectation.get('original_question_step_id') == current_step.id:
        
        variable_to_save_name = question_expectation.get('variable_name')
        expected_reply_type = question_expectation.get('expected_type')
        validation_regex_ctx = question_expectation.get('validation_regex')
        
        user_text = message_data.get('text', {}).get('body', '').strip() if message_data.get('type') == 'text' else None
        interactive_reply_id = None
        if message_data.get('type') == 'interactive':
            interactive_payload = message_data.get('interactive', {})
            interactive_type = interactive_payload.get('type')
            if interactive_type == 'button_reply':
                interactive_reply_id = interactive_payload.get('button_reply', {}).get('id')
            elif interactive_type == 'list_reply':
                interactive_reply_id = interactive_payload.get('list_reply', {}).get('id')
        
        logger.debug(f"Processing reply for question '{current_step.name}'. Expected type: '{expected_reply_type}'. User text: '{user_text}', Interactive ID: '{interactive_reply_id}'.")

        reply_is_valid = False
        value_to_save = None

        if expected_reply_type == 'text' and user_text:
            value_to_save = user_text
            reply_is_valid = True
            if validation_regex_ctx and not re.match(validation_regex_ctx, user_text):
                reply_is_valid = False
                value_to_save = None
                logger.debug(f"Text reply '{user_text}' did not match regex '{validation_regex_ctx}'.")
        elif expected_reply_type == 'email':
            email_r = validation_regex_ctx or r"^[a-zA-Z0-9._%+-]+@[a_zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if user_text and re.match(email_r, user_text):
                value_to_save = user_text
                reply_is_valid = True
            else:
                logger.debug(f"Email reply '{user_text}' did not match regex '{email_r}'.")
        elif expected_reply_type == 'number' and user_text:
            try:
                # Attempt to convert to float if decimal point present or regex suggests it, else int
                num_val = float(user_text) if '.' in user_text or (validation_regex_ctx and '.' in validation_regex_ctx) else int(user_text)
                if validation_regex_ctx and not re.match(validation_regex_ctx, user_text): # Validate original string for regex
                    logger.debug(f"Number string reply '{user_text}' did not match regex '{validation_regex_ctx}'.")
                else:
                    value_to_save = num_val
                    reply_is_valid = True
            except ValueError:
                logger.debug(f"Could not parse '{user_text}' as a number.")
        elif expected_reply_type == 'interactive_id' and interactive_reply_id:
            value_to_save = interactive_reply_id
            reply_is_valid = True
            # Regex validation for interactive_id if provided
            if validation_regex_ctx and not re.match(validation_regex_ctx, interactive_reply_id):
                reply_is_valid = False
                value_to_save = None
                logger.debug(f"Interactive ID reply '{interactive_reply_id}' did not match regex '{validation_regex_ctx}'.")
        elif expected_reply_type == 'any': # Accept any input as valid
             if user_text is not None: value_to_save = user_text
             elif interactive_reply_id is not None: value_to_save = interactive_reply_id
             # Potentially extend to other message types if needed
             else: value_to_save = message_data # Save the whole message data if no specific part extracted
             reply_is_valid = True


        if reply_is_valid and variable_to_save_name:
            flow_context[variable_to_save_name] = value_to_save
            logger.info(f"Saved valid reply for variable '{variable_to_save_name}' in question step '{current_step.name}'. Value: '{str(value_to_save)[:100]}'.")
            # Reply processed, remove expectation for this specific reply to allow transitions to check broader conditions
            # However, the _question_awaiting_reply_for itself is cleared in _transition_to_step if a transition is made.
            # If no transition is made, fallback logic below handles re-prompts.
        elif not reply_is_valid:
            logger.info(f"Reply for question step '{current_step.name}' was not valid. Expected: '{expected_reply_type}'.")
            # Fallback logic below will handle re-prompting or other actions.
            # Do not proceed to evaluate general transitions if reply was invalid for the question.
            # The fallback config of the question step should dictate next actions.
            
            fallback_config = current_step.config.get('fallback_config', {}) if isinstance(current_step.config, dict) else {}
            max_retries = fallback_config.get('max_retries', 1) # Default to 1 retry
            current_fallback_count = flow_context.get('_fallback_count', 0)

            if current_fallback_count < max_retries:
                logger.info(f"Invalid reply for question '{current_step.name}'. Re-prompting (Attempt {current_fallback_count + 1}/{max_retries}).")
                flow_context['_fallback_count'] = current_fallback_count + 1
                
                re_prompt_message_text = fallback_config.get('re_prompt_message_text')
                if re_prompt_message_text: # Custom re-prompt message
                    resolved_re_prompt_text = _resolve_value(re_prompt_message_text, flow_context, contact)
                    actions_to_perform.append({
                        'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                        'message_type': 'text', 'data': {'body': resolved_re_prompt_text}
                    })
                else: # Re-send original question message
                    step_actions, updated_context_from_re_execution = _execute_step_actions(current_step, contact, flow_context.copy(), is_re_execution=True)
                    actions_to_perform.extend(step_actions)
                    # Crucially, the re-execution should re-establish _question_awaiting_reply_for in its returned context
                    flow_context = updated_context_from_re_execution 
                
                contact_flow_state.flow_context_data = flow_context
                contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])
                return actions_to_perform # Stop further processing, wait for new reply
            else: # Max retries reached
                logger.info(f"Max retries ({max_retries}) reached for question '{current_step.name}'. Proceeding to fallback action (e.g., handover or different transition).")
                # Clear fallback count, proceed to general fallback logic (handover etc.) or transitions
                flow_context.pop('_fallback_count', None) 
                # Reply is still invalid, but we let transitions try or a final fallback take over.
                # No, if max retries reached, it should directly go to a final fallback action
                # like handover, or a specific "failed_question_transition"
                final_fallback_action = fallback_config.get('action_after_max_retries', 'human_handover') # Default to handover
                if final_fallback_action == 'human_handover':
                    logger.info(f"Max retries for question. Initiating human handover for contact {contact.whatsapp_id}.")
                    handover_msg = fallback_config.get('handover_message_text', "Sorry, I couldn't understand your response. Let me connect you to an agent.")
                    resolved_handover_msg = _resolve_value(handover_msg, flow_context, contact)
                    actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_handover_msg}})
                    actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Max retries for question {current_step.name}'})
                    contact.needs_human_intervention = True
                    contact.intervention_requested_at = timezone.now()
                    contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
                    return actions_to_perform
                elif final_fallback_action == 'end_flow':
                    actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Max retries for question {current_step.name}, ending flow.'})
                    return actions_to_perform
                # If other actions or specific transitions are needed after max retries, they should be configured.
                # For now, this makes it go to general transitions if not handover/end.

    # If not a question reply, or if question reply was valid, proceed to evaluate transitions
    transitions = FlowTransition.objects.filter(current_step=current_step).select_related('next_step').order_by('priority')
    next_step_to_transition_to = None
    transition_chosen = None

    logger.debug(f"Evaluating {transitions.count()} transitions for step '{current_step.name}'.")
    for transition in transitions:
        if _evaluate_transition_condition(transition, contact, message_data, flow_context.copy(), incoming_message_obj):
            next_step_to_transition_to = transition.next_step
            transition_chosen = transition
            logger.info(f"Transition condition met for transition ID {transition.id} (Priority: {transition.priority}): From '{current_step.name}' to '{next_step_to_transition_to.name}'.")
            break
    
    if next_step_to_transition_to:
        # Pass the current flow_context. _transition_to_step clears question-specific keys.
        actions_from_next_step, _ = _transition_to_step( # Context updates are saved by _transition_to_step
            contact_flow_state, next_step_to_transition_to, flow_context, contact, message_data
        )
        actions_to_perform.extend(actions_from_next_step)
    else: # No transition condition met
        logger.info(f"No transition conditions met from step '{current_step.name}' for contact {contact.whatsapp_id}.")
        # General fallback if no transition (not specific to question invalid reply)
        # This is for when the user types something unexpected at a non-question step,
        # or a question step where the valid reply didn't meet any specific transition condition.
        fallback_config = current_step.config.get('fallback_config', {}) if isinstance(current_step.config, dict) else {}
        
        if fallback_config.get('fallback_message_text'):
            resolved_fallback_text = _resolve_value(fallback_config['fallback_message_text'], flow_context, contact)
            logger.debug(f"Sending general fallback message for step '{current_step.name}': {resolved_fallback_text}")
            actions_to_perform.append({
                'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                'message_type': 'text', 'data': {'body': resolved_fallback_text}
            })
            if fallback_config.get('handover_after_message', False):
                logger.info(f"General fallback: Initiating human handover after fallback message for {contact.whatsapp_id} from step '{current_step.name}'.")
                actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'General fallback handover at {current_step.name}'})
                contact.needs_human_intervention = True
                contact.intervention_requested_at = timezone.now()
                contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
        
        elif fallback_config.get('action') == 'human_handover':
            logger.info(f"General fallback: Initiating human handover directly for {contact.whatsapp_id} from step '{current_step.name}'.")
            pre_handover_msg = fallback_config.get('pre_handover_message_text', "Let me connect you to an agent.")
            resolved_msg = _resolve_value(pre_handover_msg, flow_context, contact)
            actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_msg}})
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'General fallback direct handover at {current_step.name}'})
            contact.needs_human_intervention = True
            contact.intervention_requested_at = timezone.now()
            contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
        else:
            logger.info(f"No specific general fallback action for step '{current_step.name}'. Default behavior may apply or flow might stall if not ended.")
            # Consider a default "I didn't understand" if no actions and not a question step that re-prompted.
            if not actions_to_perform and current_step.step_type != 'question': # Avoid double message if question already handled fallback
                 actions_to_perform.append({
                    'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                    'message_type': 'text', 'data': {'body': "Sorry, I'm not sure how to proceed. Please try rephrasing or type 'menu'."}
                })


    return actions_to_perform


def _trigger_new_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    actions_to_perform = []
    initial_flow_context = {} # Can be populated by Flow.default_context or specific triggers later
    message_text_body = None
    
    if message_data.get('type') == 'text':
        message_text_body = message_data.get('text', {}).get('body', '').lower().strip()
        logger.debug(f"Attempting to trigger new flow with text: '{message_text_body}'")
    else:
        logger.debug(f"Attempting to trigger new flow with non-text message type: '{message_data.get('type')}'")

    triggered_flow = None
    # TODO: Consider a more sophisticated triggering mechanism (e.g., NLP intent, regex on Flow model)
    active_flows = Flow.objects.filter(is_active=True, company=contact.company).order_by('name') # Filter by company
    
    if message_text_body: # Keyword matching only for text messages for now
        for flow_candidate in active_flows:
            if isinstance(flow_candidate.trigger_keywords, list):
                for keyword in flow_candidate.trigger_keywords:
                    # Ensure keyword is a non-empty string before lowercasing and stripping
                    if isinstance(keyword, str) and keyword.strip():
                        processed_keyword = keyword.strip().lower()
                        # Exact match or keyword present in message (configurable?)
                        # For now, simple "in" check
                        if processed_keyword in message_text_body:
                            triggered_flow = flow_candidate
                            logger.info(f"Keyword '{processed_keyword}' triggered flow '{flow_candidate.name}' (ID: {flow_candidate.id}) for contact {contact.whatsapp_id}.")
                            break
            if triggered_flow:
                break
    
    if triggered_flow:
        entry_point_step = FlowStep.objects.filter(flow=triggered_flow, is_entry_point=True).first()
        if entry_point_step:
            logger.info(f"Starting flow '{triggered_flow.name}' for contact {contact.whatsapp_id} at entry step '{entry_point_step.name}' (ID: {entry_point_step.id}).")
            _clear_contact_flow_state(contact, reason=f"Starting new flow {triggered_flow.name}") 
            
            # Initialize context
            if isinstance(triggered_flow.default_flow_context, dict):
                initial_flow_context.update(triggered_flow.default_flow_context)
            # TODO: Add specific context from the trigger match if applicable in future

            contact_flow_state = ContactFlowState.objects.create(
                contact=contact,
                current_flow=triggered_flow,
                current_step=entry_point_step,
                flow_context_data=initial_flow_context, # Start with default or empty
                started_at=timezone.now()
            )
            logger.debug(f"Created ContactFlowState (pk={contact_flow_state.pk}) for contact {contact.whatsapp_id}. Initial context: {initial_flow_context}")

            # Execute actions for the entry point step
            # Pass a copy of the initial_flow_context to _execute_step_actions
            step_actions, context_after_entry_step = _execute_step_actions(entry_point_step, contact, initial_flow_context.copy())
            actions_to_perform.extend(step_actions)
            
            # Re-fetch state to see if it was cleared or changed by the entry step itself
            current_db_state = ContactFlowState.objects.filter(pk=contact_flow_state.pk).first()
            if current_db_state:
                # Only update context if it has changed and state still exists
                if current_db_state.flow_context_data != context_after_entry_step:
                    logger.debug(f"Context changed by entry step '{entry_point_step.name}'. Old: {current_db_state.flow_context_data}, New: {context_after_entry_step}")
                    current_db_state.flow_context_data = context_after_entry_step
                    current_db_state.save(update_fields=['flow_context_data', 'last_updated_at'])
            else:
                logger.info(f"Flow state for contact {contact.whatsapp_id} was cleared by the entry step '{entry_point_step.name}' itself. Context not re-saved for this state object.")
        else:
            logger.error(f"Flow '{triggered_flow.name}' (ID: {triggered_flow.id}) is active but has no entry point step defined.")
    else:
        logger.info(f"No active flow triggered for contact {contact.whatsapp_id}. Incoming message (type: {message_data.get('type')}, text snippet: '{message_text_body[:100] if message_text_body else 'N/A'}').")
        # Optionally send a default "I don't understand" message if no flow is triggered.
        # This should be configurable at a company/integration level.
        # actions_to_perform.append({'type': 'send_whatsapp_message', ... 'data': {'body': "Sorry, I didn't understand that."}})

    return actions_to_perform

def _evaluate_transition_condition(
    transition: FlowTransition, 
    contact: Contact, 
    message_data: dict, # Can be empty for automatic transitions
    flow_context: dict, 
    incoming_message_obj: Optional[Message] # Can be None for automatic transitions
) -> bool:
    config = transition.condition_config
    if not isinstance(config, dict):
        logger.warning(f"Transition ID {transition.id} (step '{transition.current_step.name}') has invalid condition_config (not a dict): {config}")
        return False
    
    condition_type = config.get('type')
    is_automatic_check = not message_data # Heuristic: if message_data is empty, it's likely an auto-check

    log_message_info = f"MsgType: {message_data.get('type', 'N/A')}" if not is_automatic_check else "Automatic Check"
    logger.debug(
        f"Evaluating condition type '{condition_type}' for T_ID {transition.id} "
        f"(Step '{transition.current_step.name}' -> '{transition.next_step.name if transition.next_step else 'END'}'). "
        f"{log_message_info}. Context (snippet): {str(flow_context)[:100]}..."
    )

    if not condition_type:
        logger.warning(f"Transition ID {transition.id} has no 'type' in condition_config.")
        return False
    if condition_type == 'always_true':
        logger.debug(f"Transition ID {transition.id}: 'always_true' condition met.")
        return True

    # Conditions requiring user message data should fail if it's an automatic check
    user_dependent_conditions = [
        'user_reply_matches_keyword', 'user_reply_contains_keyword', 
        'interactive_reply_id_equals', 'message_type_is', 
        'user_reply_matches_regex', 'nfm_response_field_equals',
        'user_requests_human', 'user_reply_received' 
        # 'question_reply_is_valid' can be true even without new message if context var was set by previous valid reply
    ]
    if is_automatic_check and condition_type in user_dependent_conditions and condition_type != 'question_reply_is_valid': # question_reply_is_valid is special
        logger.debug(f"Transition ID {transition.id}: Condition '{condition_type}' requires user message; not met for automatic check.")
        return False

    user_text = ""
    if message_data and message_data.get('type') == 'text' and isinstance(message_data.get('text'), dict):
        user_text = message_data.get('text', {}).get('body', '').strip()

    interactive_reply_id = None
    nfm_response_data = None # For NFM (Notification Message) replies
    if message_data and message_data.get('type') == 'interactive' and isinstance(message_data.get('interactive'), dict):
        interactive_payload = message_data.get('interactive', {})
        interactive_type_from_payload = interactive_payload.get('type')
        if interactive_type_from_payload == 'button_reply' and isinstance(interactive_payload.get('button_reply'), dict):
            interactive_reply_id = interactive_payload.get('button_reply', {}).get('id')
        elif interactive_type_from_payload == 'list_reply' and isinstance(interactive_payload.get('list_reply'), dict):
            interactive_reply_id = interactive_payload.get('list_reply', {}).get('id')
        elif interactive_type_from_payload == 'nfm_reply' and isinstance(interactive_payload.get('nfm_reply'), dict):
            nfm_payload = interactive_payload.get('nfm_reply', {}) # Structure for NFM replies
            response_json_str = nfm_payload.get('response_json')
            if response_json_str:
                try: 
                    nfm_response_data = json.loads(response_json_str)
                except json.JSONDecodeError: 
                    logger.warning(f"Could not parse nfm_reply response_json for transition {transition.id}: {response_json_str[:100]}")

    value_for_condition_comparison = config.get('value') # The value to compare against

    # --- Condition Type Logic ---
    if condition_type == 'user_reply_matches_keyword':
        if not user_text: return False
        keyword = str(config.get('keyword', '')).strip()
        if not keyword: logger.warning(f"T_ID {transition.id}: 'user_reply_matches_keyword' missing keyword."); return False
        is_match = (keyword == user_text) if config.get('case_sensitive', False) else (keyword.lower() == user_text.lower())
        logger.debug(f"T_ID {transition.id} ('user_reply_matches_keyword'): Text '{user_text}' vs Keyword '{keyword}'. Match: {is_match}")
        return is_match
    
    elif condition_type == 'user_reply_contains_keyword':
        if not user_text: return False
        keyword = str(config.get('keyword', '')).strip()
        if not keyword: logger.warning(f"T_ID {transition.id}: 'user_reply_contains_keyword' missing keyword."); return False
        is_match = (keyword in user_text) if config.get('case_sensitive', False) else (keyword.lower() in user_text.lower())
        logger.debug(f"T_ID {transition.id} ('user_reply_contains_keyword'): Text '{user_text}' vs Keyword '{keyword}'. Contains: {is_match}")
        return is_match

    elif condition_type == 'interactive_reply_id_equals':
        if interactive_reply_id is None: return False
        expected_id = str(value_for_condition_comparison)
        is_match = interactive_reply_id == expected_id
        logger.debug(f"T_ID {transition.id} ('interactive_reply_id_equals'): Received ID '{interactive_reply_id}' vs Expected ID '{expected_id}'. Match: {is_match}")
        return is_match

    elif condition_type == 'message_type_is':
        if not message_data or not message_data.get('type'): return False
        is_match = message_data.get('type') == str(value_for_condition_comparison)
        logger.debug(f"T_ID {transition.id} ('message_type_is'): Received Type '{message_data.get('type')}' vs Expected Type '{value_for_condition_comparison}'. Match: {is_match}")
        return is_match

    elif condition_type == 'user_reply_matches_regex':
        if not user_text: return False
        regex = config.get('regex')
        if not regex: logger.warning(f"T_ID {transition.id}: 'user_reply_matches_regex' missing regex pattern."); return False
        try:
            is_match = bool(re.match(regex, user_text))
            logger.debug(f"T_ID {transition.id} ('user_reply_matches_regex'): Text '{user_text}' vs Regex '{regex}'. Match: {is_match}")
            return is_match
        except re.error as e:
            logger.error(f"Invalid regex in transition {transition.id}: '{regex}'. Error: {e}")
            return False
    
    # Conditions that can be checked automatically (without new user message)
    elif condition_type == 'variable_equals':
        variable_name = config.get('variable_name')
        if variable_name is None: logger.warning(f"T_ID {transition.id}: 'variable_equals' missing variable_name."); return False
        actual_value = _get_value_from_context_or_contact(variable_name, flow_context, contact)
        # Compare string representations for simplicity unless types are critical and handled
        expected_value_str = str(value_for_condition_comparison)
        actual_value_str = str(actual_value)
        is_match = actual_value_str == expected_value_str
        logger.debug(f"T_ID {transition.id} ('variable_equals'): Var '{variable_name}' (Actual: '{actual_value_str}') vs Expected: '{expected_value_str}'. Match: {is_match}")
        return is_match

    elif condition_type == 'variable_exists':
        variable_name = config.get('variable_name')
        if variable_name is None: logger.warning(f"T_ID {transition.id}: 'variable_exists' missing variable_name."); return False
        exists = _get_value_from_context_or_contact(variable_name, flow_context, contact) is not None
        logger.debug(f"T_ID {transition.id} ('variable_exists'): Var '{variable_name}'. Exists: {exists}")
        return exists

    elif condition_type == 'variable_contains':
        variable_name = config.get('variable_name')
        if variable_name is None: logger.warning(f"T_ID {transition.id}: 'variable_contains' missing variable_name."); return False
        actual_value = _get_value_from_context_or_contact(variable_name, flow_context, contact)
        expected_item_to_contain = value_for_condition_comparison
        contains = False
        if isinstance(actual_value, str) and isinstance(expected_item_to_contain, str):
            contains = expected_item_to_contain in actual_value
        elif isinstance(actual_value, list) and expected_item_to_contain is not None:
            contains = expected_item_to_contain in actual_value
        logger.debug(f"T_ID {transition.id} ('variable_contains'): Var '{variable_name}' (Value: '{str(actual_value)[:50]}') vs Expected Item: '{str(expected_item_to_contain)[:50]}'. Contains: {contains}")
        return contains

    elif condition_type == 'nfm_response_field_equals':
        if not nfm_response_data: return False # Needs NFM reply
        field_path = config.get('field_path')
        if not field_path: logger.warning(f"T_ID {transition.id}: 'nfm_response_field_equals' missing field_path."); return False
        
        actual_val_from_nfm = nfm_response_data
        try:
            for part in field_path.split('.'):
                if isinstance(actual_val_from_nfm, dict):
                    actual_val_from_nfm = actual_val_from_nfm.get(part)
                elif isinstance(actual_val_from_nfm, list) and part.isdigit(): # Basic list index access
                    idx = int(part)
                    if 0 <= idx < len(actual_val_from_nfm): actual_val_from_nfm = actual_val_from_nfm[idx]
                    else: actual_val_from_nfm = None; break
                else: actual_val_from_nfm = None; break
        except Exception: actual_val_from_nfm = None

        is_match = actual_val_from_nfm == value_for_condition_comparison
        logger.debug(f"T_ID {transition.id} ('nfm_response_field_equals'): Path '{field_path}' (Actual NFM val: '{actual_val_from_nfm}') vs Expected: '{value_for_condition_comparison}'. Match: {is_match}")
        return is_match

    elif condition_type == 'question_reply_is_valid':
        # This checks if the *last processed reply* for the question associated with this context was valid
        question_expectation = flow_context.get('_question_awaiting_reply_for')
        expected_bool_value = bool(value_for_condition_comparison is True) # True if value is True, False otherwise

        if question_expectation and isinstance(question_expectation, dict):
            # A question was asked and is the current context focus
            var_name_for_reply = question_expectation.get('variable_name')
            # If var_name_for_reply is in flow_context, it means a valid reply was saved.
            # Note: This implies the reply processing logic in _handle_active_flow_step correctly sets the variable
            # ONLY IF the reply is valid as per its specific type/regex.
            is_var_set_and_not_none = var_name_for_reply in flow_context and flow_context.get(var_name_for_reply) is not None
            
            logger.debug(f"T_ID {transition.id} ('question_reply_is_valid'): Expected valid = {expected_bool_value}. Actual reply was valid (var '{var_name_for_reply}' set): {is_var_set_and_not_none}.")
            return is_var_set_and_not_none if expected_bool_value else not is_var_set_and_not_none
        else: # No question is actively awaiting reply in this context, so "reply is valid" is usually false.
            logger.debug(f"T_ID {transition.id} ('question_reply_is_valid'): No active question expectation. Expected valid = {expected_bool_value}. Returning False for positive check, True for negative check.")
            return not expected_bool_value # If expecting valid=true, this fails. If expecting valid=false, this passes.

    elif condition_type == 'user_requests_human':
        if not user_text: return False
        human_request_keywords = config.get('keywords', ['help', 'support', 'agent', 'human', 'operator', 'talk to someone'])
        if isinstance(human_request_keywords, list):
            user_text_lower = user_text.lower()
            for keyword in human_request_keywords:
                if isinstance(keyword, str) and keyword.strip():
                    processed_keyword = keyword.strip().lower()
                    if processed_keyword in user_text_lower:
                        logger.info(f"T_ID {transition.id}: User requested human agent with keyword: '{processed_keyword}' in text '{user_text_lower}'.")
                        return True
        return False
        
    elif condition_type == 'user_reply_received': # Generic check if any user message came in for this interaction cycle
        # This is true if message_data is populated (meaning it's not an automatic transition check)
        # and message_data actually contains a message type.
        if not is_automatic_check and message_data and message_data.get('type'):
            logger.debug(f"T_ID {transition.id}: Condition 'user_reply_received' met because a message of type '{message_data.get('type')}' was part of current processing cycle.")
            return True
        logger.debug(f"T_ID {transition.id}: Condition 'user_reply_received' not met (is_automatic_check: {is_automatic_check} or no message type in message_data).")
        return False

    logger.warning(f"Unknown or unhandled condition type: '{condition_type}' for transition ID {transition.id} (Step '{transition.current_step.name}').")
    return False


def _process_automatic_transitions(contact_flow_state: ContactFlowState, contact: Contact) -> List[Dict[str, Any]]:
    accumulated_actions = []
    max_auto_transitions = 10  # Safety break to prevent infinite loops
    transitions_count = 0

    logger.debug(f"Attempting automatic transitions for contact {contact.whatsapp_id}, starting from step '{contact_flow_state.current_step.name}'.")

    while transitions_count < max_auto_transitions:
        # Important: Re-fetch current_step and flow_context inside the loop,
        # as they are mutated by _transition_to_step via contact_flow_state.
        current_step = contact_flow_state.current_step # This object gets updated if state changes
        flow_context = contact_flow_state.flow_context_data if isinstance(contact_flow_state.flow_context_data, dict) else {}

        logger.debug(f"Auto-transition loop iter {transitions_count + 1}. Contact {contact.whatsapp_id}, Step '{current_step.name}' (ID: {current_step.id}).")

        # Stop auto-transitions if the current step is a question that is actively awaiting a reply.
        # This is crucial to prevent skipping over a question step that expects user input.
        if current_step.step_type == 'question':
            question_expectation = flow_context.get('_question_awaiting_reply_for')
            if isinstance(question_expectation, dict) and question_expectation.get('original_question_step_id') == current_step.id:
                logger.info(f"Step '{current_step.name}' is a question actively awaiting reply. Halting automatic transitions for contact {contact.whatsapp_id}.")
                break
        
        transitions = FlowTransition.objects.filter(current_step=current_step).select_related('next_step').order_by('priority')
        if not transitions.exists():
            logger.debug(f"No outgoing transitions defined for step '{current_step.name}'. Stopping automatic transitions.")
            break
            
        next_step_to_transition_to = None
        chosen_transition_info = "None"

        for transition in transitions:
            # For automatic transitions, message_data is empty, incoming_message_obj is None.
            # _evaluate_transition_condition should handle this for user-input dependent conditions.
            if _evaluate_transition_condition(transition, contact, message_data={}, flow_context=flow_context.copy(), incoming_message_obj=None):
                next_step_to_transition_to = transition.next_step
                chosen_transition_info = f"ID {transition.id} (Priority {transition.priority})"
                logger.info(f"Automatic transition condition met: {chosen_transition_info}. From '{current_step.name}' to '{next_step_to_transition_to.name}'.")
                break
        
        if next_step_to_transition_to:
            # _transition_to_step updates contact_flow_state (current_step, context) and saves it.
            # It's crucial that flow_context passed here is the one from the step we are *leaving*.
            actions_from_transitioned_step, updated_context_after_new_step = _transition_to_step(
                contact_flow_state,           # This object gets updated by _transition_to_step
                next_step_to_transition_to,
                flow_context,                 # Context of the step being left
                contact,
                message_data={}               # Empty for auto-transitions
            )
            accumulated_actions.extend(actions_from_transitioned_step)
            logger.debug(f"Accumulated {len(actions_from_transitioned_step)} actions after auto-transition to '{next_step_to_transition_to.name}'. Total: {len(accumulated_actions)}.")

            # Check if flow was cleared or switched by actions in the new step
            # These commands are processed by the main loop, so we just detect them here.
            if any(a.get('type') == '_internal_command_clear_flow_state' for a in actions_from_transitioned_step) or \
               any(a.get('type') == '_internal_command_switch_flow' for a in actions_from_transitioned_step):
                logger.info(f"Flow state cleared or switch command issued during auto-transition from '{next_step_to_transition_to.name}'. Stopping further auto-transitions.")
                break 
            
            # contact_flow_state object should have been updated by _transition_to_step.
            # If it was deleted (e.g. by _internal_command_clear_flow_state not yet processed but state removed in DB),
            # we need to ensure we don't try to use a stale object.
            refreshed_state = ContactFlowState.objects.filter(pk=contact_flow_state.pk).first()
            if not refreshed_state:
                logger.info(f"ContactFlowState (pk={contact_flow_state.pk}) was cleared from DB during auto-transition. Stopping.")
                break
            contact_flow_state = refreshed_state # Ensure we use the latest state for the next iteration

            transitions_count += 1
        else:
            logger.debug(f"No automatic transition condition met from step '{current_step.name}'. Stopping automatic transitions.")
            break 
    
    if transitions_count >= max_auto_transitions:
        logger.warning(f"Reached max_auto_transitions ({max_auto_transitions}) for contact {contact.whatsapp_id}. Last step attempted: '{contact_flow_state.current_step.name}'.")

    logger.info(f"Finished automatic transition processing for contact {contact.whatsapp_id}. Total {transitions_count} auto-transitions made. {len(accumulated_actions)} actions generated.")
    return accumulated_actions

def _transition_to_step(
    contact_flow_state: ContactFlowState, 
    next_step: FlowStep, 
    context_of_leaving_step: dict, # Context from the step we are transitioning FROM
    contact: Contact, 
    message_data: dict # Original message_data that might have triggered the first transition in a chain
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]: # Returns actions from new step, and context after new step's execution

    previous_step = contact_flow_state.current_step # For logging
    logger.info(
        f"Transitioning contact {contact.whatsapp_id} from '{previous_step.name}' (ID: {previous_step.id}) "
        f"to '{next_step.name}' (ID: {next_step.id}) in flow '{contact_flow_state.current_flow.name}'."
    )

    # Prepare context for the next step: Start with the context of the step we are leaving.
    context_for_next_step = context_of_leaving_step.copy()

    # Clear question-specific flags from the context if the step we are leaving was a question
    if previous_step.step_type == 'question':
        removed_q_key = context_for_next_step.pop('_question_awaiting_reply_for', None)
        removed_f_key = context_for_next_step.pop('_fallback_count', None)
        if removed_q_key or removed_f_key:
             logger.debug(f"Cleared question expectation/fallback count from context after leaving question step '{previous_step.name}'.")
    
    # Execute actions of the NEW step. This function returns the actions and the context *after* this new step's execution.
    actions_from_new_step, context_after_new_step_execution = _execute_step_actions(
        next_step, contact, context_for_next_step # Pass the prepared context for the new step
    )
    
    # Update the contact's flow state in the database to reflect the new current step and its resulting context.
    # This is critical. The contact_flow_state object passed in is mutated here.
    # However, if _execute_step_actions resulted in a _internal_command_clear_flow_state or _internal_command_switch_flow,
    # the state might already be deleted or replaced.
    
    # Re-fetch the state to ensure we're operating on the correct, current record,
    # especially if the flow was switched or cleared and a new state was made.
    current_db_state_for_contact = ContactFlowState.objects.filter(contact=contact).first()

    if current_db_state_for_contact:
        # Check if the state we are working with is still the primary state for the contact
        if current_db_state_for_contact.pk == contact_flow_state.pk:
            logger.debug(f"Updating original ContactFlowState (pk={contact_flow_state.pk}) for contact {contact.whatsapp_id}.")
            contact_flow_state.current_step = next_step
            contact_flow_state.flow_context_data = context_after_new_step_execution
            contact_flow_state.last_updated_at = timezone.now()
            contact_flow_state.save(update_fields=['current_step', 'flow_context_data', 'last_updated_at'])
            logger.info(f"Contact {contact.whatsapp_id} successfully transitioned to step '{next_step.name}'. Context updated.")
        else:
            # This means _execute_step_actions (e.g. via a switch_flow action) resulted in a new ContactFlowState record for this contact.
            # The `contact_flow_state` object passed into this function is now stale. The `current_db_state_for_contact` IS the new state.
            # The new state's current_step and context were set when it was created by _trigger_new_flow (called by switch_flow action processor).
            logger.info(f"Contact {contact.whatsapp_id} switched to a new flow. Current state is now pk={current_db_state_for_contact.pk}, step '{current_db_state_for_contact.current_step.name}'. The old state (pk={contact_flow_state.pk}) is no longer primary.")
            # Update the caller's reference to the new state object
            contact_flow_state.id = current_db_state_for_contact.id # Point to new object by effectively replacing it
            contact_flow_state.current_flow = current_db_state_for_contact.current_flow
            contact_flow_state.current_step = current_db_state_for_contact.current_step
            contact_flow_state.flow_context_data = current_db_state_for_contact.flow_context_data
            contact_flow_state.started_at = current_db_state_for_contact.started_at
            contact_flow_state.last_updated_at = current_db_state_for_contact.last_updated_at

    else: # No ContactFlowState for this contact means it was cleared.
        logger.info(f"ContactFlowState for contact {contact.whatsapp_id} was cleared during or after execution of step '{next_step.name}'. No state to update.")

    return actions_from_new_step, context_after_new_step_execution


def _update_contact_data(contact: Contact, field_path: str, value_to_set: Any):
    if not field_path:
        logger.warning(f"_update_contact_data: Empty field_path for contact {contact.whatsapp_id}.")
        return
    
    logger.debug(f"Attempting to update Contact {contact.whatsapp_id} field/path '{field_path}' to value '{str(value_to_set)[:100]}'.")
    parts = field_path.split('.')
    
    if len(parts) == 1:
        field_name = parts[0]
        # Prevent updating protected fields
        if field_name.lower() in ['id', 'pk', 'whatsapp_id', 'company', 'company_id', 'created_at', 'updated_at', 'customer_profile']:
            logger.warning(f"Attempt to update protected or relational Contact field '{field_name}' denied for contact {contact.whatsapp_id}.")
            return
        if hasattr(contact, field_name):
            try:
                # TODO: Add type conversion or validation based on model field type if necessary
                setattr(contact, field_name, value_to_set)
                contact.save(update_fields=[field_name])
                logger.info(f"Updated Contact {contact.whatsapp_id} field '{field_name}' to '{str(value_to_set)[:100]}'.")
            except Exception as e:
                logger.error(f"Error setting Contact field '{field_name}' for {contact.whatsapp_id}: {e}", exc_info=True)
        else:
            logger.warning(f"Contact field '{field_name}' not found on Contact model for contact {contact.whatsapp_id}.")
    elif parts[0] == 'custom_fields':
        if not hasattr(contact, 'custom_fields') or contact.custom_fields is None: # Ensure it's initialized
            contact.custom_fields = {}
        elif not isinstance(contact.custom_fields, dict):
            logger.error(f"Contact {contact.whatsapp_id} custom_fields is not a dict ({type(contact.custom_fields)}). Cannot update path '{field_path}'. Re-initializing.")
            contact.custom_fields = {} # Attempt to recover by re-initializing

        current_level = contact.custom_fields
        # Traverse/create path up to the second to last part
        for i, key in enumerate(parts[1:-1]):
            if not isinstance(current_level, dict): # Should not happen if above initialization works
                 logger.error(f"Path error in Contact.custom_fields for {contact.whatsapp_id}: '{key}' is not traversable (parent not a dict) for path '{field_path}'. Current part of path: {parts[1:i+1]}")
                 return
            current_level = current_level.setdefault(key, {}) # Ensure intermediate dicts exist
            if not isinstance(current_level, dict): # If setdefault somehow didn't make/return a dict
                 logger.error(f"Path error in Contact.custom_fields for {contact.whatsapp_id}: Could not ensure dict at '{key}' for path '{field_path}'.")
                 return
        
        final_key = parts[-1]
        if len(parts) > 1 : # e.g. custom_fields.some_key
            if isinstance(current_level, dict): # current_level should be the dict holding the final_key
                current_level[final_key] = value_to_set
                contact.save(update_fields=['custom_fields'])
                logger.info(f"Updated Contact {contact.whatsapp_id} custom_fields path '{'.'.join(parts[1:])}' to '{str(value_to_set)[:100]}'.")
            else: # Should be rare if logic above is correct
                logger.error(f"Error updating Contact {contact.whatsapp_id} custom_fields: Parent for final key '{final_key}' is not a dict for path '{field_path}'.")
        # This case (parts[0] == 'custom_fields' and len(parts)==1) means replacing the whole custom_fields dict.
        # elif len(parts) == 1 and parts[0] == 'custom_fields':
        # This should ideally be handled by the len(parts)==1 block and a specific check for 'custom_fields' there,
        # but that block protects 'custom_fields'. So direct assignment is needed if intended.
        # For safety, a specific action type might be better to replace the whole custom_fields.
        # For now, assuming paths like 'custom_fields.key'
        else: # Path was just "custom_fields", which is not typical for setting a nested value
            logger.warning(f"Ambiguous path '{field_path}' for updating Contact.custom_fields. Expecting 'custom_fields.some_key...'.")
            if isinstance(value_to_set, dict):
                 contact.custom_fields = value_to_set
                 contact.save(update_fields=['custom_fields'])
                 logger.info(f"Replaced entire Contact {contact.whatsapp_id} custom_fields with: {str(value_to_set)[:200]}")
            else:
                 logger.warning(f"Cannot replace Contact.custom_fields for {contact.whatsapp_id} with a non-dictionary value for path '{field_path}'. Value type: {type(value_to_set)}")

    else:
        logger.warning(f"Unsupported field path structure '{field_path}' for updating Contact model for contact {contact.whatsapp_id}.")


def _update_customer_profile_data(contact: Contact, fields_to_update_config: Dict[str, Any], flow_context: dict):
    if not fields_to_update_config or not isinstance(fields_to_update_config, dict):
        logger.warning(f"_update_customer_profile_data called for contact {contact.whatsapp_id} with invalid fields_to_update_config: {fields_to_update_config}")
        return

    logger.debug(f"Attempting to update CustomerProfile for contact {contact.whatsapp_id} with fields: {fields_to_update_config}")
    profile, created = CustomerProfile.objects.get_or_create(contact=contact, company=contact.company) # Ensure company match
    if created:
        logger.info(f"Created CustomerProfile (ID: {profile.id}) for contact {contact.whatsapp_id} (Company: {contact.company.name}).")
    
    changed_fields = []
    for field_path, value_template in fields_to_update_config.items():
        resolved_value = _resolve_value(value_template, flow_context, contact)
        logger.debug(f"For CustomerProfile of {contact.whatsapp_id}, attempting to set path '{field_path}' to resolved value '{str(resolved_value)[:100]}'.")
        parts = field_path.split('.')
        try:
            if len(parts) == 1:
                field_name = parts[0]
                # Prevent updating protected/relational fields directly this way
                protected_fields = ['id', 'pk', 'contact', 'contact_id', 'company', 'company_id', 'created_at', 'updated_at', 'last_updated_from_conversation']
                if hasattr(profile, field_name) and field_name.lower() not in protected_fields:
                    setattr(profile, field_name, resolved_value)
                    if field_name not in changed_fields:
                        changed_fields.append(field_name)
                else:
                    logger.warning(f"CustomerProfile field '{field_name}' not found on model or is protected for contact {contact.whatsapp_id}.")
            # Handle JSONFields like 'preferences' or 'custom_attributes'
            elif parts[0] in ['preferences', 'custom_attributes'] and len(parts) > 1:
                json_field_name = parts[0]
                json_data = getattr(profile, json_field_name)
                if json_data is None: # Initialize if None
                    json_data = {}
                elif not isinstance(json_data, dict):
                    logger.error(f"CustomerProfile.{json_field_name} for contact {contact.id} is not a dict ({type(json_data)}). Cannot update path '{field_path}'. Re-initializing.")
                    json_data = {} # Attempt to recover
                
                current_level = json_data
                for i, key in enumerate(parts[1:-1]): # Traverse/create path
                    if not isinstance(current_level, dict): # Parent not a dict, error
                        logger.error(f"Path error in CustomerProfile.{json_field_name} for contact {contact.id} at '{key}'. Expected dict, found {type(current_level)}. Full path: {field_path}")
                        current_level = None; break # Stop processing this field_path
                    current_level = current_level.setdefault(key, {})
                    if not isinstance(current_level, dict): # setdefault failed to ensure dict
                         logger.error(f"Path error in CustomerProfile.{json_field_name} for contact {contact.id}: could not ensure dict at '{key}' for path '{field_path}'.")
                         current_level = None; break

                if current_level is not None: # If path traversal was successful
                    final_key = parts[-1]
                    current_level[final_key] = resolved_value
                    setattr(profile, json_field_name, json_data) # Assign back the modified dict
                    if json_field_name not in changed_fields:
                        changed_fields.append(json_field_name)
            else:
                logger.warning(f"Unsupported field path structure for CustomerProfile: '{field_path}' for contact {contact.whatsapp_id}.")
        except Exception as e:
            logger.error(f"Error updating CustomerProfile field '{field_path}' for contact {contact.id}: {e}", exc_info=True)
            
    if changed_fields:
        profile.last_updated_from_conversation = timezone.now()
        if 'last_updated_from_conversation' not in changed_fields:
            changed_fields.append('last_updated_from_conversation')
        
        try:
            profile.save(update_fields=changed_fields)
            logger.info(f"CustomerProfile for {contact.whatsapp_id} (ID: {profile.id}) updated. Changed fields: {changed_fields}.")
        except Exception as e_save:
            logger.error(f"Error saving CustomerProfile for {contact.whatsapp_id} (ID: {profile.id}): {e_save}", exc_info=True)
    elif created: # If no fields changed but profile was just created, save it with timestamp
        profile.last_updated_from_conversation = timezone.now()
        profile.save(update_fields=['last_updated_from_conversation'])
        logger.debug(f"Saved newly created CustomerProfile for {contact.whatsapp_id} with initial timestamp.")


@transaction.atomic # Ensure atomicity for flow processing
def process_message_for_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    """
    Main entry point to process an incoming message for a contact against flows.
    Returns a list of actions to be performed (e.g., send messages to meta_integration).
    """
    actions_to_perform = []
    logger.info(f"Processing message for flow. Contact: {contact.whatsapp_id}, Message Type: {message_data.get('type')}, Message ID: {incoming_message_obj.whatsapp_message_id if incoming_message_obj else 'N/A'}.")

    try:
        # Use select_for_update to lock the ContactFlowState row for this contact during processing
        # This helps prevent race conditions if multiple messages arrive nearly simultaneously for the same contact.
        contact_flow_state = ContactFlowState.objects.select_for_update().select_related(
            'current_flow', 'current_step'
        ).get(contact=contact)
        
        logger.info(
            f"Contact {contact.whatsapp_id} is currently in flow '{contact_flow_state.current_flow.name}' (ID: {contact_flow_state.current_flow.id}), "
            f"step '{contact_flow_state.current_step.name}' (ID: {contact_flow_state.current_step.id})."
        )
        # This function will evaluate transitions based on the new message and update state
        actions_to_perform = _handle_active_flow_step(
            contact_flow_state, contact, message_data, incoming_message_obj
        )
    except ContactFlowState.DoesNotExist:
        logger.info(f"No active flow state for contact {contact.whatsapp_id}. Attempting to trigger a new flow.")
        actions_to_perform = _trigger_new_flow(contact, message_data, incoming_message_obj)
    except Exception as e:
        logger.error(f"CRITICAL error in process_message_for_flow for contact {contact.whatsapp_id} (Message ID: {incoming_message_obj.whatsapp_message_id if incoming_message_obj else 'N/A'}): {e}", exc_info=True)
        _clear_contact_flow_state(contact, error=True, reason=f"Critical error in process_message_for_flow: {e}")
        # Send a generic error message to the user
        actions_to_perform = [{
            'type': 'send_whatsapp_message',
            'recipient_wa_id': contact.whatsapp_id,
            'message_type': 'text',
            'data': {'body': 'I encountered an unexpected issue. Please try again in a moment. If the problem persists, contact support.'}
        }]
        # Early exit if critical error
        return actions_to_perform 
        
    # --- Process automatic transitions after initial handling based on the message ---
    # Re-fetch the state as _handle_active_flow_step or _trigger_new_flow might have changed it
    current_contact_flow_state_after_initial_handling = ContactFlowState.objects.filter(contact=contact).first()
    
    if current_contact_flow_state_after_initial_handling:
        is_waiting_for_reply_from_current_step = False
        current_step = current_contact_flow_state_after_initial_handling.current_step
        current_context = current_contact_flow_state_after_initial_handling.flow_context_data if isinstance(current_contact_flow_state_after_initial_handling.flow_context_data, dict) else {}

        if current_step.step_type == 'question':
            question_expectation = current_context.get('_question_awaiting_reply_for')
            if isinstance(question_expectation, dict) and question_expectation.get('original_question_step_id') == current_step.id:
                is_waiting_for_reply_from_current_step = True
                logger.debug(f"Current step '{current_step.name}' is a question still awaiting reply. No auto-transitions will be processed now.")
        
        # Only try auto-transitions if:
        # 1. Not currently waiting for a specific reply from the current step.
        # 2. The flow wasn't cleared or switched by the initial set of actions generated from the user's message.
        if not is_waiting_for_reply_from_current_step and \
           not any(a.get('type') == '_internal_command_clear_flow_state' for a in actions_to_perform) and \
           not any(a.get('type') == '_internal_command_switch_flow' for a in actions_to_perform):
            
            logger.info(f"Checking for automatic transitions for contact {contact.whatsapp_id} from step '{current_step.name}'.")
            additional_auto_actions = _process_automatic_transitions(current_contact_flow_state_after_initial_handling, contact)
            if additional_auto_actions:
                logger.info(f"Appending {len(additional_auto_actions)} actions from automatic transitions for contact {contact.whatsapp_id}.")
                actions_to_perform.extend(additional_auto_actions)
        else:
            logger.debug(f"Skipping automatic transitions for contact {contact.whatsapp_id}. Waiting for reply: {is_waiting_for_reply_from_current_step}, Flow Clear/Switch commanded: {any(a.get('type') in ['_internal_command_clear_flow_state', '_internal_command_switch_flow'] for a in actions_to_perform)}")
    else:
        logger.info(f"No active flow state for contact {contact.whatsapp_id} after initial processing. No automatic transitions to run.")
            
    # Final processing of actions, especially internal commands like switch_flow
    final_actions_for_meta_view = []
    # A flow switch might generate its own send_whatsapp_message actions, so collect them.
    # The switch itself needs to be handled carefully to avoid double processing or incorrect state.

    # Process actions in order. If a switch_flow occurs, it might generate new actions.
    # The list `actions_to_perform` could be modified if _internal_command_switch_flow calls _trigger_new_flow which returns actions.
    # This loop structure might need refinement if switch_flow actions are added *during* iteration.
    # For now, let's assume switch_flow is a terminal command for the current list of actions,
    # and its generated actions are what's returned.

    processed_switch_command = False
    for action in actions_to_perform:
        action_type = action.get('type')
        logger.debug(f"Final processing of action: {action_type} for contact {contact.whatsapp_id}")

        if action_type == '_internal_command_clear_flow_state':
            # State is already cleared by _clear_contact_flow_state called in end_flow or handover.
            # This action is more of a marker.
            logger.info(f"Internal command: Flow state already handled for clear command. Reason: {action.get('reason', 'N/A')}")
            # No action to pass to meta_view for this.
        
        elif action_type == '_internal_command_switch_flow':
            if processed_switch_command:
                logger.warning("Multiple switch flow commands detected in action list. Only processing the first one.")
                continue

            logger.info(f"Processing internal command to switch flow for contact {contact.whatsapp_id} to '{action.get('target_flow_name')}'.")
            
            # Ensure any existing state is gone before triggering new one to avoid unique constraint issues
            # _clear_contact_flow_state is called inside _trigger_new_flow as well if no state exists,
            # but explicit call before can be safer if a stale state from a weird edge case existed.
            _clear_contact_flow_state(contact, reason=f"Switching to flow {action.get('target_flow_name')}")

            new_flow_name = action.get('target_flow_name')
            initial_context_for_new_flow = action.get('initial_context', {}) 
            new_flow_trigger_msg_body = action.get('new_flow_trigger_message_body')
            
            # Prepare a synthetic message_data to trigger the new flow as if by keyword
            # This allows the new flow's trigger logic (if any beyond name) and entry point to run naturally.
            synthetic_message_data = {
                'type': 'text', 
                'text': {'body': new_flow_trigger_msg_body or f"__internal_trigger_{new_flow_name}"}
            }
            
            # incoming_message_obj is the original message that led to this whole sequence.
            # Pass it along if relevant, or None.
            switched_flow_actions = _trigger_new_flow(contact, synthetic_message_data, incoming_message_obj) 
            
            # Apply initial_context to the newly created state by _trigger_new_flow
            newly_created_state_after_switch = ContactFlowState.objects.filter(contact=contact).first()
            if newly_created_state_after_switch and initial_context_for_new_flow and isinstance(initial_context_for_new_flow, dict):
                logger.debug(f"Applying initial context to newly switched flow state (pk={newly_created_state_after_switch.pk}). Current context: {newly_created_state_after_switch.flow_context_data}, Initial to apply: {initial_context_for_new_flow}")
                # Ensure flow_context_data is a dict before updating
                if not isinstance(newly_created_state_after_switch.flow_context_data, dict):
                    newly_created_state_after_switch.flow_context_data = {} 
                newly_created_state_after_switch.flow_context_data.update(initial_context_for_new_flow)
                newly_created_state_after_switch.save(update_fields=['flow_context_data', 'last_updated_at'])
                logger.info(f"Applied initial context to new flow '{new_flow_name}' state for {contact.whatsapp_id}: {initial_context_for_new_flow}")
            
            # Replace all current actions with those from the new flow's entry
            final_actions_for_meta_view = switched_flow_actions 
            processed_switch_command = True # Mark that switch has been handled
            logger.info(f"Flow switch completed. New actions from switched flow: {len(final_actions_for_meta_view)}")
            break # Stop processing old list of actions, use new ones from switched flow

        elif action_type == 'send_whatsapp_message':
            final_actions_for_meta_view.append(action)
        else:
            logger.warning(f"Unhandled action type '{action_type}' encountered during final action processing for contact {contact.whatsapp_id}. Action: {action}")
            
    logger.info(f"Finished processing message for contact {contact.whatsapp_id}. Total {len(final_actions_for_meta_view)} actions to be sent to meta_integration.")
    logger.debug(f"Final actions for {contact.whatsapp_id}: {json.dumps(final_actions_for_meta_view, indent=2)}")
    return final_actions_for_meta_view