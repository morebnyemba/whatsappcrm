# whatsappcrm_backend/flows/definitions/__init__.py

# Conversational flow definitions (traditional Flow → FlowStep → FlowTransition)
from flows.welcome_flow import create_welcome_flow
from flows.registration_flow import create_registration_flow
from flows.login_flow import create_login_flow
from flows.betting_flow import create_betting_flow
from flows.deposit_flow import create_deposit_flow
from flows.withdrawal_flow import create_withdrawal_flow
from flows.get_fixtures_flow import create_get_fixtures_flow
from flows.view_results_flow import create_view_results_flow
from flows.account_management_flow import create_account_management_flow
from referrals.flows import create_referral_flow

# WhatsApp UI flow definitions (WhatsAppFlow with Meta JSON schema)
from flows.definitions.login_whatsapp_flow import (
    LOGIN_WHATSAPP_FLOW,
    LOGIN_WHATSAPP_FLOW_METADATA,
)
from flows.definitions.register_whatsapp_flow import (
    REGISTER_WHATSAPP_FLOW,
    REGISTER_WHATSAPP_FLOW_METADATA,
)

TRADITIONAL_FLOW_CREATORS = [
    create_welcome_flow,
    create_registration_flow,
    create_login_flow,
    create_betting_flow,
    create_deposit_flow,
    create_withdrawal_flow,
    create_get_fixtures_flow,
    create_view_results_flow,
    create_account_management_flow,
    create_referral_flow,
]

WHATSAPP_UI_FLOWS = [
    (LOGIN_WHATSAPP_FLOW, LOGIN_WHATSAPP_FLOW_METADATA),
    (REGISTER_WHATSAPP_FLOW, REGISTER_WHATSAPP_FLOW_METADATA),
]
