from django.test import TestCase
from pydantic import ValidationError

from flows.services import (
    InteractiveFlowAction,
    InteractiveFlowActionParameters,
    InteractiveMessagePayload,
    StepConfigSendMessage,
    StepConfigQuestion,
)


class InteractiveFlowActionParametersTests(TestCase):
    """Tests for the InteractiveFlowActionParameters Pydantic model."""

    def test_valid_data_exchange_parameters(self):
        params = InteractiveFlowActionParameters.model_validate({
            "flow_message_version": "3",
            "flow_token": "263774635389",
            "flow_id": "1751481449569466",
            "flow_cta": "Login",
            "flow_action": "data_exchange",
        })
        self.assertEqual(params.flow_action, "data_exchange")
        self.assertEqual(params.flow_id, "1751481449569466")
        self.assertIsNone(params.flow_action_payload)

    def test_valid_navigate_parameters(self):
        params = InteractiveFlowActionParameters.model_validate({
            "flow_message_version": "3",
            "flow_token": "",
            "flow_id": "12345",
            "flow_cta": "Open",
            "flow_action": "navigate",
            "flow_action_payload": {"screen": "INIT"},
        })
        self.assertEqual(params.flow_action, "navigate")
        self.assertEqual(params.flow_action_payload, {"screen": "INIT"})

    def test_invalid_flow_action_rejected(self):
        with self.assertRaises(ValidationError):
            InteractiveFlowActionParameters.model_validate({
                "flow_message_version": "3",
                "flow_id": "12345",
                "flow_cta": "Open",
                "flow_action": "invalid_action",
            })

    def test_missing_flow_id_rejected(self):
        with self.assertRaises(ValidationError):
            InteractiveFlowActionParameters.model_validate({
                "flow_message_version": "3",
                "flow_cta": "Open",
                "flow_action": "navigate",
            })


class InteractiveFlowActionTests(TestCase):
    """Tests for the InteractiveFlowAction Pydantic model."""

    def test_valid_flow_action(self):
        action = InteractiveFlowAction.model_validate({
            "name": "flow",
            "parameters": {
                "flow_message_version": "3",
                "flow_id": "12345",
                "flow_cta": "Login",
                "flow_action": "data_exchange",
            },
        })
        self.assertEqual(action.name, "flow")
        self.assertEqual(action.parameters.flow_action, "data_exchange")

    def test_invalid_name_rejected(self):
        with self.assertRaises(ValidationError):
            InteractiveFlowAction.model_validate({
                "name": "not_flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_id": "12345",
                    "flow_cta": "Login",
                    "flow_action": "data_exchange",
                },
            })


class InteractiveMessagePayloadFlowTests(TestCase):
    """Tests for InteractiveMessagePayload with type 'flow'."""

    def test_valid_flow_payload(self):
        payload = InteractiveMessagePayload.model_validate({
            "type": "flow",
            "body": {"text": "Tap the button below to enter your credentials securely."},
            "header": {"type": "text", "text": "Login"},
            "footer": {"text": "Your credentials are sent securely."},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_id": "1751481449569466",
                    "flow_cta": "Login",
                    "flow_token": "263774635389",
                    "flow_action": "data_exchange",
                    "flow_message_version": "3",
                },
            },
        })
        self.assertEqual(payload.type, "flow")
        self.assertIsInstance(payload.action, InteractiveFlowAction)

    def test_button_type_still_works(self):
        payload = InteractiveMessagePayload.model_validate({
            "type": "button",
            "body": {"text": "Choose an option"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "btn1", "title": "Option 1"}},
                ],
            },
        })
        self.assertEqual(payload.type, "button")


class StepConfigSendMessageFlowTests(TestCase):
    """Tests for StepConfigSendMessage with interactive flow type."""

    def test_valid_flow_send_message(self):
        config = StepConfigSendMessage.model_validate({
            "message_type": "interactive",
            "interactive": {
                "type": "flow",
                "body": {"text": "Tap the button below to enter your credentials securely."},
                "header": {"type": "text", "text": "Login"},
                "footer": {"text": "Your credentials are sent securely."},
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_id": "1751481449569466",
                        "flow_cta": "Login",
                        "flow_token": "263774635389",
                        "flow_action": "data_exchange",
                        "flow_message_version": "3",
                    },
                },
            },
        })
        self.assertEqual(config.interactive.type, "flow")
        self.assertIsInstance(config.interactive.action, InteractiveFlowAction)


class StepConfigQuestionFlowTests(TestCase):
    """Tests for StepConfigQuestion with interactive flow type."""

    def test_valid_flow_question_config(self):
        """Reproduces the exact config from the error log."""
        config = StepConfigQuestion.model_validate({
            "reply_config": {
                "expected_type": "any",
                "save_to_variable": "login_nfm_response",
            },
            "message_config": {
                "interactive": {
                    "body": {"text": "Tap the button below to enter your credentials securely."},
                    "type": "flow",
                    "action": {
                        "name": "flow",
                        "parameters": {
                            "flow_id": "1751481449569466",
                            "flow_cta": "Login",
                            "flow_token": "263774635389",
                            "flow_action": "data_exchange",
                            "flow_message_version": "3",
                        },
                    },
                    "footer": {"text": "Your credentials are sent securely."},
                    "header": {"text": "Login", "type": "text"},
                },
                "message_type": "interactive",
            },
        })
        self.assertEqual(config.reply_config.save_to_variable, "login_nfm_response")
