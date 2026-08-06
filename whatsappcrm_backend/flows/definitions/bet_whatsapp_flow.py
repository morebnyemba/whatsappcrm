# whatsappcrm_backend/flows/definitions/bet_whatsapp_flow.py
"""
WhatsApp UI **Flow** JSON for the native BetBlitz betting hub (data_exchange).

The Flow opens on a menu and folds the whole experience into native WhatsApp UI:
place a bet, build an accumulator (bet slip), view my bets, check my balance, and
manage safer-gambling controls. Every screen is dynamic: on open (INIT) and on
each submit, the backend data-exchange endpoint
(meta_integration.views.WhatsAppFlowEndpointView →
football_data_app.bet_flow_handler) returns the next screen and its data.

The running bet slip is threaded through screen data/payloads as a compact CSV
of outcome ids (`slip`); odds are always re-derived server-side. Bets are placed
server-side, reusing the same ticket-processing validation as the rest of the
system. Screen ids are namespaced BET_* so the shared Flow endpoint can route them.
"""

_ERR = {
    "error_message": {"type": "string", "__example__": ""},
    "is_error": {"type": "boolean", "__example__": False},
}
_OPTION_EXAMPLE = [{"id": "1", "title": "Example", "description": ""}]
_SLIP = {"slip": {"type": "string", "__example__": ""}}

BET_WHATSAPP_FLOW = {
    "version": "6.0",
    "data_api_version": "3.0",
    "routing_model": {
        "BET_MENU": ["BET_BROWSE", "BET_SLIP", "BET_MYBETS", "BET_SAFER", "BET_DONE"],
        "BET_BROWSE": ["BET_MARKETS"],
        "BET_MARKETS": ["BET_OUTCOMES", "BET_BROWSE"],
        "BET_OUTCOMES": ["BET_STAKE", "BET_SLIP", "BET_BROWSE"],
        "BET_STAKE": ["BET_CONFIRM", "BET_BROWSE"],
        "BET_CONFIRM": ["BET_SUCCESS", "BET_BROWSE"],
        "BET_SLIP": ["BET_SUCCESS", "BET_BROWSE", "BET_MENU"],
        "BET_MYBETS": ["BET_DONE"],
        "BET_SAFER": ["BET_DONE"],
    },
    "screens": [
        {
            "id": "BET_MENU",
            "title": "BetBlitz",
            "data": {
                **_SLIP,
                "menu": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                "message": {"type": "string", "__example__": "What would you like to do?"},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "⚽ BetBlitz"},
                {"type": "TextBody", "text": "${data.message}"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "menu_form", "children": [
                    {"type": "RadioButtonsGroup", "name": "action", "label": "Menu", "required": True,
                     "data-source": "${data.menu}"},
                    {"type": "Footer", "label": "Continue", "on-click-action": {
                        "name": "data_exchange", "payload": {
                            "action": "${form.action}", "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_BROWSE",
            "title": "Place a Bet",
            "data": {
                **_SLIP,
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
                        "name": "data_exchange", "payload": {
                            "fixture_id": "${form.fixture_id}", "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_MARKETS",
            "title": "Choose Market",
            "data": {
                **_SLIP,
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
                        "name": "data_exchange", "payload": {
                            "market_id": "${form.market_id}", "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_OUTCOMES",
            "title": "Choose Selection",
            "data": {
                **_SLIP,
                "market_label": {"type": "string", "__example__": "Match Winner"},
                "outcomes": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                "modes": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "${data.market_label}"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "outcomes_form", "children": [
                    {"type": "Dropdown", "name": "outcome_id", "label": "Selection", "required": True,
                     "data-source": "${data.outcomes}"},
                    {"type": "RadioButtonsGroup", "name": "mode", "label": "Then", "required": True,
                     "data-source": "${data.modes}"},
                    {"type": "Footer", "label": "Continue", "on-click-action": {
                        "name": "data_exchange", "payload": {
                            "outcome_id": "${form.outcome_id}", "mode": "${form.mode}",
                            "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_STAKE",
            "title": "Enter Stake",
            "data": {
                **_SLIP,
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
                            "outcome_id": "${data.outcome_id}", "stake": "${form.stake}",
                            "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_CONFIRM",
            "title": "Confirm Bet",
            "data": {
                **_SLIP,
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
                            "outcome_id": "${data.outcome_id}", "stake": "${data.stake}",
                            "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_SLIP",
            "title": "Bet Slip",
            "data": {
                **_SLIP,
                "summary": {"type": "string", "__example__": "🧾 Your Bet Slip"},
                "has_slip": {"type": "boolean", "__example__": False},
                "slip_actions": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Your bet slip"},
                {"type": "TextBody", "text": "${data.summary}"},
                {"type": "Form", "name": "slip_form", "children": [
                    {"type": "TextInput", "name": "stake", "label": "Stake ($)", "required": False,
                     "input-type": "number", "helper-text": "Stake for the whole slip"},
                    {"type": "RadioButtonsGroup", "name": "slip_action", "label": "Action", "required": True,
                     "data-source": "${data.slip_actions}"},
                    {"type": "Footer", "label": "Continue", "on-click-action": {
                        "name": "data_exchange", "payload": {
                            "slip_action": "${form.slip_action}", "stake": "${form.stake}",
                            "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_MYBETS",
            "title": "My Bets",
            "data": {
                **_SLIP,
                "tickets": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Your recent bets"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "mybets_form", "children": [
                    {"type": "Dropdown", "name": "ticket_id", "label": "Ticket", "required": True,
                     "data-source": "${data.tickets}"},
                    {"type": "Footer", "label": "View", "on-click-action": {
                        "name": "data_exchange", "payload": {"ticket_id": "${form.ticket_id}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_SAFER",
            "title": "Safer Gambling",
            "data": {
                "summary": {"type": "string", "__example__": "🛡️ Safer Gambling"},
                "safer_actions": {"type": "array", "items": {"type": "object"}, "__example__": _OPTION_EXAMPLE},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Safer gambling"},
                {"type": "TextBody", "text": "${data.summary}"},
                {"type": "Form", "name": "safer_form", "children": [
                    {"type": "RadioButtonsGroup", "name": "safer_action", "label": "Choose", "required": True,
                     "data-source": "${data.safer_actions}"},
                    {"type": "TextInput", "name": "amount", "label": "Limit amount ($)", "required": False,
                     "input-type": "number", "helper-text": "For a deposit/stake limit. 0 removes it."},
                    {"type": "Footer", "label": "Apply", "on-click-action": {
                        "name": "data_exchange", "payload": {
                            "safer_action": "${form.safer_action}", "amount": "${form.amount}"}}},
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
        {
            "id": "BET_DONE",
            "title": "BetBlitz",
            "terminal": True,
            "success": True,
            "data": {
                "heading": {"type": "string", "__example__": "Done"},
                "message": {"type": "string", "__example__": ""},
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "${data.heading}"},
                {"type": "TextBody", "text": "${data.message}"},
                {"type": "Footer", "label": "Close", "on-click-action": {
                    "name": "complete", "payload": {"done": "true"}}},
            ]},
        },
    ],
}

BET_WHATSAPP_FLOW_METADATA = {
    "name": "bet_whatsapp",
    "friendly_name": "BetBlitz (Interactive)",
    "description": "Native WhatsApp Flow: place bets, accumulators, my bets, balance and safer gambling.",
    "is_active": True,
}
