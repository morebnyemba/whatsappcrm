from django.test import TestCase

from pydantic import ValidationError

from conversations.models import Contact, ContactSession
from flows.models import Flow, FlowStep, WhatsAppFlow
from flows.whatsapp_flow_service import WhatsAppFlowService
from flows.services import (
    InteractiveFlowAction,
    InteractiveFlowActionParameters,
    InteractiveMessagePayload,
    StepConfigSendMessage,
    StepConfigQuestion,
    _build_login_prompt_action,
    _trigger_new_flow,
    process_message_for_flow,
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
        # Meta's Graph API rejects flow_action_payload when flow_action is
        # data_exchange ("Unexpected key \"flow_action_payload\"..." /
        # error 131009) — it must be absent here, not just unused.
        self.assertEqual(data["action"]["parameters"]["flow_action"], "data_exchange")
        self.assertNotIn("flow_action_payload", data["action"]["parameters"])


class SwitchFlowToNativeBettingFlowTests(TestCase):
    """The conversational engine's switch_flow action ('switch_to_betting' in the
    Welcome Flow) hands off to _trigger_new_flow, which -- for the native betting
    Flow -- returns a stateless send_whatsapp_message action without ever creating a
    ContactFlowState (there's no conversational flow to be 'in'). The switch-flow
    post-processing used to treat "no ContactFlowState was created" as "the switch
    failed" regardless of why, so it always appended a spurious 'Sorry, I could not
    switch to the requested section' text message after every successful native
    Flow launch. Guards against a regression of that bug."""

    def setUp(self):
        self.config = MetaAppConfig.objects.create(
            name="Test Config",
            app_secret="secret",
            access_token="token",
            phone_number_id="880051405199010",
            waba_id="111222334",
            verify_token="verify",
            is_active=True,
        )
        self.contact = Contact.objects.create(
            whatsapp_id="263780625683", associated_app_config=self.config
        )
        session = ContactSession.objects.create(contact=self.contact)
        session.start()
        WhatsAppFlow.objects.create(
            name="bet_whatsapp",
            friendly_name="BetBlitz (Interactive)",
            meta_app_config=self.config,
            flow_id="2216047699159394",
            flow_json={},
            is_active=True,
            sync_status="published",
        )
        trigger_flow = Flow.objects.create(
            name="Trigger Bet Flow Test",
            is_active=True,
            trigger_keywords=["startbet"],
        )
        FlowStep.objects.create(
            flow=trigger_flow,
            name="switch_to_betting",
            step_type="action",
            is_entry_point=True,
            config={"actions_to_run": [
                {"action_type": "switch_flow", "trigger_keyword_template": "bet"}
            ]},
        )

    def test_successful_native_flow_launch_has_no_spurious_error_message(self):
        message_data = {"type": "text", "text": {"body": "startbet"}}
        actions = process_message_for_flow(self.contact, message_data, None)

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["data"].get("type"), "flow")
        self.assertEqual(actions[0]["data"]["action"]["parameters"]["flow_id"], "2216047699159394")


class TraditionalFlowTransitionIntegrityTests(TestCase):
    """Each traditional flow definition's transitions reference other steps by
    name string (`to_step`), with no validation at definition time. The
    loader (load_flow_definitions._load_traditional_flow) silently drops any
    transition whose `to_step` doesn't match a step in the same flow -- it
    only logs a warning, never raises -- so a typo'd or removed step name
    quietly turns into a dead end: the contact reaches that step and the
    conversation just stops, with nothing in the logs a live user would ever
    see. This happened for real: Deposit Flow's `ensure_customer_account`
    step transitioned to a step named 'account_creation_failed' that was
    never defined, so a failed account-creation silently stranded the user.

    This test loads no database rows -- it walks the plain dict returned by
    each TRADITIONAL_FLOW_CREATORS entry and checks every transition's
    `to_step` resolves to a real step name in that same flow, so a dangling
    reference fails fast in CI instead of silently degrading a live flow."""

    def test_every_transition_target_exists_in_its_own_flow(self):
        from flows.definitions import TRADITIONAL_FLOW_CREATORS

        dangling = []
        for creator in TRADITIONAL_FLOW_CREATORS:
            flow_def = creator()
            step_names = {step['name'] for step in flow_def.get('steps', [])}
            for step in flow_def.get('steps', []):
                for transition in step.get('transitions', []):
                    to_step = transition.get('to_step')
                    if to_step not in step_names:
                        dangling.append(
                            f"{flow_def['name']}: '{step['name']}' -> '{to_step}'"
                        )

        self.assertEqual(dangling, [], "Dangling transition(s) found:\n" + "\n".join(dangling))


class CreateFlowMessageDataTests(TestCase):
    """Meta's Graph API rejects flow_action_payload when flow_action is
    data_exchange (error 131009) — it's only valid for flow_action=navigate,
    since data_exchange mode has Meta call the endpoint's own INIT action to
    get the first screen instead of the caller specifying one up front."""

    def test_data_exchange_omits_flow_action_payload(self):
        data = WhatsAppFlowService.create_flow_message_data(
            flow_id="123", screen="BET_MENU", flow_cta="Open", body_text="Body",
            flow_action="data_exchange",
        )
        self.assertNotIn("flow_action_payload", data["action"]["parameters"])

    def test_navigate_includes_flow_action_payload(self):
        data = WhatsAppFlowService.create_flow_message_data(
            flow_id="123", screen="LOGIN", flow_cta="Login", body_text="Body",
            flow_action="navigate",
        )
        self.assertEqual(data["action"]["parameters"]["flow_action_payload"], {"screen": "LOGIN"})

    def test_default_flow_action_is_navigate_with_payload(self):
        data = WhatsAppFlowService.create_flow_message_data(
            flow_id="123", screen="REGISTER", flow_cta="Register", body_text="Body",
        )
        self.assertEqual(data["action"]["parameters"]["flow_action"], "navigate")
        self.assertEqual(data["action"]["parameters"]["flow_action_payload"], {"screen": "REGISTER"})
