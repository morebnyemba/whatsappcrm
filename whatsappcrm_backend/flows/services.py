# whatsappcrm_backend/flows/services.py

from enum import Enum
import logging
import json
import re
from typing import List, Dict, Any, Optional, Union, Literal, Tuple
from django.db import models
from django.utils import timezone
from django.db import transaction
from django.template import Template, Context
from django.template.exceptions import TemplateSyntaxError, TemplateDoesNotExist

from pydantic import BaseModel, ValidationError, field_validator, root_validator, Field
from decimal import Decimal # Ensure Decimal is imported for type hints if used by Pydantic validators

# IMPORTANT: Retaining the original import methods as requested.
# If these cause "attempted relative import beyond top-level package" errors,
# your environment's PYTHONPATH or Django app structure configuration might need adjustment.
from conversations.models import Contact # Direct import as originally specified
from conversations.models import Message # Direct import as originally specified
from football_data_app.models import FootballFixture # Direct import as originally specified (renamed from Match)
from customer_data.models import CustomerProfile # Direct import as originally specified

# Flow related models (relative import as originally specified)
from .models import Flow, FlowStep, FlowTransition, ContactFlowState

# Conditional imports as per your original structure
try:
    from media_manager.models import MediaAsset
    MEDIA_ASSET_ENABLED = True
except ImportError:
    MEDIA_ASSET_ENABLED = False

logger = logging.getLogger(__name__)

if not MEDIA_ASSET_ENABLED:
    logger.warning("MediaAsset model not found or could not be imported. MediaAsset functionality (e.g., 'asset_pk') will be disabled in flows.")

# Conditional imports for football_data_app and customer_data actions/utils
# Retaining the original import method that uses direct package names
FOOTBALL_APP_ENABLED = False
try:
    # These imports assume 'football_data_app' is directly on Python path or known to Django
    from football_data_app.flow_actions import handle_football_betting_action # Assuming renamed to handle_football_betting_action
    from football_data_app.utils import get_formatted_football_data # Assuming this is in utils.py
    FOOTBALL_APP_ENABLED = True
except ImportError as e:
    logger.warning(f"football_data_app.flow_actions or utils could not be imported. Football-related actions will not work. Error: {e}")

CUSTOMER_DATA_UTILS_ENABLED = False
try:
    # This import assumes 'customer_data' is directly on Python path or known to Django
    import customer_data.utils as customer_data_utils
    CUSTOMER_DATA_UTILS_ENABLED = True
except ImportError as e:
    logger.warning(f"customer_data.utils could not be imported. Account/Wallet actions will not work. Error: {e}")


# --- Pydantic Models ---
class BasePydanticConfig(BaseModel):
    class Config:
        extra = 'allow' # Allow extra fields for flexibility in config JSONs
        # Pydantic V2 recommends `model_config = ConfigDict(extra='allow')`

# Your existing message content models
class TextMessageContent(BasePydanticConfig):
    body: str = Field(..., min_length=1, max_length=4096)
    preview_url: bool = False

class MediaMessageContent(BasePydanticConfig):
    asset_pk: Optional[int] = None
    id: Optional[str] = None # WhatsApp Media ID
    link: Optional[str] = None
    caption: Optional[str] = Field(default=None, max_length=1024)
    filename: Optional[str] = None

    @root_validator(pre=True, skip_on_failure=True) # Use pre=True for validation on raw input
    def check_media_source(cls, values):
        asset_pk, media_id, link = values.get('asset_pk'), values.get('id'), values.get('link')
        if not MEDIA_ASSET_ENABLED and asset_pk:
            raise ValueError("'asset_pk' provided but MediaAsset system is not enabled/imported.")
        if not (asset_pk or media_id or link):
            raise ValueError("One of 'asset_pk', 'id' (WhatsApp Media ID), or 'link' must be provided for media.")
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
    # Add other media header fields if your API supports them (e.g., video: MediaSourceConfig)

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
    button: str = Field(..., min_length=1, max_length=20)
    sections: List[InteractiveListSection] = Field(..., min_items=1)

class InteractiveMessagePayload(BasePydanticConfig):
    type: Literal["button", "list", "product", "product_list"]
    header: Optional[InteractiveHeader] = None
    body: InteractiveBody
    footer: Optional[InteractiveFooter] = None
    action: Union[InteractiveButtonAction, InteractiveListAction] # This uses Union

class TemplateLanguage(BasePydanticConfig):
    code: str

class TemplateParameter(BasePydanticConfig):
    type: Literal["text", "currency", "date_time", "image", "document", "video", "payload"]
    text: Optional[str] = None
    currency: Optional[Dict[str, Any]] = None # This dict usually contains { "amount": <value>, "code": "USD" }
    date_time: Optional[Dict[str, Any]] = None # This dict usually contains { "timestamp": <value> }
    image: Optional[Dict[str, Any]] = None # This dict usually contains { "link": "...", "id": "..." }
    document: Optional[Dict[str, Any]] = None # This dict usually contains { "link": "...", "id": "...", "filename": "..." }
    video: Optional[Dict[str, Any]] = None # This dict usually contains { "link": "...", "id": "..." }
    payload: Optional[str] = None # For quick reply buttons

class TemplateComponent(BasePydanticConfig):
    type: Literal["header", "body", "button"]
    sub_type: Optional[Literal['url', 'quick_reply', 'call_button', 'catalog_button', 'mpm_button']] = None # For buttons
    parameters: Optional[List[TemplateParameter]] = None
    index: Optional[int] = None # For button components to specify which button

class TemplateMessageContent(BasePydanticConfig):
    name: str
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
    phone: Optional[str] = None
    type: Optional[Literal['CELL', 'MAIN', 'IPHONE', 'HOME', 'WORK']] = None
    wa_id: Optional[str] = None

class ContactOrg(BasePydanticConfig):
    company: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None

class ContactUrl(BasePydanticConfig):
    url: Optional[str] = None
    type: Optional[Literal['HOME', 'WORK']] = None

class ContactObject(BasePydanticConfig):
    addresses: Optional[List[ContactAddress]] = Field(default_factory=list)
    birthday: Optional[str] = None
    emails: Optional[List[ContactEmail]] = Field(default_factory=list)
    name: ContactName
    org: Optional[ContactOrg] = None
    phones: Optional[List[ContactPhone]] = Field(default_factory=list)
    urls: Optional[List[ContactUrl]] = Field(default_factory=list)

class LocationMessageContent(BasePydanticConfig):
    longitude: float
    latitude: float
    name: Optional[str] = None
    address: Optional[str] = None

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
    contacts: Optional[List[ContactObject]] = None
    location: Optional[LocationMessageContent] = None

    @root_validator(pre=False, skip_on_failure=True)
    def check_payload_exists_for_type(cls, values):
        msg_type = values.get('message_type')
        payload_specific_to_type = values.get(msg_type)

        if msg_type and payload_specific_to_type is None:
            raise ValueError(f"Payload for message_type '{msg_type}' (expected field '{msg_type}') is missing or null.")

        defined_payload_fields = {"text", "image", "document", "audio", "video", "sticker", "interactive", "template", "contacts", "location"}
        for field_name in defined_payload_fields:
            if field_name != msg_type and values.get(field_name) is not None:
                raise ValueError(f"Field '{field_name}' should not be present (or must be null) when message_type is '{msg_type}'.")

        if msg_type == 'interactive':
            interactive_payload = values.get('interactive')
            if not interactive_payload or not getattr(interactive_payload, 'type', None):
                raise ValueError("For 'interactive' messages, the 'interactive' payload object must exist and itself specify an interactive 'type' (e.g., 'button', 'list').")
            
            interactive_internal_type = interactive_payload.type
            interactive_action = interactive_payload.action
            
            if interactive_internal_type == "button" and not isinstance(interactive_action, InteractiveButtonAction):
                raise ValueError("For interactive message type 'button', the 'action' field must be a valid InteractiveButtonAction.")
            if interactive_internal_type == "list" and not isinstance(interactive_action, InteractiveListAction):
                raise ValueError("For interactive message type 'list', the 'action' field must be a valid InteractiveListAction.")
        return values

class ReplyConfig(BasePydanticConfig):
    save_to_variable: str = Field(..., min_length=1)
    expected_type: Literal["text", "email", "number", "interactive_id", "any"] = "any"
    validation_regex: Optional[str] = None

class StepConfigQuestion(BasePydanticConfig):
    message_config: Dict[str, Any]
    reply_config: ReplyConfig
    # Added fallback_config for consistent handling of invalid replies in questions
    fallback_config: Optional[Dict[str, Any]] = Field(default_factory=dict)


    @field_validator('message_config')
    def validate_message_config_structure(cls, v_dict):
        try:
            StepConfigSendMessage.model_validate(v_dict)
            return v_dict
        except ValidationError as e:
            logger.error(f"Invalid message_config for question step: {e.errors()}", exc_info=False)
            raise ValueError(f"message_config for question is invalid: {e.errors()}")

# --- NEW/UPDATED ACTION CONFIG MODELS (using Literal for action_type - FIX FOR PYDANTIC ERROR) ---

# Define individual action configurations with Literal types for the discriminator
class ActionType(str, Enum): # This Enum is fine for internal use and defining Literal values
    SET_CONTEXT_VARIABLE = "set_context_variable"
    UPDATE_CONTACT_FIELD = "update_contact_field"
    UPDATE_CUSTOMER_PROFILE = "update_customer_profile"
    SWITCH_FLOW = "switch_flow"
    FETCH_FOOTBALL_DATA = "fetch_football_data"
    CREATE_ACCOUNT = "create_account"
    PERFORM_DEPOSIT = "perform_deposit"
    PERFORM_WITHDRAWAL = "perform_withdrawal"
    HANDLE_BETTING_ACTION = "handle_betting_action"

class SetContextVariableConfig(BasePydanticConfig):
    action_type: Literal["set_context_variable"] = "set_context_variable"
    variable_name: str
    value_template: Any

class UpdateContactFieldConfig(BasePydanticConfig):
    action_type: Literal["update_contact_field"] = "update_contact_field"
    field_path: str
    value_template: Any

class UpdateCustomerProfileConfig(BasePydanticConfig):
    action_type: Literal["update_customer_profile"] = "update_customer_profile"
    fields_to_update: Dict[str, Any] # Dictionary where keys are field names and values are templates

class SwitchFlowConfig(BasePydanticConfig):
    action_type: Literal["switch_flow"] = "switch_flow"
    target_flow_name: str
    initial_context_template: Optional[Dict[str, Any]] = Field(default_factory=dict)
    message_to_evaluate_for_new_flow: Optional[str] = None # Message body to simulate triggering the new flow

class FetchFootballDataConfig(BasePydanticConfig):
    action_type: Literal["fetch_football_data"] = "fetch_football_data"
    data_type: Literal["scheduled_fixtures", "finished_results"]
    league_code_variable: Optional[str] = None # Path to context var holding league code
    output_variable_name: str # Name of context var to save formatted output
    days_past_for_results: Optional[int] = Field(default=2)
    days_ahead_for_fixtures: Optional[int] = Field(default=7)

class CreateAccountConfig(BasePydanticConfig):
    action_type: Literal["create_account"] = "create_account"
    email_template: Optional[str] = None # Template for email (e.g., {{ flow_context.user_email }})
    first_name_template: Optional[str] = None
    last_name_template: Optional[str] = None
    acquisition_source_template: Optional[str] = "WhatsApp Flow"
    initial_balance: float = 0.0

class PerformDepositConfig(BasePydanticConfig):
    action_type: Literal["perform_deposit"] = "perform_deposit"
    amount_template: Union[float, str] # Can be a direct float or a template string
    payment_method: Literal["paynow_mobile", "stripe", "manual"] = "manual" # New field
    phone_number_template: Optional[str] = None # New field for mobile payments
    paynow_method_type_template: Optional[str] = None # e.g., 'ecocash', 'onemoney'
    description_template: Optional[str] = "Deposit via bot flow"

class PerformWithdrawalConfig(BasePydanticConfig):
    action_type: Literal["perform_withdrawal"] = "perform_withdrawal"
    amount_template: Union[float, str]
    payment_method: Optional[str] = None # Allow direct value
    payment_method_template: Optional[str] = None # Make template optional
    phone_number_template: str # The phone number for withdrawal
    description_template: Optional[str] = "Withdrawal via bot flow"

    @root_validator(pre=False, skip_on_failure=True)
    def check_payment_method_source(cls, values):
        # Ensure that either the direct value or the template is provided.
        if not values.get('payment_method') and not values.get('payment_method_template'):
            raise ValueError("Either 'payment_method' or 'payment_method_template' must be provided for 'perform_withdrawal' action.")
        return values

