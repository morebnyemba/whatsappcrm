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

# Every RadioButtonsGroup/Dropdown bound to a *dynamic* data-source
# (`"data-source": "${data.X}"`) in this Flow has submitted with no value at
# all on every device tested, regardless of component type -- see git history
# on this file and football_data_app/bet_flow_handler.py for the full trail
# (field renames, missing "description" item property, RadioButtonsGroup vs
# Dropdown). Per Meta's own Flow JSON docs, `data-source` also accepts a
# *static* literal array baked into the screen JSON at publish time instead of
# a dynamic reference -- a genuinely different code path in the WhatsApp
# client, unlike swapping component type. The four fixed, small option lists
# below (menu / bet-mode / slip-action / safer-gambling) are static in
# practice, so they're inlined here as literals rather than resolved from
# screen `data` each request. Import from bet_flow_handler so the ids this
# Flow submits and the ids handle_data_exchange checks for can never drift
# apart. The genuinely variable-length lists (fixtures/markets/outcomes/
# tickets) remain dynamic -- they can't be static.
from football_data_app.bet_flow_handler import MENU_ITEMS, MENU_MODES, SLIP_ACTIONS, SAFER_ACTIONS

_ERR = {
    "error_message": {"type": "string", "__example__": ""},
    "is_error": {"type": "boolean", "__example__": False},
}
_OPTION_EXAMPLE = [{"id": "1", "title": "Example", "description": "Example option"}]
# Meta requires dynamic data-source arrays to declare their item object schema
# (id/title/description), not a bare {"type": "object"}.
_OPTION_ITEMS = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
    },
}
_SLIP = {"slip": {"type": "string", "__example__": ""}}

BET_WHATSAPP_FLOW = {
    "version": "6.0",
    "data_api_version": "3.0",
    # Forward-only DAG (Meta rejects backward edges; back navigation uses the
    # device back button). BET_MENU is the entry screen (no inbound edges);
    # BET_SUCCESS and BET_DONE are terminal.
    "routing_model": {
        "BET_MENU": ["BET_BROWSE", "BET_SLIP", "BET_MYBETS", "BET_SAFER", "BET_DONE"],
        "BET_BROWSE": ["BET_MARKETS"],
        "BET_MARKETS": ["BET_OUTCOMES"],
        "BET_OUTCOMES": ["BET_STAKE", "BET_SLIP"],
        "BET_STAKE": ["BET_CONFIRM"],
        "BET_CONFIRM": ["BET_SUCCESS"],
        "BET_SLIP": ["BET_SUCCESS", "BET_DONE"],
        "BET_MYBETS": ["BET_DONE"],
        "BET_SAFER": ["BET_DONE"],
    },
    "screens": [
        {
            "id": "BET_MENU",
            "title": "BetBlitz",
            "data": {
                **_SLIP,
                "message": {"type": "string", "__example__": "What would you like to do?"},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "⚽ BetBlitz"},
                {"type": "TextBody", "text": "${data.message}"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "menu_form", "children": [
                    # Named "menu_choice", not "action" -- every other RadioButtonsGroup in
                    # this Flow uses a compound name (mode/slip_action/safer_action); "action"
                    # bare also names a load-bearing key elsewhere in WhatsApp's own Flow
                    # message schema (the interactive message's own "action" object,
                    # "on-click-action"), and a bare-"action" field consistently submitted
                    # with no value at all even when a radio option was selected.
                    #
                    # RadioButtonsGroup with a STATIC data-source (MENU_ITEMS, a literal
                    # array), not a dynamic "${data.menu}" reference. Every RadioButtonsGroup/
                    # Dropdown bound to a dynamic data-source in this Flow submitted with no
                    # value at all, on every device tested, regardless of component type --
                    # see the module docstring. This menu's five options are fixed in
                    # practice, so making the data-source static (a genuinely different code
                    # path per Meta's Flow JSON docs) is the next differential test.
                    {"type": "RadioButtonsGroup", "name": "menu_choice", "label": "Menu", "required": True,
                     "data-source": MENU_ITEMS},
                    {"type": "Footer", "label": "Continue", "on-click-action": {
                        "name": "data_exchange", "payload": {
                            "action": "${form.menu_choice}", "slip": "${data.slip}"}}},
                ]},
            ]},
        },
        {
            "id": "BET_BROWSE",
            "title": "Place a Bet",
            "data": {
                **_SLIP,
                "fixtures": {"type": "array", "items": _OPTION_ITEMS, "__example__": _OPTION_EXAMPLE},
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
                "markets": {"type": "array", "items": _OPTION_ITEMS, "__example__": _OPTION_EXAMPLE},
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
                "outcomes": {"type": "array", "items": _OPTION_ITEMS, "__example__": _OPTION_EXAMPLE},
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "${data.market_label}"},
                {"type": "TextBody", "text": "${data.error_message}", "visible": "${data.is_error}"},
                {"type": "Form", "name": "outcomes_form", "children": [
                    {"type": "Dropdown", "name": "outcome_id", "label": "Selection", "required": True,
                     "data-source": "${data.outcomes}"},
                    # Static data-source (MENU_MODES) -- see the module docstring.
                    {"type": "RadioButtonsGroup", "name": "mode", "label": "Then", "required": True,
                     "data-source": MENU_MODES},
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
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Your bet slip"},
                {"type": "TextBody", "text": "${data.summary}"},
                {"type": "Form", "name": "slip_form", "children": [
                    {"type": "TextInput", "name": "stake", "label": "Stake ($)", "required": False,
                     "input-type": "number", "helper-text": "Stake for the whole slip"},
                    # Static data-source (SLIP_ACTIONS) -- see the module docstring.
                    {"type": "RadioButtonsGroup", "name": "slip_action", "label": "Action", "required": True,
                     "data-source": SLIP_ACTIONS},
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
                "tickets": {"type": "array", "items": _OPTION_ITEMS, "__example__": _OPTION_EXAMPLE},
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
                **_ERR,
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextHeading", "text": "Safer gambling"},
                {"type": "TextBody", "text": "${data.summary}"},
                {"type": "Form", "name": "safer_form", "children": [
                    # Static data-source (SAFER_ACTIONS) -- see the module docstring.
                    {"type": "RadioButtonsGroup", "name": "safer_action", "label": "Choose", "required": True,
                     "data-source": SAFER_ACTIONS},
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
