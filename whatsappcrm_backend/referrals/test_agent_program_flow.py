# whatsappcrm_backend/referrals/test_agent_program_flow.py
"""
The Agent Program flow (referrals/flows.py::create_referral_flow) had no test
coverage of its own -- referrals/tests.py covers the underlying commission/
earnings math (AgentEarning, award_agent_commission, etc.) thoroughly, but
nothing exercised the conversational flow itself: whether "agent" actually
routes there from the Welcome/Account Management menus, the login gate, or
the is_agent branch that decides between the real agent menu and "you're not
an agent, contact support".

These tests load the real flow definition (not a hand-rolled stand-in) via
the same loader load_flow_definitions uses, and drive it through the actual
conversational engine (process_message_for_flow) exactly as a live WhatsApp
message would.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from conversations.models import Contact, ContactSession
from customer_data.models import CustomerProfile
from flows.models import Flow, ContactFlowState
from flows.services import process_message_for_flow
from meta_integration.models import MetaAppConfig
from referrals.flows import create_referral_flow
from referrals.models import ReferralProfile


class AgentProgramFlowTests(TestCase):
    def setUp(self):
        self.config = MetaAppConfig.objects.create(
            name="Agent Program Test Config",
            app_secret="secret",
            access_token="token",
            phone_number_id="222",
            waba_id="waba222",
            verify_token="vt",
            is_active=True,
        )
        self.contact = Contact.objects.create(
            whatsapp_id="263771112222", associated_app_config=self.config
        )
        self.user = User.objects.create_user(username="agenttester", password="irrelevant")
        CustomerProfile.objects.create(
            contact=self.contact, user=self.user,
            date_of_birth=timezone.localdate().replace(year=1990),
        )

        # Load the real flow definition the same way `load_flow_definitions`
        # does, rather than a hand-rolled stand-in -- so these tests fail if
        # the actual production flow (steps, transitions, trigger_keywords)
        # ever drifts from what's exercised here.
        from flows.management.commands.load_flow_definitions import Command as LoadFlowsCommand
        LoadFlowsCommand()._load_traditional_flow(create_referral_flow())
        self.agent_program_flow = Flow.objects.get(name="Agent Program")
        self.agent_program_flow.is_active = True
        self.agent_program_flow.save(update_fields=["is_active"])

    def _text_message(self, body):
        return {"type": "text", "text": {"body": body}}

    def _log_in(self):
        session = ContactSession.objects.create(contact=self.contact)
        session.start()

    def test_agent_keyword_without_session_prompts_login(self):
        actions = process_message_for_flow(self.contact, self._text_message("agent"), None)
        self.assertEqual(len(actions), 1)
        data = actions[0]["data"]
        self.assertEqual(data.get("type"), "button")
        button_ids = {b["reply"]["id"] for b in data["action"]["buttons"]}
        self.assertEqual(button_ids, {"prompt_login", "prompt_register"})
        # Login gate must trip before any flow state is created for a
        # non-agent, unauthenticated contact.
        self.assertFalse(ContactFlowState.objects.filter(contact=self.contact).exists())

    def test_logged_in_non_agent_is_told_they_are_not_an_agent(self):
        self._log_in()
        # No ReferralProfile at all, matching a brand-new user who's never
        # been designated an agent.
        actions = process_message_for_flow(self.contact, self._text_message("agent"), None)

        combined = " ".join(str(a.get("data")) for a in actions)
        self.assertIn("not currently enrolled as an agent", combined)
        # Must never reach the real agent menu (which would let a
        # non-designated user generate a referral code / see earnings).
        self.assertNotIn("Agent Program!", combined)

    def test_logged_in_designated_agent_reaches_the_agent_menu(self):
        self._log_in()
        ReferralProfile.objects.create(user=self.user, is_agent=True)

        actions = process_message_for_flow(self.contact, self._text_message("agent"), None)

        combined = " ".join(str(a.get("data")) for a in actions)
        self.assertIn("Welcome to the Agent Program!", combined)
        # The three real agent actions must be offered.
        self.assertIn("get_referral_code", combined)
        self.assertIn("check_agent_earnings", combined)
        self.assertIn("check_total_referrals", combined)

    def test_agent_can_request_their_referral_code(self):
        self._log_in()
        profile = ReferralProfile.objects.create(user=self.user, is_agent=True)

        process_message_for_flow(self.contact, self._text_message("agent"), None)
        state = ContactFlowState.objects.get(contact=self.contact)
        self.assertEqual(state.current_step.name, "show_agent_options")

        actions = process_message_for_flow(
            self.contact,
            {"type": "interactive", "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "get_referral_code", "title": "Get My Agent Code"},
            }},
            None,
        )

        combined = " ".join(str(a.get("data")) for a in actions)
        self.assertIn(profile.referral_code, combined)

    def test_welcome_flow_agent_program_option_routes_here(self):
        """The Welcome Flow's "Agent Program" menu row switches to this exact
        flow via the "agent" trigger keyword -- confirms that wiring still
        resolves to a real, active Flow row, not a dangling keyword."""
        self._log_in()
        ReferralProfile.objects.create(user=self.user, is_agent=True)

        from flows.welcome_flow import create_welcome_flow
        from flows.management.commands.load_flow_definitions import Command as LoadFlowsCommand
        LoadFlowsCommand()._load_traditional_flow(create_welcome_flow())
        Flow.objects.filter(name="Welcome Flow").update(is_active=True)

        process_message_for_flow(self.contact, self._text_message("hi"), None)
        actions = process_message_for_flow(
            self.contact,
            {"type": "interactive", "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "welcome_agent_program", "title": "Agent Program"},
            }},
            None,
        )

        combined = " ".join(str(a.get("data")) for a in actions)
        self.assertIn("Welcome to the Agent Program!", combined)