class HandleBettingActionConfig(BasePydanticConfig):
    action_type: Literal["handle_betting_action"] = "handle_betting_action"
    betting_action: str # e.g., 'view_matches', 'create_new_ticket', 'add_bet_to_ticket', 'place_ticket', 'view_my_tickets', 'check_wallet_balance'
    stake_template: Optional[Union[float, str]] = None # Can be a direct float or template (for place_ticket)
    market_outcome_id_template: Optional[str] = None # Template for outcome ID (for add_bet_to_ticket)
    raw_bet_string_template: Optional[str] = None # Template for raw betting string (for place_ticket)
    # Additional parameters might be needed here if specific betting actions require them, e.g.:
    league_code_template: Optional[str] = None # Template for league code (for view_matches/view_results via betting action)
    days_past: Optional[int] = Field(default=2) # For view_results
    days_ahead: Optional[int] = Field(default=7) # For view_matches


# This is the Union type that `StepConfigAction` will use in its `actions_to_run` list
class ActionItem(BaseModel):
    # This acts as a union type for all action configurations
    # The `discriminator` argument is crucial for Pydantic to determine which sub-model to use
    # based on the value of the 'action_type' field.
    root: Union[
        SetContextVariableConfig,
        UpdateContactFieldConfig,
        UpdateCustomerProfileConfig,
        SwitchFlowConfig,
        FetchFootballDataConfig,
        CreateAccountConfig,
        PerformDepositConfig,
        PerformWithdrawalConfig,
        HandleBettingActionConfig
    ] = Field(discriminator='action_type')

    # Allows direct attribute access to the underlying action configuration object
    # This makes it easier to access fields like `action_item_conf.variable_name`
    # instead of `action_item_conf.root.variable_name`
    def __getattr__(self, name: str) -> Any:
        # Check if the attribute exists on the root model, otherwise raise AttributeError
        if hasattr(self.root, name):
            return getattr(self.root, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    # Custom initializer to correctly parse data into the 'root' field
    # Pydantic v2 often prefers `model_validate(data)` over direct `__init__` for root fields
    # However, this pattern is common in Pydantic v1 for discriminator setup.
    def __init__(self, **data: Any):
        super().__init__(root=data) # Initialize the root with the incoming data


class StepConfigAction(BasePydanticConfig):
    actions_to_run: List[ActionItem] = Field(default_factory=list) # Changed min_items to 0 (or removed)

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

# Rebuild models if they contain forward references (like InteractiveMessagePayload referencing itself)
InteractiveMessagePayload.model_rebuild()


# --- Helper Functions ---
# _execute_step_actions calls other helpers like _get_value_from_context_or_contact, _resolve_value etc.
# These helper functions have been updated to match the new Pydantic structure and action types.

def _get_value_from_context_or_contact(variable_path: str, flow_context: dict, contact: Contact) -> Any:
    """
    Safely retrieves a value from flow_context or contact/customer_profile object using dot notation.
    Handles nested dictionaries and model attributes, including callable attributes.
    """
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
            current_value = contact.customerprofile # Note: Use .customerprofile for OneToOne related_name
            path_to_traverse = parts[1:]
            logger.debug(f"Accessing customer_profile attributes for contact {contact.id}. Path to traverse: {path_to_traverse}")
        except CustomerProfile.DoesNotExist:
            logger.debug(f"CustomerProfile does not exist for contact {contact.id} when trying to access '{variable_path}'")
            return None
        except AttributeError: # If related object is None (e.g., customerprofile not yet created)
            logger.warning(f"Contact {contact.id} has no 'customerprofile' related object (or it's None) for path '{variable_path}'")
            return None
    else:
        # If the path doesn't start with a known source, assume it's a top-level flow_context variable
        current_value = flow_context
        path_to_traverse = parts
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
                    # Handle callable attributes (methods, properties)
                    try:
                        num_args = -1
                        # For methods on instances (including properties)
                        if hasattr(attr_or_method, '__func__'):
                            # inspect.signature might be more robust, but this checks for 'self' arg
                            num_args = attr_or_method.__func__.__code__.co_argcount - (1 if not isinstance(attr_or_method.__self__, type) else 0) 
                            if num_args == 0:
                                current_value = attr_or_method()
                                logger.debug(f"Called method '{part}' from path '{variable_path}'.")
                            else:
                                logger.debug(f"Method '{part}' requires {num_args} args, returning method itself for path '{variable_path}'.")
                                current_value = attr_or_method # Return the callable if it needs args
                        # For plain functions or staticmethods (no 'self' arg)
                        elif hasattr(attr_or_method, '__code__'):
                            num_args = attr_or_method.__code__.co_argcount
                            if num_args == 0:
                                current_value = attr_or_method()
                                logger.debug(f"Called function/static method '{part}' from path '{variable_path}'.")
                            else:
                                logger.debug(f"Function '{part}' requires {num_args} args, returning function itself for path '{variable_path}'.")
                                current_value = attr_or_method
                        else: # Fallback for other callable types
                            logger.debug(f"Unknown callable type for '{part}', returning as is for path '{variable_path}'.")
                            current_value = attr_or_method
                    except TypeError as te_callable:
                        logger.warning(f"TypeError calling method/function '{part}' for path '{variable_path}': {te_callable}. Returning callable as is.")
                        current_value = attr_or_method
                    except Exception as e_callable:
                        logger.warning(f"Error calling method/function '{part}' for path '{variable_path}': {e_callable}. Returning callable as is.")
                        current_value = attr_or_method
                else:
                    current_value = attr_or_method # It's a non-callable attribute
            else:
                logger.debug(f"Part '{part}' not found in current object for path '{variable_path}'. Current object type: {type(current_value)}, value: {str(current_value)[:100]}")
                return None
        except Exception as e:
            logger.warning(f"Unexpected error accessing part '{part}' of path '{variable_path}': {e}", exc_info=True)
            return None
            
    resolved_val_str = str(current_value)
    logger.debug(f"Resolved path '{variable_path}' to value: '{resolved_val_str[:100]}{'...' if len(resolved_val_str) > 100 else ''}' (Type: {type(current_value)})")

    # Ensure that 'type' objects are converted to their string representation
    # This prevents TypeError: Object of type type is not JSON serializable when saving to JSONField.
    if isinstance(current_value, type):
        return str(current_value)
    return current_value

def _resolve_value(template_value: Any, flow_context: dict, contact: Contact) -> Any:
    """
    Recursively resolves template strings within a value using _get_value_from_context_or_contact.
    Handles nested dictionaries and lists.
    """
    if isinstance(template_value, str):
        # Find all {{ variable_path }} occurrences
        variable_pattern = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
        resolved_string = template_value
        
        # Iteratively resolve templates to handle nested or chained templates (up to 10 levels)
        for i in range(10): 
            original_string_for_iteration = resolved_string
            matches = list(variable_pattern.finditer(resolved_string))
            if not matches:
                break # No more templates to resolve

            new_parts = []
            last_end = 0
            for match in matches:
                new_parts.append(resolved_string[last_end:match.start()]) # Add text before match
                var_path = match.group(1).strip() # Extract variable path
                val = _get_value_from_context_or_contact(var_path, flow_context, contact) # Resolve variable
                new_parts.append(str(val) if val is not None else '') # Add resolved value
                last_end = match.end() # Move cursor past the match
            
            new_parts.append(resolved_string[last_end:]) # Add remaining text after last match
            resolved_string = "".join(new_parts)

            # Break if no change occurred (all templates resolved or unresolved)
            if resolved_string == original_string_for_iteration:
                break
            # Also break if no more templates are found, faster than waiting for no change
            if not variable_pattern.search(resolved_string):
                break
            if i == 9: # Warn if max iterations reached
                logger.warning(f"Template string resolution reached max iterations (10) for input: '{template_value}'. Result: '{resolved_string}'")
        return resolved_string
    elif isinstance(template_value, dict):
        return {k: _resolve_value(v, flow_context, contact) for k, v in template_value.items()}
    elif isinstance(template_value, list):
        return [_resolve_value(item, flow_context, contact) for item in template_value]
    return template_value # Return non-string, non-dict, non-list values as is

def _resolve_template_components(components_config: list, flow_context: dict, contact: Contact) -> list:
    """
    Resolves template parameters within WhatsApp template message components.
    """
    if not components_config or not isinstance(components_config, list):
        logger.debug("_resolve_template_components: No components to resolve or invalid format.")
        return []
    try:
        # Deep copy the config to avoid modifying the original Pydantic object
        # Use json.loads(json.dumps()) for a simple deep copy of JSON-serializable objects
        resolved_components_list = json.loads(json.dumps(components_config))
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

                    # Resolve 'text' parameters
                    if 'text' in param and isinstance(param['text'], str):
                        original_text = param['text']
                        param['text'] = _resolve_value(param['text'], flow_context, contact)
                        if original_text != param['text']: logger.debug(f"Resolved param text from '{original_text}' to: '{param['text']}'")
                    
                    # Resolve media (image, video, document) links
                    if param_type in ['image', 'video', 'document'] and isinstance(param.get(param_type), dict):
                        media_obj = param[param_type]
                        if 'link' in media_obj and isinstance(media_obj['link'], str):
                            original_link = media_obj['link']
                            media_obj['link'] = _resolve_value(media_obj['link'], flow_context, contact)
                            if original_link != media_obj['link']: logger.debug(f"Resolved media link from '{original_link}' to: {media_obj['link']}")
                    
                    # Resolve button 'payload'
                    if component.get('type') == 'button' and param.get('type') == 'payload' and 'payload' in param and isinstance(param['payload'], str):
                        original_payload = param['payload']
                        param['payload'] = _resolve_value(param['payload'], flow_context, contact)
                        if original_payload != param['payload']: logger.debug(f"Resolved button payload from '{original_payload}' to: {param['payload']}")

                    # Resolve currency fallback value
                    if param_type == 'currency' and isinstance(param.get('currency'), dict) and 'fallback_value' in param['currency'] and isinstance(param['currency']['fallback_value'], str) :
                        original_fb_val = param['currency']['fallback_value']
                        param['currency']['fallback_value'] = _resolve_value(param['currency']['fallback_value'], flow_context, contact)
                        if original_fb_val != param['currency']['fallback_value']: logger.debug(f"Resolved currency fallback from '{original_fb_val}' to: {param['currency']['fallback_value']}")

                    # Resolve date_time fallback value
                    if param_type == 'date_time' and isinstance(param.get('date_time'), dict) and 'fallback_value' in param['date_time'] and isinstance(param['date_time']['fallback_value'], str):
                        original_fb_val = param['date_time']['fallback_value']
                        param['date_time']['fallback_value'] = _resolve_value(param['date_time']['fallback_value'], flow_context, contact)
                        if original_fb_val != param['date_time']['fallback_value']: logger.debug(f"Resolved date_time fallback from '{original_fb_val}' to: {param['date_time']['fallback_value']}")
            
        logger.debug(f"Finished resolving template components. Final data (sample): {str(resolved_components_list)[:200]}")
        return resolved_components_list
    except Exception as e:
        logger.error(f"Error during _resolve_template_components: {e}. Original Config: {components_config}", exc_info=True)
        return components_config


def _clear_contact_flow_state(contact: Contact, error: bool = False, reason: str = ""):
    """
    Clears the active flow state for a given contact.
    """
    if not contact or not contact.pk:
        logger.warning(f"Attempted to clear flow state for a contact without a PK or a None contact object. Reason: {reason}")
        return

    deleted_count, _ = ContactFlowState.objects.filter(contact=contact).delete()
    log_message = f"Cleared flow state for contact {contact.whatsapp_id} (ID: {contact.id})."
    if reason:
        log_message += f" Reason: {reason}."
    if error:
        log_message += " Due to an error."
    if deleted_count > 0:
        logger.info(log_message)
    else:
        log_suffix = reason or ("N/A" if not error else "Error, but no state found")
        logger.debug(f"No flow state to clear for contact {contact.whatsapp_id} (ID: {contact.id}). Reason: {log_suffix}.")


# Helper to update Contact model fields
def _update_contact_data(contact: Contact, field_path: str, value_to_set: Any):
    """
    Updates a field on the Contact model (or its custom_fields JSONField) dynamically.
    """
    if not field_path:
        logger.warning(f"_update_contact_data: Empty field_path for contact {contact.whatsapp_id} (ID: {contact.id}).")
        return
        
    logger.debug(f"Attempting to update Contact {contact.whatsapp_id} (ID: {contact.id}) field/path '{field_path}' to value '{str(value_to_set)[:100]}'.")
    parts = field_path.split('.')
    
    if len(parts) == 1: # Direct field on Contact model
        field_name = parts[0]
        # Protect common fields that should not be directly updated this way
        protected_fields = ['id', 'pk', 'whatsapp_id', 'company', 'company_id', 'created_at', 'updated_at', 'customerprofile', 'messages', 'current_flow', 'current_flow_state', 'needs_human_intervention', 'intervention_requested_at']
        if field_name.lower() in protected_fields:
            logger.warning(f"Attempt to update protected or relational Contact field '{field_name}' denied for contact {contact.whatsapp_id}.")
            return
        if hasattr(contact, field_name):
            try:
                setattr(contact, field_name, value_to_set)
                contact.save(update_fields=[field_name])
                logger.info(f"Updated Contact {contact.whatsapp_id} field '{field_name}' to '{str(value_to_set)[:100]}'.")
            except Exception as e:
                logger.error(f"Error setting Contact field '{field_name}' for {contact.whatsapp_id}: {e}", exc_info=True)
        else:
            logger.warning(f"Contact field '{field_name}' not found on Contact model for contact {contact.whatsapp_id}.")
    elif parts[0] == 'custom_fields': # Nested field within Contact.custom_fields (JSONField)
        if not hasattr(contact, 'custom_fields') or contact.custom_fields is None:
            contact.custom_fields = {}
        elif not isinstance(contact.custom_fields, dict):
            logger.error(f"Contact {contact.whatsapp_id} custom_fields is not a dict ({type(contact.custom_fields)}). Cannot update path '{field_path}'. Re-initializing.")
            contact.custom_fields = {}

        current_level = contact.custom_fields
        for i, key in enumerate(parts[1:-1]): # Traverse all but the last part
            if not isinstance(current_level, dict):
                logger.error(f"Path error in Contact.custom_fields for {contact.whatsapp_id}: '{key}' is not traversable (parent not a dict) for path '{field_path}'. Current part of path: {parts[1:i+1]}")
                return
            current_level = current_level.setdefault(key, {}) # Create dict if key doesn't exist
            if not isinstance(current_level, dict): # Ensure setdefault didn't overwrite with non-dict
                logger.error(f"Path error in Contact.custom_id fields for {contact.whatsapp_id}: Could not ensure dict at '{key}' for path '{field_path}'.")
                return
            
        final_key = parts[-1] # The last part is the field to set
        if len(parts) > 1 : # Ensure there's at least one key after 'custom_fields'
            if isinstance(current_level, dict):
                current_level[final_key] = value_to_set
                contact.save(update_fields=['custom_fields']) # Save the updated JSONField
                logger.info(f"Updated Contact {contact.whatsapp_id} custom_fields path '{'.'.join(parts[1:])}' to '{str(value_to_set)[:100]}'.")
            else:
                logger.error(f"Error updating Contact {contact.whatsapp_id} custom_fields: Parent for final key '{final_key}' is not a dict for path '{field_path}'.")
        else: # Case where field_path is just 'custom_fields' (no dot notation)
            logger.warning(f"Ambiguous path '{field_path}' for updating Contact.custom_fields. Expecting 'custom_fields.some_key...'.")
            if isinstance(value_to_set, dict):
                contact.custom_fields = value_to_set # Replace entire custom_fields dict
                contact.save(update_fields=['custom_fields'])
                logger.info(f"Replaced entire Contact {contact.whatsapp_id} custom_fields with: {str(value_to_set)[:200]}")
            else:
                logger.warning(f"Cannot replace Contact.custom_fields for {contact.whatsapp_id} with a non-dictionary value for path '{field_path}'. Value type: {type(value_to_set)}")
    else:
        logger.warning(f"Unsupported field path structure '{field_path}' for updating Contact model for contact {contact.whatsapp_id}.")


def _update_customer_profile_data(contact: Contact, fields_to_update_config: Dict[str, Any], flow_context: dict):
    """
    Updates fields on the CustomerProfile model. Handles special mappings (e.g., gender, date_of_birth)
    and assumes CustomerProfile has JSONFields named 'preferences' and 'custom_attributes' if used.
    """
    if not fields_to_update_config or not isinstance(fields_to_update_config, dict):
        logger.warning(f"_update_customer_profile_data called for contact {contact.whatsapp_id} (ID: {contact.id}) with invalid fields_to_update_config: {fields_to_update_config}")
        return

    logger.debug(f"Attempting to update CustomerProfile for contact {contact.whatsapp_id} (ID: {contact.id}) with fields_to_update_config: {fields_to_update_config}")
    
    # Get or create CustomerProfile. Assumes 'customerprofile' related_name on Contact.
    profile, created = CustomerProfile.objects.get_or_create(contact=contact)

    if created:
        logger.info(f"Created CustomerProfile (ID: {profile.id}) for contact {contact.whatsapp_id} (ID: {contact.id}).")
    
    changed_fields = []
    for field_name, value_template in fields_to_update_config.items():
        # Resolve value from template
        resolved_value = _resolve_value(value_template, flow_context, contact)
        
        logger.debug(f"For CustomerProfile of {contact.whatsapp_id}, field '{field_name}', resolved value from template '{value_template}': '{str(resolved_value)[:100]}'.")

        # Specific handling for 'skip' keyword and special fields
        if isinstance(resolved_value, str) and resolved_value.lower() == 'skip':
            # Try to find the model field to check if it's nullable
            model_field = next((f for f in CustomerProfile._meta.fields if f.name == field_name), None)
            if model_field and model_field.null:
                resolved_value = None # Set to None if field is nullable
                logger.debug(f"Field '{field_name}' was 'skip', resolved_value set to None as model field allows null.")
            else:
                logger.warning(f"Field '{field_name}' was 'skip'. If model field is not nullable, this might cause issues or save the string 'skip'.")
                if model_field and not model_field.null and isinstance(model_field, (models.CharField, models.TextField)):
                    resolved_value = "" # Set to empty string for Char/Text fields if not nullable
                elif model_field and not model_field.null:
                    logger.error(f"Field '{field_name}' is not nullable and was skipped. Skipping update for this field.")
                    continue # Do not attempt to save this field

        # Special handling for 'gender' mapping (example based on interactive reply IDs)
        if field_name == 'gender':
            gender_map = {
                "gender_male": "M", # Map reply IDs to model choices
                "gender_female": "F",
                "gender_other": "O",
                "gender_skip": None # If you have a 'prefer_not_to_say' choice, use that value, otherwise None
            }
            if resolved_value is not None:
                original_gender_reply_id = str(resolved_value).lower()
                resolved_value = gender_map.get(original_gender_reply_id, None)
                if resolved_value is None and original_gender_reply_id not in gender_map:
                    logger.warning(f"Unknown gender reply ID '{original_gender_reply_id}'. Setting gender to None.")
            logger.debug(f"Field 'gender' (original reply_id: '{original_gender_reply_id if 'original_gender_reply_id' in locals() else 'N/A'}') mapped to model value: '{resolved_value}'.")
            
        # Special handling for 'date_of_birth' format (assuming YYYY-MM-DD string)
        elif field_name == 'date_of_birth':
            if isinstance(resolved_value, str) and resolved_value:
                # Basic YYYY-MM-DD validation regex
                if not re.match(r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$", resolved_value):
                    logger.warning(f"Invalid date format or range for date_of_birth '{resolved_value}' for contact {contact.id}. Setting to None.")
                    resolved_value = None
            elif not resolved_value: # If it's empty string or None
                resolved_value = None
            logger.debug(f"Field 'date_of_birth' processed value: '{resolved_value}'.")

        # Handle direct model fields vs. JSONField updates (e.g., 'preferences', 'custom_attributes')
        json_field_names = ['preferences', 'custom_attributes'] # Example JSONFields
        
        if field_name in json_field_names:
            json_data = getattr(profile, field_name)
            if json_data is None: json_data = {}
            elif not isinstance(json_data, dict):
                logger.error(f"CustomerProfile.{field_name} for contact {contact.id} is not a dict. Re-initializing.")
                json_data = {}
            
            if isinstance(resolved_value, dict) or resolved_value is None: # Allow setting dict or None for JSONField
                 if json_data != resolved_value: # Only update if value changed
                    setattr(profile, field_name, resolved_value)
                    if field_name not in changed_fields:
                        changed_fields.append(field_name)
                    logger.debug(f"CustomerProfile JSON field '{field_name}' set to '{str(resolved_value)[:100]}'.")
            else:
                logger.warning(f"CustomerProfile JSON field '{field_name}' expected dict or None, got '{type(resolved_value)}'. Skipping update.")
        else: # Direct model fields (non-JSONFields)
            try:
                protected_fields = ['id', 'pk', 'contact', 'contact_id', 'created_at', 'updated_at', 'last_updated_from_conversation', 'user']
                
                if hasattr(profile, field_name) and field_name.lower() not in protected_fields:
                    current_attr_val = getattr(profile, field_name)
                    # Convert Decimal to float for comparison if one is float and other is Decimal
                    if isinstance(current_attr_val, Decimal) and isinstance(resolved_value, float):
                        current_attr_val = float(current_attr_val)
                    elif isinstance(resolved_value, Decimal) and isinstance(current_attr_val, float):
                        resolved_value = float(resolved_value)

                    if current_attr_val != resolved_value:
                        setattr(profile, field_name, resolved_value)
                        if field_name not in changed_fields:
                            changed_fields.append(field_name)
                        logger.debug(f"CustomerProfile field '{field_name}' set to '{str(resolved_value)[:100]}'. Old value was '{str(current_attr_val)[:100]}'")
                    else:
                        logger.debug(f"CustomerProfile field '{field_name}' value '{str(resolved_value)[:100]}' is same as current. No change.")
                else:
                    logger.warning(f"CustomerProfile field '{field_name}' not found on model or is protected for contact {contact.whatsapp_id}.")
            except Exception as e:
                logger.error(f"Error processing CustomerProfile field '{field_name}' for contact {contact.id}: {e}", exc_info=True)
                
    if changed_fields:
        profile.last_updated_from_conversation = timezone.now() # Update timestamp for last conversation update
        # No need to append 'last_updated_from_conversation' to changed_fields if it's not a direct model field
        
        try:
            profile.save(update_fields=changed_fields)
            logger.info(f"CustomerProfile for {contact.whatsapp_id} (ID: {profile.id}) updated. Changed fields: {changed_fields}.")
        except Exception as e_save:
            logger.error(f"Error saving CustomerProfile for {contact.whatsapp_id} (ID: {profile.id}): {e_save}", exc_info=True)
    elif created: # If profile was just created but no specific fields were set in this config
        profile.last_updated_from_conversation = timezone.now()
        profile.save(update_fields=['last_updated_from_conversation'])
        logger.debug(f"Saved newly created CustomerProfile for {contact.whatsapp_id} with initial last_updated_from_conversation timestamp.")
    else:
        logger.debug(f"No fields changed in CustomerProfile for {contact.whatsapp_id}. No save needed.")


@transaction.atomic
def _execute_step_actions(step: FlowStep, contact: Contact, flow_context: dict, is_re_execution: bool = False) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Executes actions defined for a given flow step. This includes sending messages,
    updating contact/customer profile data, switching flows, and triggering integrations.
    """
    actions_to_perform = []
    # Make a copy of context to ensure changes are reflected in this execution scope
    current_step_context = flow_context.copy()

    logger.debug(
        f"Executing actions for step '{step.name}' (ID: {step.id}, Type: {step.step_type}) "
        f"for contact {contact.whatsapp_id} (ID: {contact.id}). Is re-execution: {is_re_execution}. "
        f"Raw Config: {json.dumps(step.config) if isinstance(step.config, dict) else str(step.config)}"
    )

    raw_step_config = step.config or {} # Ensure it's a dict for safety

    if step.step_type == 'send_message':
        try:
            send_message_config = StepConfigSendMessage.model_validate(raw_step_config)
            actual_message_type = send_message_config.message_type
            final_api_data_structure = {}
            logger.debug(f"Step '{step.name}': Validated send_message config. Type: '{actual_message_type}'.")

            payload_field_value = getattr(send_message_config, actual_message_type, None)

            if payload_field_value is None:
                logger.error(f"Step '{step.name}': Payload field '{actual_message_type}' is None after Pydantic validation. Raw Config: {raw_step_config}")
            
            elif actual_message_type == "text":
                text_content: TextMessageContent = payload_field_value
                body_template_string = text_content.body # e.g., "{{ flow_context.my_list }}" or "Hello {{ name }}"
                
                potential_list_value = None
                # Prepare context for Django template rendering
                template_context_data = {
                    'flow_context': current_step_context, # Pass the entire flow_context
                    'contact': contact,
                }
                # Add customer_profile if it exists
                try:
                    template_context_data['customer_profile'] = contact.customerprofile
                except CustomerProfile.DoesNotExist:
                    template_context_data['customer_profile'] = None

                # Create Django Context
                context = Context(template_context_data)

                # Attempt to see if the body_template_string refers to a single context variable that might be a list
                # This is a custom behavior to allow sending multiple messages from a single list variable.
                single_var_match = re.fullmatch(r"\s*\{\{\s*([\w.]+)\s*\}\}\s*", body_template_string)
                if single_var_match:
                    variable_path = single_var_match.group(1).strip()
                    # Directly get the value of the variable from context/contact
                    potential_list_value = _get_value_from_context_or_contact(variable_path, current_step_context, contact)

                if isinstance(potential_list_value, list):
                    # The template variable resolved directly to a list of strings (message parts), send each as a separate message
                    logger.info(f"Step '{step.name}': Template variable '{variable_path}' resolved to a list ({len(potential_list_value)} parts). Generating multiple send actions.")
                    for i, part_body in enumerate(potential_list_value):
                        part_body_str = str(part_body).strip() if part_body is not None else ""
                        if part_body_str:
                             actions_to_perform.append({
                                'type': 'send_whatsapp_message',
                                'message_type': 'text',
                                'data': {'body': part_body_str, 'preview_url': text_content.preview_url}
                            })
                    logger.debug(f"Step '{step.name}': Added send action for text part {i+1} from list variable.")
                    final_api_data_structure = None # Indicate that actions were already added
                else:
                    # This path handles general Django templating, including {% if %} and filters.
                    try:
                        template = Template(body_template_string)
                        resolved_body_string = template.render(context)
                        logger.debug(f"Step '{step.name}': Rendered Django template body: '{str(resolved_body_string)[:100]}{'...' if len(str(resolved_body_string)) > 100 else ''}'")

                        if resolved_body_string is not None:
                            final_body = resolved_body_string.strip()
                            if final_body:
                                final_api_data_structure = {'body': final_body, 'preview_url': text_content.preview_url}
                            else:
                                logger.warning(f"Step '{step.name}': Rendered text body was empty after stripping. No message sent.")
                                final_api_data_structure = None
                        else:
                            logger.warning(f"Step '{step.name}': Rendered text body was None. No message sent.")
                            final_api_data_structure = None

                    except (TemplateSyntaxError, TemplateDoesNotExist) as e:
                        logger.error(f"Django Template error for 'send_message' step '{step.name}' (ID: {step.id}): {e}. Raw template: '{body_template_string}'", exc_info=True)
                        final_api_data_structure = {'body': 'An error occurred while preparing this message. Please contact support.', 'preview_url': False}
                    except Exception as e:
                        logger.error(f"Unexpected error during Django template rendering for 'send_message' step '{step.name}' (ID: {step.id}): {e}", exc_info=True)
                        final_api_data_structure = {'body': 'An unexpected error occurred while preparing this message. Please contact support.', 'preview_url': False}

            elif actual_message_type in ['image', 'document', 'audio', 'video', 'sticker']:
                media_conf: MediaMessageContent = payload_field_value
                media_data_to_send = {}
                valid_source_found = False
                if MEDIA_ASSET_ENABLED and media_conf.asset_pk:
                    try:
                        asset_qs = MediaAsset.objects
                        asset = asset_qs.get(pk=media_conf.asset_pk)
                        if asset.status == 'synced' and asset.whatsapp_media_id and not asset.is_whatsapp_id_potentially_expired():
                            media_data_to_send['id'] = asset.whatsapp_media_id
                            valid_source_found = True
                            logger.info(f"Step '{step.name}': Using MediaAsset {asset.pk} ('{asset.name}') with WA ID: {asset.whatsapp_media_id}.")
                        else:
                            logger.warning(f"Step '{step.name}': MediaAsset {asset.pk} ('{asset.name}') not usable (Status: {asset.status}, WA ID: {asset.whatsapp_media_id}, Expired: {asset.is_whatsapp_id_potentially_expired()}). Trying direct id/link.")
                    except MediaAsset.DoesNotExist:
                        logger.error(f"Step '{step.name}': MediaAsset pk={media_conf.asset_pk} not found. Trying direct id/link.")
                    except Exception as e_asset:
                        logger.error(f"Step '{step.name}': Error accessing MediaAsset pk={media_conf.asset_pk}: {e_asset}", exc_info=True)

                if not valid_source_found:
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
                    if actual_message_type == 'document' and media_conf.filename:
                        media_data_to_send['filename'] = _resolve_value(media_conf.filename, current_step_context, contact)
                    final_api_data_structure = media_data_to_send

            elif actual_message_type == "interactive":
                interactive_payload_obj: InteractiveMessagePayload = payload_field_value
                # Access interactive payload dictionary to allow resolution
                interactive_payload_dict = interactive_payload_obj.model_dump(exclude_none=True, by_alias=True)
                resolved_interactive_dict = _resolve_value(interactive_payload_dict, current_step_context, contact)
                logger.debug(f"Step '{step.name}': Resolved interactive payload: {json.dumps(resolved_interactive_dict, indent=2)}")
                final_api_data_structure = resolved_interactive_dict

            elif actual_message_type == "template":
                template_payload_obj: TemplateMessageContent = payload_field_value
                template_payload_dict = template_payload_obj.model_dump(exclude_none=True, by_alias=True)
                if 'components' in template_payload_dict and template_payload_dict['components']:
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
                final_api_data_structure = {"contacts": resolved_contacts_list}

            elif actual_message_type == "location":
                location_obj: LocationMessageContent = payload_field_value
                location_dict = location_obj.model_dump(exclude_none=True, by_alias=True)
                # Location data is typically fixed, but resolving allows for templates in name/address
                resolved_location_dict = _resolve_value(location_dict, current_step_context, contact) 
                logger.debug(f"Step '{step.name}': Resolved location payload: {json.dumps(resolved_location_dict, indent=2)}")
                final_api_data_structure = resolved_location_dict

            if final_api_data_structure:
                logger.info(f"Step '{step.name}': Prepared '{actual_message_type}' message data. Snippet: {str(final_api_data_structure)[:250]}...")
                actions_to_perform.append({
                    'type': 'send_whatsapp_message',
                    # recipient_wa_id is added by the caller of process_message_for_flow
                    # 'recipient_wa_id': contact.whatsapp_id, 
                    'message_type': actual_message_type,
                    'data': final_api_data_structure
                })
            elif actual_message_type:
                logger.warning(
                    f"Step '{step.name}': No data payload was generated for message_type '{actual_message_type}'. "
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
                    dummy_send_step = FlowStep(
                        name=f"{step.name}_prompt_message",
                        step_type="send_message",
                        config=question_config.message_config
                    )
                    # Recursively call _execute_step_actions to handle sending the question prompt
                    send_actions, _ = _execute_step_actions(dummy_send_step, contact, current_step_context.copy())
                    actions_to_perform.extend(send_actions)
                    logger.debug(f"Generated {len(send_actions)} send actions for question prompt of step '{step.name}'.")
                except ValidationError as ve:
                    logger.error(f"Pydantic validation error for 'message_config' within 'question' step '{step.name}': {ve.errors()}", exc_info=False)
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
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'question' step '{step.name}' (ID: {step.id}) failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_q_step:
            logger.error(f"Unexpected error in 'question' step '{step.name}' (ID: {step.id}): {e_q_step}", exc_info=True)

    elif step.step_type == 'action':
        try:
            action_step_config = StepConfigAction.model_validate(raw_step_config)
            logger.debug(f"Validated 'action' step '{step.name}' (ID: {step.id}) config with {len(action_step_config.actions_to_run)} actions.")
            
            for i, action_item_conf in enumerate(action_step_config.actions_to_run):
                # Ensure action_item_conf is the actual root object after Pydantic validation
                action_item_root = action_item_conf.root
                action_type = action_item_root.action_type
                
                logger.info(f"Step '{step.name}': Executing action item {i+1}/{len(action_step_config.actions_to_run)} of type '{action_type}'.")

                if action_type == ActionType.SET_CONTEXT_VARIABLE:
                    # Use the Django template engine for consistency with message rendering.
                    template_context_data = {
                        'flow_context': current_step_context,
                        'contact': contact,
                    }
                    # Make utility modules available in the template context if they are enabled
                    if CUSTOMER_DATA_UTILS_ENABLED:
                        template_context_data['customer_data'] = {'utils': customer_data_utils}
                    if FOOTBALL_APP_ENABLED:
                        from football_data_app import utils as football_data_utils
                        template_context_data['football_data'] = {'utils': football_data_utils}

                    try:
                        template_context_data['customer_profile'] = contact.customerprofile
                    except CustomerProfile.DoesNotExist:
                        template_context_data['customer_profile'] = None

                    context = Context(template_context_data)
                    
                    resolved_value = None
                    try:
                        # The value_template can be a string to be rendered, or another type.
                        value_template_str = action_item_root.value_template
                        if isinstance(value_template_str, str):
                            # HACK: Special handling for invalid template syntax `get_customer_wallet_balance(...)`
                            # This makes the service robust to this specific error found in logs.
                            if 'get_customer_wallet_balance' in value_template_str:
                                logger.warning(f"Applying special handling for 'get_customer_wallet_balance' in template for step '{step.name}'.")
                                balance_info = customer_data_utils.get_customer_wallet_balance(contact.whatsapp_id)
                                if '.balance' in value_template_str:
                                    resolved_value = balance_info.get('balance', 0.0)
                                else:
                                    resolved_value = balance_info # Return the whole dict
                            else:
                                template = Template(value_template_str)
                                resolved_value = template.render(context)
                        else:
                            # If it's not a string, it's a literal value, no need to render.
                            resolved_value = template.render(context)
                    except (TemplateSyntaxError, TemplateDoesNotExist) as e:
                        logger.error(f"Django Template error for 'set_context_variable' action in step '{step.name}': {e}. Raw template: '{action_item_root.value_template}'", exc_info=True)
                        resolved_value = f"TEMPLATE_ERROR: {e}" # Set an error message in the context for debugging
                    
                    current_step_context[action_item_root.variable_name] = resolved_value
                    logger.info(f"Step '{step.name}': Context variable '{action_item_root.variable_name}' set to: '{str(resolved_value)[:100]}'.")
                
                elif action_type == ActionType.UPDATE_CONTACT_FIELD:
                    resolved_value = _resolve_value(action_item_root.value_template, current_step_context, contact)
                    _update_contact_data(contact, action_item_root.field_path, resolved_value)
                
                elif action_type == ActionType.UPDATE_CUSTOMER_PROFILE:
                    resolved_fields_to_update = _resolve_value(action_item_root.fields_to_update, current_step_context, contact)
                    _update_customer_profile_data(contact, resolved_fields_to_update, current_step_context)
                
                elif action_type == ActionType.SWITCH_FLOW:
                    resolved_initial_context = _resolve_value(action_item_root.initial_context_template or {}, current_step_context, contact)
                    resolved_msg_body = _resolve_value(action_item_root.message_to_evaluate_for_new_flow, current_step_context, contact) if action_item_root.message_to_evaluate_for_new_flow else None
                    
                    logger.info(f"Step '{step.name}': Queuing switch to flow '{action_item_root.target_flow_name}'. Initial context: {resolved_initial_context}, Trigger message: '{resolved_msg_body}'")
                    actions_to_perform.append({
                        'type': '_internal_command_switch_flow',
                        'target_flow_name': action_item_root.target_flow_name,
                        'initial_context': resolved_initial_context if isinstance(resolved_initial_context, dict) else {},
                        'new_flow_trigger_message_body': resolved_msg_body
                    })
                    logger.debug(f"Step '{step.name}': Switch flow action encountered. Further actions in this step will be skipped.")
                    break # Stop processing further actions in this step after a flow switch command

                elif action_type == ActionType.FETCH_FOOTBALL_DATA:
                    if not FOOTBALL_APP_ENABLED:
                        logger.error(f"Step '{step.name}': fetch_football_data action called, but football_data_app utilities not available.")
                        current_step_context[action_item_root.output_variable_name] = "Error: Football data feature is currently unavailable."
                        continue

                    selected_league_code = None
                    if hasattr(action_item_root, 'league_code_variable') and action_item_root.league_code_variable:
                        selected_league_code = _get_value_from_context_or_contact(action_item_root.league_code_variable, current_step_context, contact)

                    days_past = action_item_root.days_past_for_results
                    days_ahead = action_item_root.days_ahead_for_fixtures

                    logger.info(f"Step '{step.name}': Calling get_formatted_football_data. League code from context ('{action_item_root.league_code_variable}'): '{selected_league_code}', Data type: '{action_item_root.data_type}'.")

                    display_text = get_formatted_football_data(
                        league_code=selected_league_code,
                        data_type=action_item_root.data_type,
                        days_ahead=days_ahead,
                        days_past=days_past
                    )
                    current_step_context[action_item_root.output_variable_name] = display_text
                    logger.info(f"Step '{step.name}': Context variable '{action_item_root.output_variable_name}' set after fetching football data. Length: {len(display_text)}")
                
                # --- NEW ACTION DISPATCHES ---
                elif action_type == ActionType.CREATE_ACCOUNT:
                    if not CUSTOMER_DATA_UTILS_ENABLED:
                        logger.error(f"Step '{step.name}': 'create_account' action called, but customer_data utilities not available.")
                        current_step_context['account_creation_status'] = False
                        current_step_context['account_creation_message'] = "Error: Account creation feature is unavailable."
                        continue

                    # Resolve all templates for parameters
                    email = _resolve_value(action_item_root.email_template, current_step_context, contact) if hasattr(action_item_root, 'email_template') else None
                    first_name = _resolve_value(action_item_root.first_name_template, current_step_context, contact) if hasattr(action_item_root, 'first_name_template') else None
                    last_name = _resolve_value(action_item_root.last_name_template, current_step_context, contact) if hasattr(action_item_root, 'last_name_template') else None
                    acquisition_source = _resolve_value(action_item_root.acquisition_source_template, current_step_context, contact) if hasattr(action_item_root, 'acquisition_source_template') else None
                    initial_balance = action_item_root.initial_balance if hasattr(action_item_root, 'initial_balance') else 0.0

                    result = customer_data_utils.create_or_get_customer_account(
                        whatsapp_id=contact.whatsapp_id,
                        name=contact.name, # Use contact's current name
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        acquisition_source=acquisition_source,
                        initial_balance=initial_balance
                    )
                    current_step_context['account_creation_status'] = result['success']
                    current_step_context['account_creation_message'] = result['message']
                    current_step_context['user_created'] = result.get('created_user', False) # For transition conditions
                    if result['success'] and result.get('user'):
                        # Add user's username and generated password to context for use in subsequent message templates
                        current_step_context['user_username'] = result['user'].username
                        current_step_context['generated_password'] = result.get('generated_password')
                        logger.info(f"Account creation/link successful for {contact.whatsapp_id}. User created: {result.get('created_user', False)}")
                    else:
                        logger.error(f"Account creation/link failed for {contact.whatsapp_id}: {result['message']}")

                elif action_type == ActionType.PERFORM_DEPOSIT:
                    if not CUSTOMER_DATA_UTILS_ENABLED:
                        logger.error(f"Step '{step.name}': 'perform_deposit' action called, but customer_data utilities not available.")
                        current_step_context['deposit_status'] = False
                        current_step_context['deposit_message'] = "Error: Deposit feature is unavailable."
                        continue
                    
                    # Resolve amount and validate it's a float
                    resolved_amount = _resolve_value(action_item_root.amount_template, current_step_context, contact)
                    try:
                        resolved_amount = float(resolved_amount)
                    except (ValueError, TypeError):
                        logger.error(f"Step '{step.name}': Deposit amount '{resolved_amount}' could not be converted to float.")
                        current_step_context['deposit_status'] = False
                        current_step_context['deposit_message'] = "Invalid deposit amount provided."
                        continue

                    # Resolve all other templates from the action config
                    resolved_description = _resolve_value(action_item_root.description_template, current_step_context, contact)
                    resolved_phone_number = _resolve_value(action_item_root.phone_number_template, current_step_context, contact) if hasattr(action_item_root, 'phone_number_template') and action_item_root.phone_number_template else None
                    resolved_paynow_method_type = _resolve_value(action_item_root.paynow_method_type_template, current_step_context, contact) if hasattr(action_item_root, 'paynow_method_type_template') and action_item_root.paynow_method_type_template else None
                    
                    # Call the updated perform_deposit function with all necessary parameters
                    result = customer_data_utils.perform_deposit(
                        whatsapp_id=contact.whatsapp_id,
                        amount=resolved_amount,
                        payment_method=action_item_root.payment_method, # This is a literal, not a template
                        description=resolved_description,
                        phone_number=resolved_phone_number,
                        paynow_method_type=resolved_paynow_method_type
                    )
                    
                    # Update context with the result from the utility function
                    current_step_context['deposit_status'] = result['success']
                    current_step_context['deposit_message'] = result['message']
                    
                    # Handle different result structures based on payment method
                    if result.get('new_balance') is not None: # For manual deposits
                        current_step_context['current_balance'] = result['new_balance']
                    
                    # For Paynow initiations, save the details needed for polling and user instructions
                    if result.get('poll_url'):
                        current_step_context['paynow_poll_url'] = result.get('poll_url')
                    if result.get('instructions'):
                        current_step_context['paynow_instructions'] = result.get('instructions')

                    # Add the payment_method to the context for conditional messages later
                    current_step_context['payment_method'] = action_item_root.payment_method

                    if result['success']:
                        logger.info(f"Deposit action for {contact.whatsapp_id} processed successfully. Message: {result['message']}")
                    else:
                        logger.error(f"Deposit failed for {contact.whatsapp_id}: {result['message']}")

                elif action_type == ActionType.PERFORM_WITHDRAWAL:
                    if not CUSTOMER_DATA_UTILS_ENABLED:
                        logger.error(f"Step '{step.name}': 'perform_withdrawal' action called, but customer_data utilities not available.")
                        current_step_context['withdrawal_status'] = False
                        current_step_context['withdrawal_message'] = "Error: Withdrawal feature is unavailable."
                        continue
                    
                    resolved_amount = _resolve_value(action_item_root.amount_template, current_step_context, contact)
                    # Ensure amount is float
                    try:
                        resolved_amount = float(resolved_amount)
                    except (ValueError, TypeError):
                        logger.error(f"Step '{step.name}': Withdrawal amount '{resolved_amount}' could not be converted to float.")
                        current_step_context['withdrawal_status'] = False
                        current_step_context['withdrawal_message'] = "Invalid withdrawal amount provided."
                        continue
                    
                    # Get payment method from either the direct field or the template
                    resolved_payment_method = None
                    if action_item_root.payment_method:
                        resolved_payment_method = action_item_root.payment_method
                    elif action_item_root.payment_method_template:
                        resolved_payment_method = _resolve_value(action_item_root.payment_method_template, current_step_context, contact)

                    resolved_phone_number = _resolve_value(action_item_root.phone_number_template, current_step_context, contact)
                    resolved_description = _resolve_value(action_item_root.description_template, current_step_context, contact)
                    
                    result = customer_data_utils.perform_withdrawal(
                        whatsapp_id=contact.whatsapp_id,
                        amount=resolved_amount,
                        payment_method=resolved_payment_method,
                        phone_number=resolved_phone_number,
                        description=resolved_description
                    )
                    current_step_context['withdrawal_status'] = result['success']
                    # Ensure withdrawal_message is set even if result['message'] is missing
                    # This handles cases where perform_withdrawal might return success:False but no message
                    current_step_context['withdrawal_message'] = result['message']
                    if result['success']:
                        current_step_context['current_balance'] = result['new_balance']
                        logger.info(f"Withdrawal successful for {contact.whatsapp_id}. New balance: {result['new_balance']:.2f}")
                    else:
                        logger.error(f"Withdrawal failed for {contact.whatsapp_id}: {result['message']}")

                elif action_type == ActionType.HANDLE_BETTING_ACTION:
                    if not FOOTBALL_APP_ENABLED:
                        logger.error(f"Step '{step.name}': 'handle_betting_action' action called, but football_data utilities not available.")
                        current_step_context[f"{action_item_root.betting_action}_status"] = False
                        current_step_context[f"{action_item_root.betting_action}_message"] = "Error: Betting feature is unavailable."
                        continue
                    
                    # Resolve all relevant parameters for betting action
                    resolved_stake = _resolve_value(action_item_root.stake_template, current_step_context, contact) if hasattr(action_item_root, 'stake_template') else None
                    try:
                        if resolved_stake is not None:
                            resolved_stake = float(resolved_stake)
                    except (ValueError, TypeError):
                        logger.error(f"Step '{step.name}': Betting stake '{resolved_stake}' could not be converted to float.")
                        resolved_stake = None # Ensure it's None if invalid

                    resolved_market_outcome_id = _resolve_value(action_item_root.market_outcome_id_template, current_step_context, contact) if hasattr(action_item_root, 'market_outcome_id_template') else None
                    resolved_raw_bet_string = _resolve_value(action_item_root.raw_bet_string_template, current_step_context, contact) if hasattr(action_item_root, 'raw_bet_string_template') else None
                    
                    # Parameters for view_matches/view_results (if the betting_action itself involves fetching data)
                    resolved_league_code = _resolve_value(action_item_root.league_code_template, current_step_context, contact) if hasattr(action_item_root, 'league_code_template') else None
                    days_past = action_item_root.days_past if hasattr(action_item_root, 'days_past') else 2
                    days_ahead = action_item_root.days_ahead if hasattr(action_item_root, 'days_ahead') else 7


                    result = handle_football_betting_action(
                        contact=contact,
                        action_type=action_item_root.betting_action,
                        flow_context=current_step_context, # Pass context directly for internal updates by betting action
                        stake=resolved_stake,
                        market_outcome_id=resolved_market_outcome_id,
                        raw_bet_string=resolved_raw_bet_string,
                        # Pass data fetching params
                        league_code=resolved_league_code,
                        days_ahead=days_ahead,
                        days_past=days_past
                    )
                    current_step_context[f"{action_item_root.betting_action}_status"] = result['success']
                    current_step_context[f"{action_item_root.betting_action}_message"] = result['message']
                    if result['data']:
                        current_step_context.update(result['data']) # Merge any returned data into context
                    if result['success']:
                        logger.info(f"Betting action '{action_item_root.betting_action}' successful for {contact.whatsapp_id}.")
                    else:
                        logger.error(f"Betting action '{action_item_root.betting_action}' failed for {contact.whatsapp_id}: {result['message']}")
                # --- END NEW ACTION DISPATCHES ---
                
                else:
                    logger.warning(f"Step '{step.name}': Unknown or unhandled action_type '{action_type}'. Config: {action_item_conf.model_dump_json(indent=2)}")
        
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'action' step '{step.name}' (ID: {step.id}) failed: {e.errors()}. Raw config: {raw_step_config}", exc_info=False)
        except Exception as e_act_step:
            logger.error(f"Unexpected error in 'action' step '{step.name}' (ID: {step.id}): {e_act_step}", exc_info=True)

    elif step.step_type == 'end_flow':
        try:
            end_flow_config = StepConfigEndFlow.model_validate(raw_step_config)
            logger.info(f"Executing 'end_flow' step '{step.name}' (ID: {step.id}) for contact {contact.whatsapp_id} (ID: {contact.id}).")
            
            if end_flow_config.message_config:
                logger.debug(f"Step '{step.name}': End_flow step has a final message to send. Config: {end_flow_config.message_config}")
                try:
                    dummy_end_msg_step = FlowStep(
                        name=f"{step.name}_final_message",
                        step_type="send_message",
                        config=end_flow_config.message_config
                    )
                    send_actions, _ = _execute_step_actions(dummy_end_msg_step, contact, current_step_context.copy())
                    actions_to_perform.extend(send_actions)
                    logger.debug(f"Generated {len(send_actions)} send actions for the final message of end_flow step '{step.name}'.")
                except ValidationError as ve_msg_conf:
                    logger.error(f"Pydantic validation error for 'message_config' within 'end_flow' step '{step.name}': {ve_msg_conf.errors()}", exc_info=False)
                except Exception as ex_end_msg:
                    logger.error(f"Error processing message_config for 'end_flow' step '{step.name}': {ex_end_msg}", exc_info=True)
            else:
                logger.debug(f"Step '{step.name}': No final message configured for this end_flow step.")
            
            clear_reason = f'Flow ended at step {step.name} (ID: {step.id})'
            logger.info(f"Step '{step.name}': {clear_reason}. Clearing flow state directly for contact {contact.whatsapp_id}.")
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': clear_reason}) # Defer actual clearing
            
        except ValidationError as e_conf:
            logger.error(f"Pydantic validation error for 'end_flow' step '{step.name}' (ID: {step.id}) config: {e_conf.errors()}. Raw config: {raw_step_config}", exc_info=False)
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f"Error validating config for end_flow step '{step.name}' (ID: {step.id})"})
        except Exception as e_end_step:
            logger.error(f"Unexpected error in 'end_flow' step '{step.name}' (ID: {step.id}): {e_end_step}", exc_info=True)
            actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f"Error executing end_flow step '{step.name}' (ID: {step.id})"})

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
            logger.info(f"Contact {contact.whatsapp_id} (ID: {contact.id}, Name: {contact.name or 'N/A'}) flagged for human intervention from step '{step.name}'.")
            
            notification_info = _resolve_value(
                handover_config.notification_details,
                current_step_context,
                contact
            )
            # This action might be sent to an internal notification system, not WhatsApp directly
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

def _trigger_new_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    actions_to_perform = []
    initial_flow_context = {}
    message_text_body = None
    if message_data.get('type') == 'text':
        message_text_body = message_data.get('text', {}).get('body', '').lower().strip()

    triggered_flow = None
    # Assuming Flow model has is_active and trigger_keywords fields
    active_flows = Flow.objects.filter(is_active=True).order_by('name')

    if message_text_body:
        for flow_candidate in active_flows:
            if isinstance(flow_candidate.trigger_keywords, list): # Assumes trigger_keywords is a JSONField or similar list
                for keyword in flow_candidate.trigger_keywords:
                    if isinstance(keyword, str) and keyword.strip() and keyword.strip().lower() in message_text_body:
                        triggered_flow = flow_candidate
                        logger.info(f"Keyword '{keyword}' triggered flow '{flow_candidate.name}' for contact {contact.whatsapp_id}.")
                        break
            if triggered_flow:
                break # A flow was triggered, stop checking others
    
    if triggered_flow:
        # Assuming FlowStep has is_entry_point field and a related manager for steps
        entry_point_step = FlowStep.objects.filter(flow=triggered_flow, is_entry_point=True).first()
        if entry_point_step:
            logger.info(f"Starting flow '{triggered_flow.name}' for contact {contact.whatsapp_id} at entry step '{entry_point_step.name}'.")
            _clear_contact_flow_state(contact) # Clear any existing state
            
            # Create new ContactFlowState
            contact_flow_state = ContactFlowState.objects.create(
                contact=contact,
                current_flow=triggered_flow,
                current_step=entry_point_step,
                flow_context_data=initial_flow_context, # Initial empty context
                started_at=timezone.now()
            )
            
            # Execute actions of the entry step immediately
            step_actions, updated_flow_context = _execute_step_actions(entry_point_step, contact, initial_flow_context.copy())
            actions_to_perform.extend(step_actions)
            
            # Update the flow context in the DB after initial actions
            current_db_state = ContactFlowState.objects.filter(pk=contact_flow_state.pk).first()
            if current_db_state:
                if current_db_state.flow_context_data != updated_flow_context:
                    current_db_state.flow_context_data = updated_flow_context
                    current_db_state.save(update_fields=['flow_context_data', 'last_updated_at'])
            else:
                logger.info(f"Flow state for contact {contact.whatsapp_id} was cleared by entry step '{entry_point_step.name}'. Context not saved.")
        else:
            logger.error(f"Flow '{triggered_flow.name}' is active but has no entry point step defined.")
    else:
        logger.info(f"No active flow triggered for contact {contact.whatsapp_id} with message: {message_text_body[:100] if message_text_body else message_data.get('type')}")
    return actions_to_perform

def _handle_active_flow_step(contact_flow_state: ContactFlowState, contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    """
    Handles processing of a message when a contact is already in an active flow.
    Manages question replies, transitions, and fallback logic.
    """
    current_step = contact_flow_state.current_step
    flow_context = contact_flow_state.flow_context_data if isinstance(contact_flow_state.flow_context_data, dict) else {}
    actions_to_perform = []

    logger.info(
        f"Handling active flow for contact {contact.whatsapp_id} (ID: {contact.id}). Current Flow: '{contact_flow_state.current_flow.name}', "
        f"Step: '{current_step.name}' (ID: {current_step.id}, Type: {current_step.step_type})."
    )
    logger.debug(f"Incoming message type: {message_data.get('type')}, data (snippet): {str(message_data)[:200]}. Current flow context (snippet): {str(flow_context)[:200]}")

    question_expectation = flow_context.get('_question_awaiting_reply_for')
    is_processing_reply_for_current_question = False
    reply_was_valid_for_question = False

    # Check if the current step is a question and is awaiting a reply from the user
    if current_step.step_type == 'question' and \
      isinstance(question_expectation, dict) and \
      question_expectation.get('original_question_step_id') == current_step.id:
        
        is_processing_reply_for_current_question = True
        variable_to_save_name = question_expectation.get('variable_name')
        expected_reply_type = question_expectation.get('expected_type')
        validation_regex_ctx = question_expectation.get('validation_regex')
        
        user_text = message_data.get('text', {}).get('body', '').strip() if message_data.get('type') == 'text' else None
        interactive_reply_id = None
        if message_data.get('type') == 'interactive':
            interactive_payload = message_data.get('interactive', {})
            interactive_type_from_payload = interactive_payload.get('type')
            if interactive_type_from_payload == 'button_reply' and isinstance(interactive_payload.get('button_reply'), dict):
                interactive_reply_id = interactive_payload.get('button_reply', {}).get('id')
            elif interactive_type_from_payload == 'list_reply' and isinstance(interactive_payload.get('list_reply'), dict):
                interactive_reply_id = interactive_payload.get('list_reply', {}).get('id')
        
        logger.debug(f"Processing reply for question '{current_step.name}'. Expected type: '{expected_reply_type}'. User text: '{user_text}', Interactive ID: '{interactive_reply_id}'.")

        value_to_save = None

        # Validate and extract the value based on expected_reply_type
        if expected_reply_type == 'text' and user_text is not None:
            value_to_save = user_text
            reply_was_valid_for_question = True
            if validation_regex_ctx and not re.match(validation_regex_ctx, user_text):
                reply_was_valid_for_question = False; value_to_save = None
                logger.debug(f"Text reply '{user_text}' for question '{current_step.name}' did not match regex '{validation_regex_ctx}'.")
        elif expected_reply_type == 'email':
            email_r = validation_regex_ctx or r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if user_text and re.match(email_r, user_text):
                value_to_save = user_text; reply_was_valid_for_question = True
            else: logger.debug(f"Email reply '{user_text}' for question '{current_step.name}' did not match regex '{email_r}'.")
        elif expected_reply_type == 'number' and user_text is not None:
            try:
                # Try parsing as float if decimal is present, else int
                num_val = float(user_text) if '.' in user_text or (validation_regex_ctx and '.' in validation_regex_ctx) else int(user_text)
                if validation_regex_ctx and not re.match(validation_regex_ctx, user_text):
                    logger.debug(f"Number string reply '{user_text}' for question '{current_step.name}' did not match regex '{validation_regex_ctx}'.")
                else: value_to_save = num_val; reply_was_valid_for_question = True
            except ValueError: logger.debug(f"Could not parse '{user_text}' as a number for question '{current_step.name}'.")
        elif expected_reply_type == 'interactive_id' and interactive_reply_id is not None:
            value_to_save = interactive_reply_id; reply_was_valid_for_question = True
            if validation_regex_ctx and not re.match(validation_regex_ctx, interactive_reply_id):
                reply_was_valid_for_question = False; value_to_save = None
                logger.debug(f"Interactive ID reply '{interactive_reply_id}' for question '{current_step.name}' did not match regex '{validation_regex_ctx}'.")
        elif expected_reply_type == 'any':
            # For 'any' type, try text, then interactive_id, then general message data
            if user_text is not None: value_to_save = user_text
            elif interactive_reply_id is not None: value_to_save = interactive_reply_id
            elif message_data:
                # If it's a media message, save its ID or link if available
                if message_data.get('type') in ['image', 'video', 'audio', 'document', 'sticker']:
                    value_to_save = message_data.get(message_data.get('type'), {}).get('id') or message_data.get(message_data.get('type'), {}).get('link') or message_data.get('type')
                elif message_data.get('type') == 'location':
                    value_to_save = message_data.get('location', {}) # Save location dict
                else: value_to_save = str(message_data)[:255] # Fallback to string representation
            else: value_to_save = None
            reply_was_valid_for_question = value_to_save is not None

        if reply_was_valid_for_question:
            if variable_to_save_name:
                flow_context[variable_to_save_name] = value_to_save
                logger.info(f"Saved valid reply for var '{variable_to_save_name}' in Q-step '{current_step.name}'. Value (type {type(value_to_save)}): '{str(value_to_save)[:100]}'.")
                flow_context.pop('_general_invalid_action_count', None) # Reset general invalid counter on valid question reply
            else:
                logger.info(f"Valid reply received for Q-step '{current_step.name}', but no 'save_to_variable' defined. Value (type {type(value_to_save)}): '{str(value_to_save)[:100]}'.")
            flow_context.pop('_fallback_count', None) # Clear fallback count on valid reply
            
            contact_flow_state.flow_context_data = flow_context
            contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])
            logger.debug(f"Saved updated flow_context for contact {contact.whatsapp_id} after processing valid reply for Q-step '{current_step.name}'.")
        
        else: # Reply was NOT valid
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
                    # Re-execute original question step to send its message again
                    step_actions, updated_context_from_re_execution = _execute_step_actions(current_step, contact, flow_context.copy(), is_re_execution=True)
                    actions_to_perform.extend(step_actions)
                    flow_context = updated_context_from_re_execution # Ensure context reflects any changes from re-execution
                contact_flow_state.flow_context_data = flow_context
                contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])
                logger.debug(f"Q '{current_step.name}' re-prompt actions generated. Flow context updated. Returning to wait for new reply.")
                return actions_to_perform # Stop further processing in this turn, await new reply
            else: # Max retries reached
                logger.info(f"Max retries ({max_retries}) reached for Q '{current_step.name}'. Executing 'action_after_max_retries' if configured.")
                flow_context.pop('_fallback_count', None) # Clear fallback count
                action_after_max_retries = fallback_config.get('action_after_max_retries', 'human_handover') # Default to human handover
                
                if action_after_max_retries == 'human_handover':
                    logger.info(f"Max retries for Q '{current_step.name}'. Fallback: Initiating human handover for {contact.whatsapp_id}.")
                    handover_message_text = fallback_config.get('handover_message_text', "Sorry, I'm having trouble understanding. Let me connect you to an agent.")
                    resolved_handover_msg = _resolve_value(handover_message_text, flow_context, contact)
                    actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_handover_msg}})
                    # Flag for human intervention and clear flow state
                    actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Max retries for Q {current_step.name}'})
                    contact.needs_human_intervention = True; contact.intervention_requested_at = timezone.now()
                    contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
                    return actions_to_perform # Stop and signal handover
                elif action_after_max_retries == 'end_flow':
                    logger.info(f"Max retries for Q '{current_step.name}'. Fallback: Ending flow for {contact.whatsapp_id}.")
                    actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Max retries for Q {current_step.name}, ending flow.'})
                    if fallback_config.get('end_flow_message_text'):
                            actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': _resolve_value(fallback_config['end_flow_message_text'], flow_context, contact)}})
                    return actions_to_perform # Stop flow
                else:
                    logger.info(f"Max retries for Q '{current_step.name}'. Action_after_max_retries is '{action_after_max_retries}' (not direct handover/end). Proceeding to general transitions.")
    
    # If not actively processing a question reply (or if reply was valid and handled), proceed to evaluate general transitions
    if not (is_processing_reply_for_current_question and not reply_was_valid_for_question):
        # Fetch transitions related to the current step
        transitions = FlowTransition.objects.filter(current_step=current_step).select_related('next_step').order_by('priority')
        next_step_to_transition_to = None
        chosen_transition_info = "None"

        logger.debug(f"Evaluating {transitions.count()} general transitions for step '{current_step.name}'.")
        for transition in transitions:
            if _evaluate_transition_condition(transition, contact, message_data, flow_context.copy(), incoming_message_obj):
                next_step_to_transition_to = transition.next_step
                chosen_transition_info = f"ID {transition.id} (Priority {transition.priority})"
                logger.info(f"Transition {chosen_transition_info} condition met: From '{current_step.name}' to '{next_step_to_transition_to.name}'.")
                break # Found a matching transition, exit loop
        
        if next_step_to_transition_to:
            # Transition to the next step and execute its actions
            actions_from_next_step, _ = _transition_to_step(
                contact_flow_state, next_step_to_transition_to, flow_context, contact, message_data
            )
            actions_to_perform.extend(actions_from_next_step)
            logger.debug(f"Accumulated {len(actions_from_next_step)} actions after transition to '{next_step_to_transition_to.name}'. Total: {len(actions_to_perform)}.")
        elif not actions_to_perform: # Only apply general fallback if no actions have been generated yet
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
            elif fallback_config.get('action') == 'end_flow':
                logger.info(f"Step '{current_step.name}': General fallback ending flow directly for {contact.whatsapp_id}.")
                actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'General fallback ending flow at {current_step.name}'})
                if fallback_config.get('end_flow_message_text'):
                    resolved_end_msg = _resolve_value(fallback_config['end_flow_message_text'], flow_context, contact)
                    actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_end_msg}})
            else:
                if not actions_to_perform: # If no explicit fallback message/action and nothing else generated
                    general_invalid_count = flow_context.get('_general_invalid_action_count', 0) + 1
                    flow_context['_general_invalid_action_count'] = general_invalid_count

                    if general_invalid_count < 3:
                        logger.info(f"Step '{current_step.name}': General invalid action (Attempt {general_invalid_count} of 2). Sending gentle notification.")
                        actions_to_perform.append({
                            'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                            'message_type': 'text', 'data': {'body': "Sorry, that's not a valid option for the current step. Please try something else or type 'menu' for main options."}
                        })
                        # Save the updated context with the incremented counter
                        contact_flow_state.flow_context_data = flow_context
                        contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])
                    else:
                        logger.info(f"Step '{current_step.name}': General invalid action (Attempt {general_invalid_count}). Max attempts reached. Resetting flow state.")
                        actions_to_perform.append({
                            'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                            'message_type': 'text', 'data': {'body': "It seems we're having trouble. Your current session has been reset. You can try keywords like 'menu', 'fixtures', or 'help' to start over."}
                        })
                        flow_context.pop('_general_invalid_action_count', None) # Clear the counter
                        # The actual clearing of flow state is handled by the internal command processor
                        actions_to_perform.append({'type': '_internal_command_clear_flow_state', 'reason': f'Max general invalid actions at step {current_step.name}'})
                        # No need to save context here if it's about to be cleared by the command.
                        # If the command doesn't clear context immediately, save it:
                        # contact_flow_state.flow_context_data = flow_context
                        # contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])
    return actions_to_perform


def _evaluate_transition_condition(
    transition: FlowTransition,    
    contact: Contact,    
    message_data: dict,    
    flow_context: dict,    
    incoming_message_obj: Optional[Message]    
) -> bool:
    """
    Evaluates the condition for a given flow transition.
    """
    config = transition.condition_config
    if not isinstance(config, dict):
        logger.warning(f"Transition ID {transition.id} (step '{transition.current_step.name}') has invalid condition_config (not a dict): {config}")
        return False
        
    condition_type = config.get('type')
    is_automatic_check = not message_data # True if called from _process_automatic_transitions

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

    # User-dependent conditions cannot be met during an automatic check (no user message)
    user_dependent_conditions = [
        'user_reply_matches_keyword', 'user_reply_contains_keyword',    
        'interactive_reply_id_equals', 'message_type_is',    
        'user_reply_matches_regex', 'nfm_response_field_equals',
        'user_requests_human', 'user_reply_received'    
    ]
    if is_automatic_check and condition_type in user_dependent_conditions and condition_type != 'question_reply_is_valid':
        logger.debug(f"Transition ID {transition.id}: Condition '{condition_type}' requires user message; not met for automatic check.")
        return False

    user_text = ""
    if message_data and message_data.get('type') == 'text' and isinstance(message_data.get('text'), dict):
        user_text = message_data.get('text', {}).get('body', '').strip()

    interactive_reply_id = None
    nfm_response_data = None
    if message_data and message_data.get('type') == 'interactive' and isinstance(message_data.get('interactive'), dict):
        interactive_payload = message_data.get('interactive', {})
        interactive_type_from_payload = interactive_payload.get('type')
        if interactive_type_from_payload == 'button_reply' and isinstance(interactive_payload.get('button_reply'), dict):
            interactive_reply_id = interactive_payload.get('button_reply', {}).get('id')
        elif interactive_type_from_payload == 'list_reply' and isinstance(interactive_payload.get('list_reply'), dict):
            interactive_reply_id = interactive_payload.get('list_reply', {}).get('id')
        elif interactive_type_from_payload == 'nfm_reply' and isinstance(interactive_payload.get('nfm_reply'), dict):
            nfm_payload = interactive_payload.get('nfm_reply', {})
            response_json_str = nfm_payload.get('response_json')
            if response_json_str:
                try:    
                    nfm_response_data = json.loads(response_json_str)
                except json.JSONDecodeError:    
                    logger.warning(f"Could not parse nfm_reply response_json for transition {transition.id}: {response_json_str[:100]}")

    value_for_condition_comparison = config.get('value')

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
        
    elif condition_type == 'variable_equals':
        variable_name = config.get('variable_name')
        if variable_name is None: logger.warning(f"T_ID {transition.id}: 'variable_equals' missing variable_name."); return False
        actual_value = _get_value_from_context_or_contact(variable_name, flow_context, contact)
        expected_value_str = str(value_for_condition_comparison)
        actual_value_str = str(actual_value)
        is_match = actual_value_str == expected_value_str
        logger.debug(f"T_ID {transition.id} ('variable_equals'): Var '{variable_name}' (Actual: '{actual_value_str}') vs Expected: '{expected_value_str}'. Match: {is_match}")
        return is_match

    elif condition_type == 'variable_exists':
        variable_name = config.get('variable_name')
        if variable_name is None: logger.warning(f"T_ID {transition.id}: 'variable_exists' missing variable_name."); return False
        # Check for truthiness (e.g., non-empty string, non-zero number, not None)
        # instead of just `is not None`. This correctly handles empty strings for fields like 'email'.
        value = _get_value_from_context_or_contact(variable_name, flow_context, contact)
        exists = bool(value)
        logger.debug(f"T_ID {transition.id} ('variable_exists'): Var '{variable_name}' (Value: '{value}'). Exists (is truthy): {exists}")
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
        # NFM = Native Flow Message, assuming structure like message_data['interactive']['nfm_reply']['response_json']
        if not nfm_response_data: return False
        field_path = config.get('field_path')
        if not field_path: logger.warning(f"T_ID {transition.id}: 'nfm_response_field_equals' missing field_path."); return False
        
        actual_val_from_nfm = nfm_response_data
        try:
            for part in field_path.split('.'):
                if isinstance(actual_val_from_nfm, dict):
                    actual_val_from_nfm = actual_val_from_nfm.get(part)
                elif isinstance(actual_val_from_nfm, list) and part.isdigit():
                    idx = int(part)
                    if 0 <= idx < len(actual_val_from_nfm): actual_val_from_nfm = actual_val_from_nfm[idx]
                    else: actual_val_from_nfm = None; break
                else: actual_val_from_nfm = None; break
        except Exception: actual_val_from_nfm = None

        is_match = actual_val_from_nfm == value_for_condition_comparison
        logger.debug(f"T_ID {transition.id} ('nfm_response_field_equals'): Path '{field_path}' (Actual NFM val: '{actual_val_from_nfm}') vs Expected: '{value_for_condition_comparison}'. Match: {is_match}")
        return is_match

    elif condition_type == 'question_reply_is_valid':
        question_expectation = flow_context.get('_question_awaiting_reply_for')
        expected_bool_value = bool(value_for_condition_comparison is True) # True if config value is true, False if false

        if question_expectation and isinstance(question_expectation, dict):
            var_name_for_reply = question_expectation.get('variable_name')
            # Check if the variable was successfully set in flow_context (meaning valid reply)
            is_var_set_and_not_none = var_name_for_reply in flow_context and flow_context.get(var_name_for_reply) is not None
            
            logger.debug(f"T_ID {transition.id} ('question_reply_is_valid'): Expected valid = {expected_bool_value}. Actual reply was valid (var '{var_name_for_reply}' set): {is_var_set_and_not_none}.")
            return is_var_set_and_not_none if expected_bool_value else not is_var_set_and_not_none
        else:
            logger.debug(f"T_ID {transition.id} ('question_reply_is_valid'): No active question expectation. Expected valid = {expected_bool_value}. Returning False for positive check, True for negative check.")
            # If no question was active, then a positive 'is_valid' check is false, and a negative 'is_valid' check is true
            return not expected_bool_value

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
        
    elif condition_type == 'user_reply_received':
        # This condition is met if there's any message_data for the current processing cycle (i.e., not an automatic transition)
        if not is_automatic_check and message_data and message_data.get('type'):
            logger.debug(f"T_ID {transition.id}: Condition 'user_reply_received' met because a message of type '{message_data.get('type')}' was part of current processing cycle.")
            return True
        logger.debug(f"T_ID {transition.id}: Condition 'user_reply_received' not met (is_automatic_check: {is_automatic_check} or no message type in message_data).")
        return False

    logger.warning(f"Unknown or unhandled condition type: '{condition_type}' for transition ID {transition.id} (Step '{transition.current_step.name}').")
    return False


def _process_automatic_transitions(contact_flow_state: ContactFlowState, contact: Contact) -> List[Dict[str, Any]]:
    """
    Attempts to automatically transition the contact through flow steps
    (e.g., action -> condition -> action) without requiring user input.
    """
    accumulated_actions = []
    max_auto_transitions = 10 # Limit to prevent infinite loops
    transitions_count = 0

    logger.debug(f"Attempting automatic transitions for contact {contact.whatsapp_id} (ID: {contact.id}), starting from step '{contact_flow_state.current_step.name}'.")

    while transitions_count < max_auto_transitions:
        current_step = contact_flow_state.current_step
        flow_context = contact_flow_state.flow_context_data if isinstance(contact_flow_state.flow_context_data, dict) else {}

        logger.debug(f"Auto-transition loop iter {transitions_count + 1}. Contact {contact.whatsapp_id}, Step '{current_step.name}' (ID: {current_step.id}).")

        # If the current step is a question and it's actively awaiting a reply, stop auto-transitions
        if current_step.step_type == 'question':
            question_expectation = flow_context.get('_question_awaiting_reply_for')
            if isinstance(question_expectation, dict) and question_expectation.get('original_question_step_id') == current_step.id:
                logger.info(f"Step '{current_step.name}' is a question actively awaiting reply. Halting automatic transitions for contact {contact.whatsapp_id}.")
                break
        
        # Get all transitions from the current step
        transitions = FlowTransition.objects.filter(current_step=current_step).select_related('next_step').order_by('priority')
        if not transitions.exists():
            logger.debug(f"No outgoing transitions defined for step '{current_step.name}'. Stopping automatic transitions.")
            break # No more transitions from this step
            
        next_step_to_transition_to = None
        chosen_transition_info = "None"

        # Evaluate transitions for an automatic check (i.e., no new user message data)
        for transition in transitions:
            if _evaluate_transition_condition(transition, contact, message_data={}, flow_context=flow_context.copy(), incoming_message_obj=None):
                next_step_to_transition_to = transition.next_step
                chosen_transition_info = f"ID {transition.id} (Priority {transition.priority})"
                logger.info(f"Automatic transition condition met: {chosen_transition_info}. From '{current_step.name}' to '{next_step_to_transition_to.name}'.")
                break # Found a matching transition
        
        if next_step_to_transition_to:
            # Transition to the next step and execute its actions
            actions_from_transitioned_step, updated_context_after_new_step = _transition_to_step(
                contact_flow_state,     
                next_step_to_transition_to,
                flow_context,              
                contact,
                message_data={}              # Pass empty message_data as this is an auto-transition
            )
            accumulated_actions.extend(actions_from_transitioned_step)
            logger.debug(f"Accumulated {len(actions_from_transitioned_step)} actions after auto-transition to '{next_step_to_transition_to.name}'. Total: {len(accumulated_actions)}.")

            # Check if an internal command to clear or switch flow was issued by the new step's actions
            if any(a.get('type') == '_internal_command_clear_flow_state' for a in actions_from_transitioned_step) or \
               any(a.get('type') == '_internal_command_switch_flow' for a in actions_from_transitioned_step):
                logger.info(f"Flow state cleared or switch command issued during auto-transition from '{next_step_to_transition_to.name}'. Stopping further auto-transitions.")
                break
            
            # Refresh the contact_flow_state object from DB, as it might have been modified by actions
            refreshed_state = ContactFlowState.objects.filter(pk=contact_flow_state.pk).first()
            if not refreshed_state:
                logger.info(f"ContactFlowState (pk={contact_flow_state.pk}) was cleared from DB during auto-transition. Stopping.")
                break # State was cleared (e.g., end flow, human handover)
            contact_flow_state = refreshed_state # Update the local reference

            transitions_count += 1 # Increment counter for next iteration
        else:
            logger.debug(f"No automatic transition condition met from step '{current_step.name}'. Stopping automatic transitions.")
            break # No valid auto-transition from this step
            
    if transitions_count >= max_auto_transitions:
        logger.warning(f"Reached max_auto_transitions ({max_auto_transitions}) for contact {contact.whatsapp_id}. Last step attempted: '{contact_flow_state.current_step.name}'.")

    logger.info(f"Finished automatic transition processing for contact {contact.whatsapp_id}. Total {transitions_count} auto-transitions made. {len(accumulated_actions)} actions generated.")
    return accumulated_actions

def _transition_to_step(
    contact_flow_state: ContactFlowState,    
    next_step: FlowStep,    
    context_of_leaving_step: dict,    
    contact: Contact,    
    message_data: dict    # This is the original incoming message, or empty for auto-transitions
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Manages the transition of a contact's flow state to a new step,
    executes actions of the new step, and updates the database.
    """
    previous_step = contact_flow_state.current_step
    logger.info(
        f"Transitioning contact {contact.whatsapp_id} (ID: {contact.id}) from '{previous_step.name}' (ID: {previous_step.id}) "
        f"to '{next_step.name}' (ID: {next_step.id}) in flow '{contact_flow_state.current_flow.name}'."
    )

    # Copy context to pass to the next step's execution
    context_for_next_step = context_of_leaving_step.copy()
    context_for_next_step.pop('_general_invalid_action_count', None) # Reset general invalid counter on successful transition

    # Clean up question-specific context variables if leaving a question step
    if previous_step.step_type == 'question':
        removed_q_key = context_for_next_step.pop('_question_awaiting_reply_for', None)
        removed_f_key = context_for_next_step.pop('_fallback_count', None)
        if removed_q_key or removed_f_key:
            logger.debug(f"Cleared question expectation/fallback count from context after leaving question step '{previous_step.name}'.")
    
    # Execute actions defined for the new step
    actions_from_new_step, context_after_new_step_execution = _execute_step_actions(
        next_step, contact, context_for_next_step
    )
    
    # After executing actions, check if the contact_flow_state object still exists
    # (it might have been deleted by an 'end_flow' or 'human_handover' action)
    current_db_state_for_contact = ContactFlowState.objects.filter(contact=contact).first()

    if current_db_state_for_contact:
        # If the state exists and is the same one we started with for this processing cycle
        if current_db_state_for_contact.pk == contact_flow_state.pk:
            logger.debug(f"Updating original ContactFlowState (pk={contact_flow_state.pk}) for contact {contact.whatsapp_id}.")
            contact_flow_state.current_step = next_step
            contact_flow_state.flow_context_data = context_after_new_step_execution
            contact_flow_state.last_updated_at = timezone.now()
            contact_flow_state.save(update_fields=['current_step', 'flow_context_data', 'last_updated_at'])
            logger.info(f"Contact {contact.whatsapp_id} successfully transitioned to step '{next_step.name}'. Context updated.")
        else:
            # This case means an _internal_command_switch_flow occurred.
            # The contact_flow_state object passed in is stale; we need to update its reference
            # to the new one that was just created/updated by _trigger_new_flow.
            logger.info(f"Contact {contact.whatsapp_id} switched to a new flow. Current state is now pk={current_db_state_for_contact.pk}, step '{current_db_state_for_contact.current_step.name}'. The old state (pk={contact_flow_state.pk}) is no longer primary.")
            # Update the passed-in contact_flow_state object to match the current DB state
            contact_flow_state.id = current_db_state_for_contact.id
            contact_flow_state.pk = current_db_state_for_contact.pk
            contact_flow_state.current_flow = current_db_state_for_contact.current_flow
            contact_flow_state.current_step = current_db_state_for_contact.current_step
            contact_flow_state.flow_context_data = current_db_state_for_contact.flow_context_data
            contact_flow_state.started_at = current_db_state_for_contact.started_at
            contact_flow_state.last_updated_at = current_db_state_for_contact.last_updated_at
            # Assuming 'company' might be a field, check if it exists before trying to copy
            if hasattr(current_db_state_for_contact, 'company') and hasattr(contact_flow_state, 'company'):
                    contact_flow_state.company = current_db_state_for_contact.company
    else:
        logger.info(f"ContactFlowState for contact {contact.whatsapp_id} was cleared during or after execution of step '{next_step.name}'. No state to update.")

    return actions_from_new_step, context_after_new_step_execution


# --- Main Flow Processing Function ---
@transaction.atomic
def process_message_for_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    """
    Main function to process an incoming message for a contact within the context of a flow.
    It orchestrates flow state management, step execution, and action generation.
    """
    actions_to_perform = []
    logger.info(
        f"Processing message for flow. Contact: {contact.whatsapp_id} (ID: {contact.id}), "
        f"Message Type: {message_data.get('type')}, "
        f"Message WAMID: {incoming_message_obj.wamid if incoming_message_obj and hasattr(incoming_message_obj, 'wamid') else 'N/A'}."
    )

    try:
        # Acquire a lock on the ContactFlowState to prevent race conditions
        contact_flow_state_qs = ContactFlowState.objects.select_for_update().select_related(
            'current_flow', 'current_step'
        )
        contact_flow_state = contact_flow_state_qs.get(contact=contact)
        
        flow_name = contact_flow_state.current_flow.name if contact_flow_state.current_flow else "N/A"
        step_name = contact_flow_state.current_step.name if contact_flow_state.current_step else "N/A"
        flow_id = contact_flow_state.current_flow.id if contact_flow_state.current_flow else "N/A"
        step_id = contact_flow_state.current_step.id if contact_flow_state.current_step else "N/A"
        
        logger.info(
            f"Contact {contact.whatsapp_id} is currently in flow '{flow_name}' (ID: {flow_id}), "
            f"step '{step_name}' (ID: {step_id})."
        )
        actions_to_perform = _handle_active_flow_step(
            contact_flow_state, contact, message_data, incoming_message_obj
        )
    except ContactFlowState.DoesNotExist:
        logger.info(f"No active flow state for contact {contact.whatsapp_id} (ID: {contact.id}). Attempting to trigger a new flow.")
        actions_to_perform = _trigger_new_flow(contact, message_data, incoming_message_obj)
    except Exception as e:
        logger.error(
            f"CRITICAL error in process_message_for_flow for contact {contact.whatsapp_id} (Message WAMID: {incoming_message_obj.wamid if incoming_message_obj and hasattr(incoming_message_obj, 'wamid') else 'N/A'}): {e}",    
            exc_info=True
        )
        # Clear flow state on critical error to prevent infinite loops and provide fallback message
        _clear_contact_flow_state(contact, error=True, reason=f"Critical error in process_message_for_flow: {str(e)[:100]}")
        actions_to_perform = [{
            'type': 'send_whatsapp_message',
            'recipient_wa_id': contact.whatsapp_id,
            'message_type': 'text',
            'data': {'body': 'I encountered an unexpected issue. Please try again in a moment. If the problem persists, contact support.'}
        }]
        return actions_to_perform
        
    # --- Post-processing: Handle internal commands and automatic transitions ---
    # After initial handling of the message (or new flow trigger),
    # check for any pending auto-transitions or internal commands like flow clearing/switching.
    
    current_contact_flow_state_after_initial_handling = ContactFlowState.objects.filter(contact=contact).first()
    
    if current_contact_flow_state_after_initial_handling:
        is_waiting_for_reply_from_current_step = False
        current_step = current_contact_flow_state_after_initial_handling.current_step
        current_context = current_contact_flow_state_after_initial_handling.flow_context_data if isinstance(current_contact_flow_state_after_initial_handling.flow_context_data, dict) else {}

        # Determine if the current step is a question still awaiting a valid reply
        if current_step and current_step.step_type == 'question':
            question_expectation = current_context.get('_question_awaiting_reply_for')
            if isinstance(question_expectation, dict) and question_expectation.get('original_question_step_id') == current_step.id:
                is_waiting_for_reply_from_current_step = True
                logger.debug(f"Contact {contact.whatsapp_id}: Current step '{current_step.name}' is a question still awaiting reply. No auto-transitions will be processed now.")
        elif not current_step:
            logger.warning(f"Contact {contact.whatsapp_id}: ContactFlowState (pk={current_contact_flow_state_after_initial_handling.pk}) has no current_step after initial handling. Cannot process auto-transitions.")

        # Only attempt automatic transitions if not waiting for a specific reply and no flow clear/switch command was issued
        if not is_waiting_for_reply_from_current_step and \
           current_step is not None and \
           not any(a.get('type') == '_internal_command_clear_flow_state' for a in actions_to_perform) and \
           not any(a.get('type') == '_internal_command_switch_flow' for a in actions_to_perform):
            
            logger.info(f"Contact {contact.whatsapp_id}: Checking for automatic transitions from step '{current_step.name}'.")
            additional_auto_actions = _process_automatic_transitions(current_contact_flow_state_after_initial_handling, contact)
            if additional_auto_actions:
                logger.info(f"Contact {contact.whatsapp_id}: Appending {len(additional_auto_actions)} actions from automatic transitions.")
                actions_to_perform.extend(additional_auto_actions)
        elif current_step is not None:
            logger.debug(f"Contact {contact.whatsapp_id}: Skipping automatic transitions from step '{current_step.name}'. Waiting for reply: {is_waiting_for_reply_from_current_step}, Flow Clear/Switch commanded: {any(a.get('type') in ['_internal_command_clear_flow_state', '_internal_command_switch_flow'] for a in actions_to_perform)}")

    else:
        logger.info(f"Contact {contact.whatsapp_id}: No active flow state after initial processing/trigger. No automatic transitions to run.")
            
    # Final filter: Process internal commands that alter flow state (clear/switch)
    # These must be handled last as they affect the database state for future turns.
    final_actions_for_meta_view = []
    processed_switch_command = False
    
    # Iterate over a copy of actions_to_perform as it might be modified
    temp_actions_to_process = list(actions_to_perform)

    for action_idx, action in enumerate(temp_actions_to_process):
        # If a switch command was processed, only allow subsequent send_whatsapp_message actions
        # (which would typically be the welcome message from the new flow's entry point)
        if processed_switch_command and action.get('type') != 'send_whatsapp_message':
            logger.debug(f"Skipping action (index {action_idx}, type {action.get('type')}) after flow switch already processed for contact {contact.whatsapp_id}.")
            continue

        action_type = action.get('type')
        logger.debug(f"Final processing action {action_idx + 1}/{len(temp_actions_to_process)}: Type '{action_type}' for contact {contact.whatsapp_id}. Action detail: {str(action)[:150]}")

        if action_type == '_internal_command_clear_flow_state':
            # This is where the actual DB operation for clearing state happens
            _clear_contact_flow_state(contact, reason=action.get('reason', 'N/A'))
            logger.info(f"Internal command: Flow state clearance for contact {contact.whatsapp_id} executed.")
        
        elif action_type == '_internal_command_switch_flow':
            if processed_switch_command:
                logger.warning(f"Contact {contact.whatsapp_id}: Multiple switch flow commands. Redundant one (index {action_idx}) skipped.")
                continue

            target_flow_name = action.get('target_flow_name')
            logger.info(f"Processing internal command to switch flow for contact {contact.whatsapp_id} to '{target_flow_name}'.")
            
            # Clear current state first (ensures clean slate for new flow)
            _clear_contact_flow_state(contact, reason=f"Switching to flow {target_flow_name}")

            initial_context_for_new_flow = action.get('initial_context', {})
            new_flow_trigger_msg_body = action.get('new_flow_trigger_message_body')
            
            # Simulate an incoming message to trigger the new flow using _trigger_new_flow
            synthetic_message_data = {
                'type': 'text',
                'text': {'body': new_flow_trigger_msg_body or f"__internal_trigger_{target_flow_name}"} # Use a unique internal trigger string
            }
            
            switched_flow_actions = _trigger_new_flow(contact, synthetic_message_data, incoming_message_obj)
            
            # After _trigger_new_flow, if a new state was created, update its context
            newly_created_state_after_switch = ContactFlowState.objects.filter(contact=contact).first()
            if newly_created_state_after_switch and initial_context_for_new_flow and isinstance(initial_context_for_new_flow, dict):
                logger.debug(f"Applying initial context to newly switched flow state (pk={newly_created_state_after_switch.pk}). Current context: {newly_created_state_after_switch.flow_context_data}, Initial to apply: {initial_context_for_new_flow}")
                if not isinstance(newly_created_state_after_switch.flow_context_data, dict):
                    newly_created_state_after_switch.flow_context_data = {} # Ensure it's a dict
                newly_created_state_after_switch.flow_context_data.update(initial_context_for_new_flow)
                newly_created_state_after_switch.save(update_fields=['flow_context_data', 'last_updated_at'])
                logger.info(f"Applied initial context to new flow '{target_flow_name}' state for {contact.whatsapp_id}: {initial_context_for_new_flow}")
            
            # Only send message actions from the newly triggered flow's entry point
            final_actions_for_meta_view = [act for act in switched_flow_actions if act.get('type') == 'send_whatsapp_message']
            processed_switch_command = True # Mark that a switch occurred
            logger.info(f"Flow switch for {contact.whatsapp_id} to '{target_flow_name}' completed. Actions from new flow's entry point to be sent: {len(final_actions_for_meta_view)}")
            break # Exit the loop, only these actions will be returned

        elif action_type == 'send_whatsapp_message':
            # Add send messages to the final list, unless a switch command was processed AND this message
            # wasn't part of the new flow's entry point actions (to avoid sending old messages after a switch)
            if not processed_switch_command:
                final_actions_for_meta_view.append(action)
            
        else:
            logger.warning(f"Unhandled action type '{action_type}' encountered during final action processing for contact {contact.whatsapp_id}. Action: {action}")
            
    logger.info(f"Finished processing message for contact {contact.whatsapp_id} (ID: {contact.id}). Total {len(final_actions_for_meta_view)} actions to be sent to meta_integration.")
    if final_actions_for_meta_view:
        logger.debug(f"Final actions for {contact.whatsapp_id} (ID: {contact.id}): {json.dumps(final_actions_for_meta_view, indent=2)}")
    return final_actions_for_meta_view