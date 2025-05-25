# whatsappcrm_backend/flows/services.py

import logging
import json
import re
from typing import List, Dict, Any, Optional, Union, Literal # For Pydantic type hinting

from django.utils import timezone
from django.db import transaction
from pydantic import BaseModel, ValidationError, field_validator, root_validator, Field

from conversations.models import Contact, Message
from .models import Flow, FlowStep, FlowTransition, ContactFlowState
from customer_data.models import CustomerProfile # Make sure this import is correct
try:
    from media_manager.models import MediaAsset # For asset_pk lookup
    MEDIA_ASSET_ENABLED = True
except ImportError:
    MEDIA_ASSET_ENABLED = False

logger = logging.getLogger(__name__)

if not MEDIA_ASSET_ENABLED:
    logger.warning("MediaAsset model not found or could not be imported. MediaAsset functionality (e.g., 'asset_pk') will be disabled in flows.")

class BasePydanticConfig(BaseModel):
    class Config:
        extra = 'allow'

class TextMessageContent(BasePydanticConfig):
    body: str = Field(..., min_length=1, max_length=4096)
    preview_url: bool = False

class MediaMessageContent(BasePydanticConfig):
    asset_pk: Optional[int] = None
    id: Optional[str] = None
    link: Optional[str] = None
    caption: Optional[str] = Field(default=None, max_length=1024)
    filename: Optional[str] = None

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
    action: Union[InteractiveButtonAction, InteractiveListAction]

class TemplateLanguage(BasePydanticConfig):
    code: str

class TemplateParameter(BasePydanticConfig):
    type: Literal["text", "currency", "date_time", "image", "document", "video", "payload"]
    text: Optional[str] = None
    currency: Optional[Dict[str, Any]] = None
    date_time: Optional[Dict[str, Any]] = None
    image: Optional[Dict[str, Any]] = None
    document: Optional[Dict[str, Any]] = None
    video: Optional[Dict[str, Any]] = None
    payload: Optional[str] = None

class TemplateComponent(BasePydanticConfig):
    type: Literal["header", "body", "button"]
    sub_type: Optional[Literal['url', 'quick_reply', 'call_button', 'catalog_button', 'mpm_button']] = None
    parameters: Optional[List[TemplateParameter]] = None
    index: Optional[int] = None

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
    addresses: Optional[List[ContactAddress]] = None
    birthday: Optional[str] = None
    emails: Optional[List[ContactEmail]] = None
    name: ContactName
    org: Optional[ContactOrg] = None
    phones: Optional[List[ContactPhone]] = None
    urls: Optional[List[ContactUrl]] = None

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
                raise ValueError(f"Payload for message_type '{msg_type}' is missing or null.")
        if msg_type == 'interactive':
                interactive_payload = values.get('interactive')
                if not interactive_payload or not getattr(interactive_payload, 'type', None):
                    raise ValueError("For 'interactive' messages, the 'interactive' payload must exist and specify its own 'type' (e.g., 'button', 'list').")
        return values

class ReplyConfig(BasePydanticConfig):
    save_to_variable: str
    expected_type: Literal["text", "email", "number", "interactive_id"]
    validation_regex: Optional[str] = None

class StepConfigQuestion(BasePydanticConfig):
    message_config: Dict[str, Any]
    reply_config: ReplyConfig

    @field_validator('message_config')
    def validate_message_config_structure(cls, v):
        try:
            StepConfigSendMessage.model_validate(v)
            return v
        except ValidationError as e:
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
    actions_to_run: List[ActionItemConfig] = Field(default_factory=list)

class StepConfigHumanHandover(BasePydanticConfig):
    pre_handover_message_text: Optional[str] = None
    notification_details: Optional[str] = None

class StepConfigEndFlow(BasePydanticConfig):
    message_config: Optional[Dict[str, Any]] = None

    @field_validator('message_config')
    def validate_message_config_structure(cls, v):
        if v is None: return None
        try:
            StepConfigSendMessage.model_validate(v)
            return v
        except ValidationError as e:
            raise ValueError(f"message_config for end_flow is invalid: {e.errors()}")

InteractiveMessagePayload.model_rebuild()


def _get_value_from_context_or_contact(variable_path: str, flow_context: dict, contact: Contact) -> Any:
    if not variable_path: return None
    parts = variable_path.split('.')
    current_value = None
    source_object_name = parts[0]

    if source_object_name == 'flow_context':
        current_value = flow_context
        path_to_traverse = parts[1:]
    elif source_object_name == 'contact':
        current_value = contact
        path_to_traverse = parts[1:]
    elif source_object_name == 'customer_profile':
        try:
            current_value = contact.customer_profile 
            path_to_traverse = parts[1:]
        except CustomerProfile.DoesNotExist:
            logger.debug(f"CustomerProfile does not exist for contact {contact.id} when accessing '{variable_path}'")
            return None
        except AttributeError: 
            logger.debug(f"Contact {contact.id} has no customer_profile attribute for '{variable_path}'")
            return None
    else:
        current_value = flow_context
        path_to_traverse = parts

    for i, part in enumerate(path_to_traverse):
        try:
            if isinstance(current_value, dict):
                    current_value = current_value.get(part)
            elif hasattr(current_value, part):
                    attr_or_method = getattr(current_value, part)
                    current_value = attr_or_method() if callable(attr_or_method) and hasattr(attr_or_method, '__code__') and attr_or_method.__code__.co_argcount == 0 else attr_or_method
            else:
                    return None
        except Exception as e:
            logger.warning(f"Error accessing path '{'.'.join(path_to_traverse[:i+1])}' on object for '{variable_path}': {e}")
            return None
        if current_value is None and i < len(path_to_traverse) - 1:
            return None
    return current_value

