from django.test import TestCase

from pydantic import ValidationError

from conversations.models import Contact, ContactSession
from flows.models import WhatsAppFlow
from flows.services import (
    InteractiveFlowAction,
    InteractiveFlowActionParameters,
    InteractiveMessagePayload,
    StepConfigSendMessage,
    StepConfigQuestion,
    _build_login_prompt_action,
    _trigger_new_flow,
)
from meta_integration.models import MetaAppConfig


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


class LoginPromptActionTests(TestCase):
    """Meta rejects interactive button messages whose footer exceeds 60
    characters (error 131009). Guards against a regression of that bug."""

    def test_footer_within_whatsapp_limit(self):
        action = _build_login_prompt_action("263774635389", "Welcome!")
        footer_text = action["data"]["footer"]["text"]
        self.assertLessEqual(len(footer_text), 60)


class NativeBettingFlowLoginGateTests(TestCase):
    """The native betting Flow launcher intercepts the 'bet' keyword ahead of
    the conversational Betting Flow's own login check, so it must enforce
    login itself. Without this, an unauthenticated contact could browse
    fixtures/markets/odds and reach the confirm screen, only to have bet
    placement silently fail server-side (no linked user account)."""

    def setUp(self):
        self.config = MetaAppConfig.objects.create(
            name="Test Config",
            app_secret="secret",
            access_token="token",
            phone_number_id="880051405199009",
            waba_id="111222333",
            verify_token="verify",
            is_active=True,
        )
        self.contact = Contact.objects.create(
            whatsapp_id="263780625682", associated_app_config=self.config
        )
        WhatsAppFlow.objects.create(
            name="bet_whatsapp",
            friendly_name="BetBlitz (Interactive)",
            meta_app_config=self.config,
            flow_id="2216047699159394",
            flow_json={},
            is_active=True,
            sync_status="published",
        )

    def _text_message(self, body):
        return {"type": "text", "text": {"body": body}}

    def test_bet_keyword_without_session_prompts_login_not_the_flow(self):
        actions = _trigger_new_flow(self.contact, self._text_message("bet"), None)
        self.assertEqual(len(actions), 1)
        data = actions[0]["data"]
        # Must be the Login/Register button prompt, not the native Flow message.
        self.assertEqual(data.get("type"), "button")
        button_ids = {b["reply"]["id"] for b in data["action"]["buttons"]}
        self.assertEqual(button_ids, {"prompt_login", "prompt_register"})

    def test_bet_keyword_with_valid_session_launches_the_flow(self):
        session = ContactSession.objects.create(contact=self.contact)
        session.start()
        actions = _trigger_new_flow(self.contact, self._text_message("bet"), None)
        self.assertEqual(len(actions), 1)
        data = actions[0]["data"]
        self.assertEqual(data.get("type"), "flow")
        self.assertEqual(data["action"]["parameters"]["flow_id"], "2216047699159394")
