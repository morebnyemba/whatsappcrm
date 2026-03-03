# whatsappcrm_backend/flows/definitions/whatsapp_flow_converter.py

"""
Helper functions to build WhatsApp Flow JSON components conforming to
Meta's Flow JSON schema.  These utilities make it easier to define
screen-based WhatsApp UI Flows in Python and then persist them as
``WhatsAppFlow`` model records.
"""

from typing import Dict, List, Any, Optional


def create_text_input(
    name: str,
    label: str,
    required: bool = True,
    helper_text: str = None,
    input_type: str = "text",
) -> Dict[str, Any]:
    """Create a TextInput component."""
    component: Dict[str, Any] = {
        "type": "TextInput",
        "name": name,
        "label": label,
        "required": required,
        "input-type": input_type,
    }
    if helper_text:
        component["helper-text"] = helper_text
    return component


def create_dropdown(
    name: str,
    label: str,
    options: List[Dict[str, str]],
    required: bool = True,
) -> Dict[str, Any]:
    """Create a Dropdown component."""
    return {
        "type": "Dropdown",
        "name": name,
        "label": label,
        "required": required,
        "data-source": options,
    }


def create_radio_buttons(
    name: str,
    label: str,
    options: List[Dict[str, str]],
    required: bool = True,
) -> Dict[str, Any]:
    """Create a RadioButtonsGroup component."""
    return {
        "type": "RadioButtonsGroup",
        "name": name,
        "label": label,
        "required": required,
        "data-source": options,
    }


def create_date_picker(
    name: str, label: str, required: bool = True
) -> Dict[str, Any]:
    """Create a DatePicker component."""
    return {
        "type": "DatePicker",
        "name": name,
        "label": label,
        "required": required,
    }


def create_text_body(text: str) -> Dict[str, Any]:
    """Create a TextBody component for displaying information."""
    return {"type": "TextBody", "text": text}


def create_text_heading(text: str) -> Dict[str, Any]:
    """Create a TextHeading component."""
    return {"type": "TextHeading", "text": text}


def create_footer(
    label: str, on_click_action: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a Footer with a navigation/complete button."""
    return {
        "type": "Footer",
        "label": label,
        "on-click-action": on_click_action,
    }


def create_navigate_action(
    next_screen: str, payload: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Create a navigate action to move to another screen."""
    action: Dict[str, Any] = {
        "name": "navigate",
        "next": {"type": "screen", "name": next_screen},
    }
    if payload:
        action["payload"] = payload
    return action


def create_complete_action(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """Create a complete action to finish the flow."""
    action: Dict[str, Any] = {"name": "complete"}
    if payload:
        action["payload"] = payload
    return action


def create_screen(
    screen_id: str,
    title: str,
    layout: List[Dict[str, Any]],
    data: Optional[Dict[str, Any]] = None,
    terminal: bool = False,
    success: bool = False,
) -> Dict[str, Any]:
    """Create a complete screen for a WhatsApp Flow."""
    screen: Dict[str, Any] = {
        "id": screen_id,
        "title": title,
        "layout": {"type": "SingleColumnLayout", "children": layout},
    }
    if data:
        screen["data"] = data
    if terminal:
        screen["terminal"] = True
    if success:
        screen["success"] = True
    return screen