def _resolve_value(template_value: Any, flow_context: dict, contact: Contact) -> Any:
    if isinstance(template_value, str):
        def replace_match(match):
            var_path = match.group(1).strip()
            val = _get_value_from_context_or_contact(var_path, flow_context, contact)
            return str(val) if val is not None else ''

        resolved_string = template_value
        for _ in range(10):
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
        resolved_components_list = json.loads(json.dumps(components_config))
        for component in resolved_components_list:
            if isinstance(component.get('parameters'), list):
                for param in component['parameters']:
                    if 'text' in param and isinstance(param['text'], str):
                            param['text'] = _resolve_value(param['text'], flow_context, contact)
                    param_type = param.get('type')
                    if param_type in ['image', 'video', 'document'] and isinstance(param.get(param_type), dict):
                            media_obj = param[param_type]
                            if 'link' in media_obj and isinstance(media_obj['link'], str):
                                    media_obj['link'] = _resolve_value(media_obj['link'], flow_context, contact)
                    if component.get('type') == 'button' and param.get('type') == 'payload' and 'payload' in param and isinstance(param['payload'], str):
                            param['payload'] = _resolve_value(param['payload'], flow_context, contact)
                    if param_type == 'currency' and isinstance(param.get('currency'), dict) and 'fallback_value' in param['currency']:
                            param['currency']['fallback_value'] = _resolve_value(param['currency']['fallback_value'], flow_context, contact)
                    if param_type == 'date_time' and isinstance(param.get('date_time'), dict) and 'fallback_value' in param['date_time']:
                            param['date_time']['fallback_value'] = _resolve_value(param['date_time']['fallback_value'], flow_context, contact)
        return resolved_components_list
    except Exception as e:
        logger.error(f"Error resolving template components: {e}. Config: {components_config}", exc_info=True)
        return components_config

def _clear_contact_flow_state(contact: Contact, error: bool = False):
    deleted_count, _ = ContactFlowState.objects.filter(contact=contact).delete()
    if deleted_count > 0:
        logger.info(f"Cleared flow state for contact {contact.whatsapp_id}." + (" Due to an error." if error else ""))

