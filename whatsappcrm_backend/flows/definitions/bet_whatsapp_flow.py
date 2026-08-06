# whatsappcrm_backend/flows/definitions/bet_whatsapp_flow.py
"""
WhatsApp UI **Flow** JSON for placing a bet natively in WhatsApp (data_exchange).

Every screen is dynamic: on open (INIT) and on each submit, the backend
data-exchange endpoint (meta_integration.views.WhatsAppFlowEndpointView →
football_data_app.bet_flow_handler) returns the next screen and its data
(fixtures, markets, outcomes, balance, confirmation). The bet is placed
server-side when the CONFIRM screen is submitted, reusing the same
ticket-processing validation as the rest of the system.

Screen ids are namespaced BET_* so the shared Flow endpoint can route them.
"""

_ERR = {
    "error_message": {"type": "string", "__example__": ""},
    "is_error": {"type": "boolean", "__example__": False},
}
_OPTION_EXAMPLE = [{"id": "1", "title": "Example", "description": ""}]

BET_WHATSAPP_FLOW = {
    "version": "6.0",
    "data_api_version": "3.0",
    "routing_model": {
        "BET_BROWSE": ["BET_MARKETS"],
        "BET_MARKETS": ["BET_OUTCOMES", "BET_BROWSE"],
        "BET_OUTCOMES": ["BET_STAKE", "BET_BROWSE"],
        "BET_STAKE": ["BET_CONFIRM", "BET_BROWSE"],
        "BET_CONFIRM": ["BET_SUCCESS", "BET_BROWSE"],
    },
    "screens": [
        {
            "id": "BET_BROWSE",
            "title": "Place a Bet",
            "data": {
                "fixtures": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                "has_fixtures": {"type": "boolean", "__example__": True},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Upcoming Matches"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "browse_form", "children": [
                    {"type": "Dropdown", "name": "fixture_id", "label": "Match", "required": True,
                     "data-source": "${data.fixtures}"},
                    {"type": "Footer", "label": "Next", "on-click-action": {
                        "name": "data_exchange", "payload": {"fixture_id": "${form.fixture_id}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_MARKETS",
            "title": "Choose Market",
            "data": {
                "fixture_id": {"type": "string", "__example__": "1"},
                "fixture_label": {"type": "string", "__example__": "Home v Away"},
                "markets": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "${data.fixture_label}"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "markets_form", "children": [
                    {"type": "Dropdown", "name": "market_id", "label": "Market", "required": True,
                     "data-source": "${data.markets}"},
                    {"type": "Footer", "label": "Next", "on-click-action": {
                        "name": "data_exchange", "payload": {"market_id": "${form.market_id}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_OUTCOMES",
            "title": "Choose Selection",
            "data": {
                "market_label": {"type": "string", "__example__": "Match Winner"},
                "outcomes": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "${data.market_label}"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "outcomes_form", "children": [
                    {"type": "Dropdown", "name": "outcome_id", "label": "Selection", "required": True,
                     "data-source": "${data.outcomes}"},
                    {"type": "Footer", "label": "Next", "on-click-action": {
                        "name": "data_exchange", "payload": {"outcome_id": "${form.outcome_id}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_STAKE",
            "title": "Enter Stake",
            "data": {
                "outcome_id": {"type": "string", "__example__": "1"},
                "selection_label": {"type": "string", "__example__": "Home v Away — Home @ 2.00"},
                "odds": {"type": "string", "__example__": "2.00"},
                "balance": {"type": "string", "__example__": "0.00"},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Your selection"},
                {"type": "TextBody", "text": "${data.selection_label}"},
                {"type": "TextCaption", "text": "Balance: $${data.balance}"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "stake_form", "children": [
                    {"type": "TextInput", "name": "stake", "label": "Stake ($)", "required": True,
                     "input-type": "number", "helper-text": "How much to stake"},
                    {"type": "Footer", "label": "Review", "on-click-action": {
                        "name": "data_exchange", "payload": {
                            "outcome_id": "${data.outcome_id}", "stake": "${form.stake}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_CONFIRM",
            "title": "Confirm Bet",
            "data": {
                "outcome_id": {"type": "string", "__example__": "1"},
                "stake": {"type": "string", "__example__": "10.00"},
                "summary": {"type": "string", "__example__": "Home v Away\nHome @ 2.00\nStake: $10.00"},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Confirm your bet"},
                {"type": "TextBody", "text": "${data.summary}"},
                {"type": "Form", "name": "confirm_form", "children": [
                    {"type": "Footer", "label": "Place bet", "on-click-action": {
                        "name": "data_exchange", "payload": {
                            "outcome_id": "${data.outcome_id}", "stake": "${data.stake}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_SUCCESS",
            "title": "Bet Placed",
            "terminal": True,
            "success": True,
            "data": {"message": {"type": "string", "__example__": "Bet placed!"}},
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Bet placed 🎉"},
                {"type": "TextBody", "text": "${data.message}"},
                {"type": "Footer", "label": "Done", "on-click-action": {
                    "name": "complete", "payload": {"placed": "true"}}},
            ]},
        },
    ],
}

BET_WHATSAPP_FLOW_METADATA = {
    "name": "bet_whatsapp",
    "friendly_name": "Place a Bet (Interactive)",
    "description": "Native WhatsApp Flow for browsing fixtures and placing a bet.",
    "is_active": True,
}