def _execute_step_actions(step: FlowStep, contact: Contact, flow_context: dict, is_re_execution: bool = False) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    actions_to_perform = []
    raw_step_config = step.config or {}
    current_step_context = flow_context.copy()

    logger.debug(
        f"Executing actions for step '{step.name}' (type: {step.step_type}) "
        f"for contact {contact.whatsapp_id}. Raw Config: {raw_step_config}"
    )

    if step.step_type == 'send_message':
        try:
            send_message_config = StepConfigSendMessage.model_validate(raw_step_config)
            actual_message_type = send_message_config.message_type
            final_api_data_structure = {}

            if actual_message_type == "text" and send_message_config.text:
                text_content = send_message_config.text
                resolved_body = _resolve_value(text_content.body, current_step_context, contact)
                final_api_data_structure = {'body': resolved_body, 'preview_url': text_content.preview_url}

            elif actual_message_type in ['image', 'document', 'audio', 'video', 'sticker'] and getattr(send_message_config, actual_message_type):
                media_conf: MediaMessageContent = getattr(send_message_config, actual_message_type)
                media_data_to_send = {}
                valid_source_found = False
                if MEDIA_ASSET_ENABLED and media_conf.asset_pk:
                    try:
                        asset = MediaAsset.objects.get(pk=media_conf.asset_pk)
                        if asset.status == 'synced' and asset.whatsapp_media_id and not asset.is_whatsapp_id_potentially_expired():
                            media_data_to_send['id'] = asset.whatsapp_media_id
                            valid_source_found = True
                            logger.info(f"Using MediaAsset {asset.pk} ('{asset.name}') with WA ID: {asset.whatsapp_media_id}")
                        else:
                            logger.warning(f"MediaAsset {asset.pk} ('{asset.name}') not usable (Status: {asset.status}, Expired: {asset.is_whatsapp_id_potentially_expired()}). Trying direct id/link from config.")
                    except MediaAsset.DoesNotExist:
                        logger.error(f"MediaAsset pk={media_conf.asset_pk} not found. Trying direct id/link from config.")
                if not valid_source_found:
                    if media_conf.id:
                        media_data_to_send['id'] = _resolve_value(media_conf.id, current_step_context, contact)
                        valid_source_found = True
                    elif media_conf.link:
                        media_data_to_send['link'] = _resolve_value(media_conf.link, current_step_context, contact)
                        valid_source_found = True
                if not valid_source_found:
                    logger.error(f"No valid media source (asset_pk, id, or link) for {actual_message_type} in step '{step.name}'.")
                else:
                    if media_conf.caption:
                        media_data_to_send['caption'] = _resolve_value(media_conf.caption, current_step_context, contact)
                    if actual_message_type == 'document' and media_conf.filename:
                        media_data_to_send['filename'] = _resolve_value(media_conf.filename, current_step_context, contact)
                    final_api_data_structure = {actual_message_type: media_data_to_send}

            elif actual_message_type == "interactive" and send_message_config.interactive:
                interactive_payload_validated = send_message_config.interactive
                interactive_payload_dict = interactive_payload_validated.model_dump(exclude_none=True, by_alias=True)
                resolved_interactive_str = _resolve_value(json.dumps(interactive_payload_dict), current_step_context, contact)
                final_api_data_structure = json.loads(resolved_interactive_str)

            elif actual_message_type == "template" and send_message_config.template:
                template_payload_validated = send_message_config.template
                template_payload_dict = template_payload_validated.model_dump(exclude_none=True, by_alias=True)
                if 'components' in template_payload_dict and template_payload_dict['components']:
                    template_payload_dict['components'] = _resolve_template_components(
                        template_payload_dict['components'], current_step_context, contact
                    )
                final_api_data_structure = template_payload_dict

            elif actual_message_type == "contacts" and send_message_config.contacts:
                contacts_list_of_objects = send_message_config.contacts
                contacts_list_of_dicts = [c.model_dump(exclude_none=True, by_alias=True) for c in contacts_list_of_objects]
                resolved_contacts = _resolve_value(contacts_list_of_dicts, current_step_context, contact)
                final_api_data_structure = {"contacts": resolved_contacts}

            elif actual_message_type == "location" and send_message_config.location:
                location_obj = send_message_config.location
                location_dict = location_obj.model_dump(exclude_none=True, by_alias=True)
                final_api_data_structure = {"location": _resolve_value(location_dict, current_step_context, contact)}

            if final_api_data_structure:
                actions_to_perform.append({
                    'type': 'send_whatsapp_message',
                    'recipient_wa_id': contact.whatsapp_id,
                    'message_type': actual_message_type,
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
            question_config = StepConfigQuestion.model_validate(raw_step_config)
            if question_config.message_config and not is_re_execution:
                try:
                    temp_msg_pydantic_config = StepConfigSendMessage.model_validate(question_config.message_config)
                    dummy_send_step = FlowStep(name=f"{step.name}_prompt", step_type="send_message", config=temp_msg_pydantic_config.model_dump())
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
            action_step_config = StepConfigAction.model_validate(raw_step_config)
            for action_item_conf in action_step_config.actions_to_run:
                action_type = action_item_conf.action_type
                if action_type == 'set_context_variable' and action_item_conf.variable_name is not None:
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    current_step_context[action_item_conf.variable_name] = resolved_value
                    logger.info(f"Action: Set context var '{action_item_conf.variable_name}' to '{resolved_value}'.")
                elif action_type == 'update_contact_field' and action_item_conf.field_path is not None:
                    resolved_value = _resolve_value(action_item_conf.value_template, current_step_context, contact)
                    _update_contact_data(contact, action_item_conf.field_path, resolved_value)
                elif action_type == 'update_customer_profile' and action_item_conf.fields_to_update is not None:
                    resolved_fields_to_update = _resolve_value(action_item_conf.fields_to_update, current_step_context, contact)
                    _update_customer_profile_data(contact, resolved_fields_to_update, current_step_context)
                elif action_type == 'switch_flow' and action_item_conf.target_flow_name is not None:
                    resolved_initial_context = _resolve_value(action_item_conf.initial_context_template or {}, current_step_context, contact)
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
                    logger.warning(f"Unknown or misconfigured action_type '{action_type}' in step '{step.name}'.")
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'action' step '{step.name}' failed: {e.errors()}", exc_info=False)

    elif step.step_type == 'end_flow':
        try:
            end_flow_config = StepConfigEndFlow.model_validate(raw_step_config)
            if end_flow_config.message_config:
                try:
                    final_msg_pydantic_config = StepConfigSendMessage.model_validate(end_flow_config.message_config)
                    dummy_end_msg_step = FlowStep(name=f"{step.name}_final_msg", step_type="send_message", config=final_msg_pydantic_config.model_dump())
                    send_actions, _ = _execute_step_actions(dummy_end_msg_step, contact, current_step_context)
                    actions_to_perform.extend(send_actions)
                except ValidationError as ve:
                        logger.error(f"Pydantic validation for 'message_config' in 'end_flow' step '{step.name}': {ve.errors()}", exc_info=False)
            logger.info(f"Executing 'end_flow' step '{step.name}'.")
            actions_to_perform.append({'type': '_internal_command_clear_flow_state'})
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'end_flow' step '{step.name}' config: {e.errors()}", exc_info=False)

    elif step.step_type == 'human_handover':
        try:
            handover_config = StepConfigHumanHandover.model_validate(raw_step_config)
            logger.info(f"Executing 'human_handover' step '{step.name}'.")
            if handover_config.pre_handover_message_text and not is_re_execution:
                resolved_msg = _resolve_value(handover_config.pre_handover_message_text, current_step_context, contact)
                actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_msg}})
            contact.needs_human_intervention = True
            contact.intervention_requested_at = timezone.now()
            contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
            logger.info(f"Contact {contact.whatsapp_id} flagged for human intervention.")
            notification_info = _resolve_value(handover_config.notification_details or f"Contact {contact.name or contact.whatsapp_id} requires help.", current_step_context, contact)
            logger.info(f"HUMAN INTERVENTION NOTIFICATION: {notification_info}. Context: {current_step_context}")
            actions_to_perform.append({'type': '_internal_command_clear_flow_state'})
        except ValidationError as e:
            logger.error(f"Pydantic validation for 'human_handover' step '{step.name}' failed: {e.errors()}", exc_info=False)

    elif step.step_type in ['condition', 'wait_for_reply', 'start_flow_node']:
        logger.debug(f"'{step.step_type}' step '{step.name}' processed. No direct actions from this function, logic handled by transitions or flow control.")
    else:
        logger.warning(f"Unhandled step_type: '{step.step_type}' for step '{step.name}'.")

    return actions_to_perform, current_step_context


def _handle_active_flow_step(contact_flow_state: ContactFlowState, contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    current_step = contact_flow_state.current_step
    flow_context = contact_flow_state.flow_context_data if contact_flow_state.flow_context_data is not None else {}
    actions_to_perform = []

    logger.debug(f"Handling active flow. Contact: {contact.whatsapp_id}, Current Step: '{current_step.name}' (Type: {current_step.step_type}). Context: {flow_context}")

    if current_step.step_type == 'question' and '_question_awaiting_reply_for' in flow_context:
        question_expectation = flow_context['_question_awaiting_reply_for']
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
        reply_is_valid = False
        value_to_save = None
        if expected_reply_type == 'text' and user_text: # An empty string for user_text will make this false
            value_to_save = user_text; reply_is_valid = True
        elif expected_reply_type == 'email':
            email_r = validation_regex_ctx or r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if user_text and re.match(email_r, user_text):
                value_to_save = user_text; reply_is_valid = True
        elif expected_reply_type == 'number' and user_text:
            try:
                value_to_save = float(user_text) if '.' in user_text or (validation_regex_ctx and '.' in validation_regex_ctx) else int(user_text)
                reply_is_valid = True
                if validation_regex_ctx and not re.match(validation_regex_ctx, str(value_to_save)):
                    reply_is_valid = False; value_to_save = None
            except ValueError: pass
        elif expected_reply_type == 'interactive_id' and interactive_reply_id:
            value_to_save = interactive_reply_id; reply_is_valid = True
        
        if validation_regex_ctx and not reply_is_valid and user_text and expected_reply_type == 'text':
            if re.match(validation_regex_ctx, user_text):
                value_to_save = user_text; reply_is_valid = True
        
        if reply_is_valid and variable_to_save_name:
            flow_context[variable_to_save_name] = value_to_save
            logger.info(f"Saved valid reply for '{variable_to_save_name}' in question step '{current_step.name}': {value_to_save}")
            # Premature pop calls were removed here. Clearing is handled by _transition_to_step or specific fallbacks.
        else:
            logger.info(f"Reply for question step '{current_step.name}' was not valid or no variable to save. Expected: {expected_reply_type}, Received text: '{user_text}', Interactive ID: '{interactive_reply_id}'")

    transitions = FlowTransition.objects.filter(current_step=current_step).select_related('next_step').order_by('priority')
    next_step_to_transition_to = None
    for transition in transitions:
        if _evaluate_transition_condition(transition, contact, message_data, flow_context, incoming_message_obj):
            next_step_to_transition_to = transition.next_step
            logger.info(f"Transition condition met: From '{current_step.name}' to '{next_step_to_transition_to.name}'.")
            break
            
    if next_step_to_transition_to:
        actions, _ = _transition_to_step(
            contact_flow_state, next_step_to_transition_to, flow_context, contact, message_data
        )
        actions_to_perform.extend(actions)
    else: # No transition condition met - Fallback logic
        fallback_config = current_step.config.get('fallback_config', {}) if isinstance(current_step.config, dict) else {}
        max_fallbacks = fallback_config.get('max_retries', 1) 
        current_fallback_count = flow_context.get('_fallback_count', 0)

        if current_step.step_type == 'question' and \
            fallback_config.get('action') == 're_prompt' and \
            current_fallback_count < max_fallbacks:
            logger.info(f"Re-prompting question step '{current_step.name}' (Attempt {current_fallback_count + 1}/{max_fallbacks}).")
            flow_context['_fallback_count'] = current_fallback_count + 1
            re_prompt_message_text = fallback_config.get('re_prompt_message_text')
            if re_prompt_message_text:
                resolved_re_prompt_text = _resolve_value(re_prompt_message_text, flow_context, contact)
                actions_to_perform.append({
                    'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                    'message_type': 'text', 'data': {'body': resolved_re_prompt_text}
                })
            else:
                step_actions, updated_context = _execute_step_actions(current_step, contact, flow_context.copy(), is_re_execution=True)
                actions_to_perform.extend(step_actions)
                flow_context = updated_context 
            
            # Save the updated context (with incremented fallback_count)
            # This is important so the re-prompt doesn't reset _question_awaiting_reply_for if it was re-set by _execute_step_actions
            contact_flow_state.flow_context_data = flow_context
            contact_flow_state.save(update_fields=['flow_context_data', 'last_updated_at'])

        elif fallback_config.get('fallback_message_text'):
            resolved_fallback_text = _resolve_value(fallback_config['fallback_message_text'], flow_context, contact)
            actions_to_perform.append({
                'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                'message_type': 'text', 'data': {'body': resolved_fallback_text}
            })
            if fallback_config.get('handover_after_message', False) or \
                (current_step.step_type == 'question' and current_fallback_count >= max_fallbacks): # Also handover if max retries for a question are done
                logger.info(f"Fallback: Initiating human handover after fallback message or max retries for {contact.whatsapp_id}.")
                # _clear_contact_flow_state(contact) # This will be handled by the internal command
                actions_to_perform.append({'type': '_internal_command_clear_flow_state'})
                contact.needs_human_intervention = True
                contact.intervention_requested_at = timezone.now()
                contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
        
        elif fallback_config.get('action') == 'human_handover' or \
                (current_step.step_type == 'question' and current_fallback_count >= max_fallbacks and not fallback_config.get('fallback_message_text') ): # Only if no specific fallback message was sent for max_retries
            logger.info(f"Fallback: Initiating human handover directly or after max retries (no specific fallback message) for {contact.whatsapp_id}.")
            pre_handover_msg = fallback_config.get('pre_handover_message_text', "I'm having a bit of trouble understanding. Let me connect you to a human agent for assistance.")
            resolved_msg = _resolve_value(pre_handover_msg, flow_context, contact)
            actions_to_perform.append({'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id, 'message_type': 'text', 'data': {'body': resolved_msg}})
            # _clear_contact_flow_state(contact) # This will be handled by the internal command
            actions_to_perform.append({'type': '_internal_command_clear_flow_state'})
            contact.needs_human_intervention = True
            contact.intervention_requested_at = timezone.now()
            contact.save(update_fields=['needs_human_intervention', 'intervention_requested_at'])
        else:
            logger.info(f"No transition met for step '{current_step.name}' and no specific fallback action configured or applicable for {contact.whatsapp_id}.")
            if not actions_to_perform: 
                actions_to_perform.append({
                    'type': 'send_whatsapp_message', 'recipient_wa_id': contact.whatsapp_id,
                    'message_type': 'text', 'data': {'body': "Sorry, I'm not sure how to proceed with that. Can you try something else?"}
                })
    return actions_to_perform

def _trigger_new_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    actions_to_perform = []
    initial_flow_context = {}
    message_text_body = None
    if message_data.get('type') == 'text':
        message_text_body = message_data.get('text', {}).get('body', '').lower().strip()
    triggered_flow = None
    active_flows = Flow.objects.filter(is_active=True).order_by('name')
    if message_text_body:
        for flow_candidate in active_flows:
            if isinstance(flow_candidate.trigger_keywords, list):
                for keyword in flow_candidate.trigger_keywords:
                    if isinstance(keyword, str) and keyword.strip() and keyword.strip().lower() in message_text_body:
                        triggered_flow = flow_candidate
                        logger.info(f"Keyword '{keyword}' triggered flow '{flow_candidate.name}' for contact {contact.whatsapp_id}.")
                        break
            if triggered_flow:
                break
    if triggered_flow:
        entry_point_step = FlowStep.objects.filter(flow=triggered_flow, is_entry_point=True).first()
        if entry_point_step:
            logger.info(f"Starting flow '{triggered_flow.name}' for contact {contact.whatsapp_id} at entry step '{entry_point_step.name}'.")
            _clear_contact_flow_state(contact)
            contact_flow_state = ContactFlowState.objects.create(
                contact=contact,
                current_flow=triggered_flow,
                current_step=entry_point_step,
                flow_context_data=initial_flow_context,
                started_at=timezone.now()
            )
            step_actions, updated_flow_context = _execute_step_actions(entry_point_step, contact, initial_flow_context.copy())
            actions_to_perform.extend(step_actions)
            
            # Save context if it changed and state still exists (wasn't cleared by step_actions)
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

def _evaluate_transition_condition(transition: FlowTransition, contact: Contact, message_data: dict, flow_context: dict, incoming_message_obj: Message) -> bool:
    config = transition.condition_config
    if not isinstance(config, dict):
        logger.warning(f"Transition {transition.id} has invalid condition_config (not a dict): {config}")
        return False
    condition_type = config.get('type')
    logger.debug(f"Evaluating condition type '{condition_type}' for transition {transition.id} of step '{transition.current_step.name}'. Context: {flow_context}, Message Type: {message_data.get('type')}")

    if not condition_type: return False
    if condition_type == 'always_true': return True

    user_text = ""
    if message_data.get('type') == 'text' and isinstance(message_data.get('text'), dict):
        user_text = message_data.get('text', {}).get('body', '').strip()

    interactive_reply_id = None
    nfm_response_data = None
    if message_data.get('type') == 'interactive' and isinstance(message_data.get('interactive'), dict):
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
                try: nfm_response_data = json.loads(response_json_str)
                except json.JSONDecodeError: logger.warning(f"Could not parse nfm_reply response_json for transition {transition.id}")

    value_for_condition = config.get('value')

    if condition_type == 'user_reply_matches_keyword':
        keyword = str(config.get('keyword', '')).strip()
        if not keyword: return False
        case_sensitive = config.get('case_sensitive', False)
        return (keyword == user_text) if case_sensitive else (keyword.lower() == user_text.lower())
    elif condition_type == 'user_reply_contains_keyword':
        keyword = str(config.get('keyword', '')).strip()
        if not keyword: return False
        case_sensitive = config.get('case_sensitive', False)
        return (keyword in user_text) if case_sensitive else (keyword.lower() in user_text.lower())
    elif condition_type == 'interactive_reply_id_equals':
        return interactive_reply_id is not None and interactive_reply_id == str(value_for_condition)
    elif condition_type == 'message_type_is':
        return message_data.get('type') == str(value_for_condition)
    elif condition_type == 'user_reply_matches_regex':
        regex = config.get('regex')
        if regex and user_text:
            try: return bool(re.match(regex, user_text))
            except re.error as e: logger.error(f"Invalid regex in transition {transition.id}: {regex}. Error: {e}"); return False
        return False
    elif condition_type == 'variable_equals':
        variable_name = config.get('variable_name')
        if variable_name is None: return False
        actual_value = _get_value_from_context_or_contact(variable_name, flow_context, contact)
        expected_value_str = str(value_for_condition)
        actual_value_str = str(actual_value)
        return actual_value_str == expected_value_str
    elif condition_type == 'variable_exists':
        variable_name = config.get('variable_name')
        if variable_name is None: return False
        return _get_value_from_context_or_contact(variable_name, flow_context, contact) is not None
    elif condition_type == 'variable_contains':
        variable_name = config.get('variable_name')
        if variable_name is None: return False
        actual_value = _get_value_from_context_or_contact(variable_name, flow_context, contact)
        expected_item = value_for_condition
        if isinstance(actual_value, str) and isinstance(expected_item, str): return expected_item in actual_value
        if isinstance(actual_value, list) and expected_item is not None: return expected_item in actual_value
        return False
    elif condition_type == 'nfm_response_field_equals' and nfm_response_data:
        field_path = config.get('field_path')
        if not field_path: return False
        actual_val_from_nfm = nfm_response_data
        for part in field_path.split('.'):
            if isinstance(actual_val_from_nfm, dict): actual_val_from_nfm = actual_val_from_nfm.get(part)
            else: actual_val_from_nfm = None; break
        return actual_val_from_nfm == value_for_condition
    elif condition_type == 'question_reply_is_valid':
        question_expectation = flow_context.get('_question_awaiting_reply_for')
        if question_expectation and isinstance(question_expectation, dict):
            var_name = question_expectation.get('variable_name')
            is_var_set_and_not_none = var_name in flow_context and flow_context.get(var_name) is not None
            return is_var_set_and_not_none if value_for_condition is True else not is_var_set_and_not_none
        return False
    elif condition_type == 'user_requests_human':
        human_request_keywords = config.get('keywords', ['help', 'support', 'agent', 'human', 'operator'])
        if user_text and isinstance(human_request_keywords, list):
            user_text_lower = user_text.lower()
            for keyword in human_request_keywords:
                if isinstance(keyword, str) and keyword.strip() and keyword.strip().lower() in user_text_lower:
                    logger.info(f"User requested human agent with keyword: '{keyword}'")
                    return True
        return False
    elif condition_type == 'user_reply_received':
        if message_data and message_data.get('type'):
            logger.info(f"Condition 'user_reply_received' met for contact {contact.whatsapp_id} as a message of type '{message_data.get('type')}' was received.")
            return True
        logger.debug(f"Condition 'user_reply_received' not met for contact {contact.whatsapp_id} (no valid message_data or message type).")
        return False
    logger.warning(f"Unknown or unhandled condition type: '{condition_type}' for transition {transition.id} or condition logic not met.")
    return False

def _transition_to_step(contact_flow_state: ContactFlowState, next_step: FlowStep, current_flow_context: dict, contact: Contact, message_data: dict) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    previous_step_name = contact_flow_state.current_step.name # For logging
    logger.info(f"Transitioning contact {contact.whatsapp_id} from '{previous_step_name}' to '{next_step.name}' in flow '{contact_flow_state.current_flow.name}'.")

    # 1. Clear question-specific context from the *previous* step's context if it was a question
    if contact_flow_state.current_step.step_type == 'question':
        current_flow_context.pop('_question_awaiting_reply_for', None)
        current_flow_context.pop('_fallback_count', None)
        logger.debug(f"Cleared question expectation and fallback count from previous step '{previous_step_name}'.")

    # 2. Execute actions for the new step (next_step)
    # Pass a copy of the (potentially cleaned) current_flow_context for the new step to use and modify.
    actions_from_new_step, context_after_new_step_execution = _execute_step_actions(
        next_step, contact, current_flow_context.copy()
    )

    # 3. After executing actions of the new step, check if the flow state record still exists and is the same one.
    # It might have been cleared (end_flow, human_handover) or replaced (switch_flow) by actions in 'next_step'.
    current_db_state_after_actions = ContactFlowState.objects.filter(contact=contact, pk=contact_flow_state.pk).first()

    if current_db_state_after_actions:
        # The state record still exists and is the one we were working with.
        # Update it to reflect the new current_step and its resulting context.
        current_db_state_after_actions.current_step = next_step
        current_db_state_after_actions.flow_context_data = context_after_new_step_execution
        current_db_state_after_actions.last_updated_at = timezone.now() 
        current_db_state_after_actions.save(update_fields=['current_step', 'flow_context_data', 'last_updated_at'])
        logger.debug(f"Saved ContactFlowState: contact {contact.whatsapp_id} is now at step '{next_step.name}' with context {context_after_new_step_execution}.")
    
    # Check if a switch_flow command was issued, which might have created a new state record
    elif any(action.get('type') == '_internal_command_switch_flow' for action in actions_from_new_step):
        # If a switch_flow happened, the new state is handled by that command's processing in process_message_for_flow
        logger.info(f"A switch_flow command was processed during execution of step '{next_step.name}'. Original state (pk={contact_flow_state.pk}) might be invalid or cleared.")
        # It's possible the original contact_flow_state.pk is now gone due to _clear_contact_flow_state in _internal_command_switch_flow
        # and a new state record exists. The main process_message_for_flow handles this.
    
    elif not ContactFlowState.objects.filter(contact=contact).exists(): # No state record exists for the contact
        logger.info(f"ContactFlowState for contact {contact.whatsapp_id} was cleared during execution of step '{next_step.name}'. No state to update.")
        
    return actions_from_new_step, context_after_new_step_execution


def _update_contact_data(contact: Contact, field_path: str, value_to_set: Any):
    if not field_path:
        logger.warning("Empty field_path provided for _update_contact_data.")
        return
    parts = field_path.split('.')
    if len(parts) == 1:
        field_name = parts[0]
        if field_name.lower() in ['id', 'pk', 'whatsapp_id']:
            logger.warning(f"Attempt to update protected Contact field '{field_name}' denied.")
            return
        if hasattr(contact, field_name):
            setattr(contact, field_name, value_to_set)
            contact.save(update_fields=[field_name])
            logger.info(f"Updated Contact {contact.whatsapp_id} field '{field_name}' to '{value_to_set}'.")
        else:
            logger.warning(f"Contact field '{field_name}' not found.")
    elif parts[0] == 'custom_fields':
        if not hasattr(contact, 'custom_fields') or not isinstance(contact.custom_fields, dict):
            contact.custom_fields = {}
        current_level = contact.custom_fields
        for i, key in enumerate(parts[1:-1]):
            current_level = current_level.setdefault(key, {})
            if not isinstance(current_level, dict):
                logger.error(f"Path error in Contact.custom_fields: '{key}' is not a dict for path '{field_path}'.")
                return
        final_key = parts[-1]
        if len(parts) > 1 :
            current_level[final_key] = value_to_set
            contact.save(update_fields=['custom_fields'])
            logger.info(f"Updated Contact {contact.whatsapp_id} custom_fields path '{'.'.join(parts[1:])}' to '{value_to_set}'.")
        else:
            if isinstance(value_to_set, dict):
                contact.custom_fields = value_to_set
                contact.save(update_fields=['custom_fields'])
                logger.info(f"Replaced Contact {contact.whatsapp_id} custom_fields with: {value_to_set}")
            else:
                logger.warning(f"Cannot replace Contact.custom_fields with a non-dictionary value for path '{field_path}'.")
    else:
        logger.warning(f"Unsupported field path '{field_path}' for updating Contact model.")

def _update_customer_profile_data(contact: Contact, fields_to_update_config: Dict[str, Any], flow_context: dict):
    if not fields_to_update_config or not isinstance(fields_to_update_config, dict):
        logger.warning("_update_customer_profile_data called with invalid fields_to_update_config.")
        return
    profile, created = CustomerProfile.objects.get_or_create(contact=contact)
    if created:
        logger.info(f"Created CustomerProfile for contact {contact.whatsapp_id}")
    changed_fields = []
    for field_path, value_template in fields_to_update_config.items():
        resolved_value = _resolve_value(value_template, flow_context, contact)
        parts = field_path.split('.')
        try:
            if len(parts) == 1:
                field_name = parts[0]
                if hasattr(profile, field_name) and field_name.lower() not in ['id', 'pk', 'contact', 'contact_id', 'created_at', 'updated_at', 'last_updated_from_conversation']:
                    setattr(profile, field_name, resolved_value)
                    if field_name not in changed_fields:
                        changed_fields.append(field_name)
                else:
                    logger.warning(f"CustomerProfile field '{field_name}' not found or is protected.")
            elif parts[0] in ['preferences', 'custom_attributes'] and len(parts) > 1:
                json_field_name = parts[0]
                json_data = getattr(profile, json_field_name)
                if not isinstance(json_data, dict):
                    json_data = {}
                current_level = json_data
                for key in parts[1:-1]:
                    current_level = current_level.setdefault(key, {})
                    if not isinstance(current_level, dict):
                        logger.warning(f"Path error in CustomerProfile.{json_field_name} at '{key}'. Expected dict, found {type(current_level)}.")
                        current_level = None
                        break
                if current_level is not None:
                    final_key = parts[-1]
                    current_level[final_key] = resolved_value
                    setattr(profile, json_field_name, json_data)
                    if json_field_name not in changed_fields:
                        changed_fields.append(json_field_name)
            else:
                logger.warning(f"Unsupported field path for CustomerProfile: {field_path}")
        except Exception as e:
            logger.error(f"Error updating CustomerProfile field '{field_path}' for contact {contact.id}: {e}", exc_info=True)
    if changed_fields:
        profile.last_updated_from_conversation = timezone.now()
        if 'last_updated_from_conversation' not in changed_fields:
            changed_fields.append('last_updated_from_conversation')
        profile.save(update_fields=changed_fields)
        logger.info(f"CustomerProfile for {contact.whatsapp_id} updated fields: {changed_fields}")
    elif created:
        profile.last_updated_from_conversation = timezone.now()
        profile.save(update_fields=['last_updated_from_conversation'])

@transaction.atomic
def process_message_for_flow(contact: Contact, message_data: dict, incoming_message_obj: Message) -> List[Dict[str, Any]]:
    actions_to_perform = []
    try:
        contact_flow_state = ContactFlowState.objects.select_related('current_flow', 'current_step').get(contact=contact)
        logger.info(
            f"Contact {contact.whatsapp_id} is currently in flow '{contact_flow_state.current_flow.name}', "
            f"step '{contact_flow_state.current_step.name}'."
        )
        actions_to_perform = _handle_active_flow_step(
            contact_flow_state, contact, message_data, incoming_message_obj
        )
    except ContactFlowState.DoesNotExist:
        logger.info(f"No active flow state for contact {contact.whatsapp_id}. Attempting to trigger a new flow.")
        actions_to_perform = _trigger_new_flow(contact, message_data, incoming_message_obj)
    except Exception as e:
        logger.error(f"Critical error in process_message_for_flow for contact {contact.whatsapp_id}: {e}", exc_info=True)
        _clear_contact_flow_state(contact, error=True)
        actions_to_perform = [{
            'type': 'send_whatsapp_message',
            'recipient_wa_id': contact.whatsapp_id,
            'message_type': 'text',
            'data': {'body': 'I seem to be having some technical difficulties. Please try again in a moment.'}
        }]
        
    final_actions_for_meta_view = []
    # Process a copy of actions_to_perform because _trigger_new_flow called by switch_flow might modify it
    # by extending final_actions_for_meta_view which could affect iteration if iterating over original.
    # However, current logic appends to final_actions_for_meta_view, so direct iteration is okay for now.
    for action in actions_to_perform: 
        if action.get('type') == '_internal_command_clear_flow_state':
            logger.debug(f"Internal command: Cleared flow state for {contact.whatsapp_id} (already handled if direct).")
        elif action.get('type') == '_internal_command_switch_flow':
            logger.info(f"Processing internal command to switch flow for contact {contact.whatsapp_id}.")
            # _clear_contact_flow_state(contact) is called within _trigger_new_flow or before calling it when switching.
            # Ensure it's called before creating a new state.
            # The original clear for switch was here, moving to be sure it happens before _trigger_new_flow for switch.
            # _clear_contact_flow_state(contact) # This is good to ensure clean state for new flow.

            new_flow_name = action.get('target_flow_name')
            initial_context_for_new_flow = action.get('initial_context', {}) # Should be a dict
            new_flow_trigger_msg_body = action.get('new_flow_trigger_message_body')
            
            synthetic_message_data = {'type': 'text', 'text': {'body': new_flow_trigger_msg_body or f"trigger_{new_flow_name}"}} # Ensure some text body

            # _clear_contact_flow_state(contact) is implicitly called by _trigger_new_flow if it finds an old state,
            # but for an explicit switch, we ensure it's clean.
            # Note: _trigger_new_flow itself has a _clear_contact_flow_state(contact) if a keyword triggers a new flow.
            # If switching programmatically, we ensure the old one is gone.
            ContactFlowState.objects.filter(contact=contact).delete() # Explicit clear for switch

            switched_flow_actions = _trigger_new_flow(contact, synthetic_message_data, incoming_message_obj) # incoming_message_obj here is from original trigger
            
            newly_created_state = ContactFlowState.objects.filter(contact=contact).first()
            if newly_created_state and initial_context_for_new_flow and isinstance(initial_context_for_new_flow, dict):
                if not isinstance(newly_created_state.flow_context_data, dict):
                    newly_created_state.flow_context_data = {}
                newly_created_state.flow_context_data.update(initial_context_for_new_flow)
                newly_created_state.save(update_fields=['flow_context_data', 'last_updated_at'])
                logger.info(f"Applied initial context to new flow state for {contact.whatsapp_id}: {initial_context_for_new_flow}")

            final_actions_for_meta_view.extend(switched_flow_actions)
        elif action.get('type') == 'send_whatsapp_message':
            final_actions_for_meta_view.append(action)
        else:
            logger.warning(f"Unhandled action type in final processing: {action.get('type')}")
            
    return final_actions_for_meta_view