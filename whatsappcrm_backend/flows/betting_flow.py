# whatsappcrm_backend/flows/betting_flow.py
"""
Tap-driven WhatsApp betting flow (BetBlitz).

Replaces the old text/PDF betting experience with a fully guided, interactive
journey: browse matches -> pick market -> pick outcome -> build a slip ->
choose a stake -> confirm -> place. Selections are always real MarketOutcome
ids and placement is delegated to the existing, well-tested
customer_data.ticket_processing validation. Also provides "My bets".

Interactive lists whose rows are generated at runtime (fixtures, markets,
outcomes, tickets) use the `sections_from` primitive: a preceding action step
builds the rows into a flow-context variable and the question step renders them.
"""


def _list_question(name, body, button, sections_var, save_var, transitions, header=None, footer=None):
    """Helper: a question step that shows a dynamic interactive list."""
    interactive = {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button, "sections_from": sections_var},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}
    return {
        "name": name,
        "step_type": "question",
        "config": {
            "message_config": {"message_type": "interactive", "interactive": interactive},
            "reply_config": {"save_to_variable": save_var, "expected_type": "interactive_id"},
        },
        "transitions": transitions,
    }


def _buttons_question(name, body, buttons, save_var, transitions, expected_type="interactive_id", header=None):
    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": bid, "title": title}} for bid, title in buttons
        ]},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    return {
        "name": name,
        "step_type": "question",
        "config": {
            "message_config": {"message_type": "interactive", "interactive": interactive},
            "reply_config": {"save_to_variable": save_var, "expected_type": expected_type},
        },
        "transitions": transitions,
    }


def _betting_action(name, betting_action, transitions, **params):
    action = {"action_type": "handle_betting_action", "betting_action": betting_action}
    action.update(params)
    return {
        "name": name,
        "step_type": "action",
        "config": {"actions_to_run": [action]},
        "transitions": transitions,
    }


def _text(name, body, transitions):
    return {
        "name": name,
        "step_type": "send_message",
        "config": {"message_type": "text", "text": {"body": body}},
        "transitions": transitions,
    }


def _eq(var, value):
    return {"type": "variable_equals", "variable_name": var, "value": value}


def _id(value):
    return {"type": "interactive_reply_id_equals", "value": value}


_ALWAYS = {"type": "always_true"}


def create_betting_flow():
    steps = [
        # ---------------------------------------------------------------- entry
        {
            "name": "ensure_account",
            "step_type": "action",
            "is_entry_point": True,
            "config": {"actions_to_run": [{"action_type": "create_account"}]},
            "transitions": [
                {"to_step": "main_menu", "priority": 1, "condition_config": _eq("account_creation_status", True)},
                {"to_step": "account_failed", "priority": 99, "condition_config": _ALWAYS},
            ],
        },
        # ------------------------------------------------------------ main menu
        _list_question(
            "main_menu",
            body="Welcome to *BetBlitz* ⚽\nWhat would you like to do?",
            button="Menu",
            sections_var="flow_context.__menu_sections",  # static, injected below
            save_var="menu_choice",
            header="BetBlitz",
            transitions=[
                {"to_step": "browse_reset", "condition_config": _id("menu:browse")},
                {"to_step": "do_my_bets", "condition_config": _id("menu:mybets")},
                {"to_step": "do_view_slip", "condition_config": _id("menu:slip")},
                {"to_step": "do_balance", "condition_config": _id("menu:balance")},
                {"to_step": "do_rg_menu", "condition_config": _id("menu:safer")},
            ],
        ),
        # -------------------------------------------------------- browse fixtures
        {
            "name": "browse_reset",
            "step_type": "action",
            "config": {"actions_to_run": [
                {"action_type": "set_context_variable", "variable_name": "fixtures_page", "value_template": "0"},
            ]},
            "transitions": [{"to_step": "do_browse", "condition_config": _ALWAYS}],
        },
        _betting_action(
            "do_browse", "browse_fixtures",
            transitions=[
                {"to_step": "no_fixtures", "priority": 1, "condition_config": _eq("fixtures_count", 0)},
                {"to_step": "show_fixtures", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _list_question(
            "show_fixtures",
            body="{{ flow_context.fixtures_body }}",
            button="Matches",
            sections_var="flow_context.fixtures_sections",
            save_var="selected_fixture",
            header="Upcoming Matches",
            transitions=[{"to_step": "route_fixture", "condition_config": _ALWAYS}],
        ),
        _betting_action(
            "route_fixture", "open_fixture",
            selection_template="{{ flow_context.selected_fixture }}",
            transitions=[
                {"to_step": "do_browse", "priority": 1, "condition_config": _eq("route", "rebrowse")},
                {"to_step": "show_markets", "priority": 2, "condition_config": _eq("route", "markets")},
                {"to_step": "fixture_no_markets", "priority": 3, "condition_config": _eq("route", "no_markets")},
                {"to_step": "show_fixtures", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _list_question(
            "show_markets",
            body="{{ flow_context.markets_body }}",
            button="Markets",
            sections_var="flow_context.markets_sections",
            save_var="selected_market",
            transitions=[{"to_step": "route_market", "condition_config": _ALWAYS}],
        ),
        _betting_action(
            "route_market", "open_market",
            selection_template="{{ flow_context.selected_market }}",
            transitions=[
                {"to_step": "show_outcomes", "priority": 1, "condition_config": _eq("route", "outcomes")},
                {"to_step": "market_error", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _list_question(
            "show_outcomes",
            body="{{ flow_context.outcomes_body }}",
            button="Options",
            sections_var="flow_context.outcomes_sections",
            save_var="selected_outcome",
            transitions=[{"to_step": "route_outcome", "condition_config": _ALWAYS}],
        ),
        _betting_action(
            "route_outcome", "select_outcome",
            selection_template="{{ flow_context.selected_outcome }}",
            transitions=[
                {"to_step": "after_add", "priority": 1, "condition_config": _eq("route", "added")},
                {"to_step": "show_outcomes", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _buttons_question(
            "after_add",
            body="{{ flow_context.slip_last_message }}\n\nWhat next?",
            buttons=[("add:more", "➕ Add more"), ("slip:done", "🧾 Slip / Stake"), ("nav:menu", "🏠 Menu")],
            save_var="after_add_choice",
            transitions=[
                {"to_step": "browse_reset", "condition_config": _id("add:more")},
                {"to_step": "do_view_slip", "condition_config": _id("slip:done")},
                {"to_step": "main_menu", "condition_config": _id("nav:menu")},
            ],
        ),
        # ---------------------------------------------------------------- slip
        _betting_action(
            "do_view_slip", "view_slip",
            transitions=[
                {"to_step": "show_slip", "priority": 1, "condition_config": _eq("route", "has_items")},
                {"to_step": "slip_empty", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _buttons_question(
            "show_slip",
            body="{{ flow_context.slip_summary }}",
            buttons=[("slip:stake", "💰 Set stake"), ("slip:clear", "🗑️ Clear slip"), ("nav:menu", "🏠 Menu")],
            save_var="slip_action",
            transitions=[
                {"to_step": "ask_stake", "condition_config": _id("slip:stake")},
                {"to_step": "do_clear_slip", "condition_config": _id("slip:clear")},
                {"to_step": "main_menu", "condition_config": _id("nav:menu")},
            ],
        ),
        _buttons_question(
            "ask_stake",
            body="How much would you like to stake?\nTap a quick amount or type any amount (e.g. 25).",
            buttons=[("stake:10", "$10"), ("stake:50", "$50"), ("stake:100", "$100")],
            save_var="stake_reply",
            expected_type="any",
            transitions=[{"to_step": "route_stake", "condition_config": _ALWAYS}],
        ),
        _betting_action(
            "route_stake", "set_stake",
            selection_template="{{ flow_context.stake_reply }}",
            stake_template="{{ flow_context.stake_reply }}",
            transitions=[
                {"to_step": "confirm_bet", "priority": 1, "condition_config": _eq("route", "confirm")},
                {"to_step": "ask_stake", "priority": 2, "condition_config": _eq("route", "invalid_stake")},
                {"to_step": "main_menu", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _buttons_question(
            "confirm_bet",
            body="{{ flow_context.bet_confirmation_message }}",
            buttons=[("bet:confirm", "✅ Place bet"), ("bet:cancel", "✖️ Cancel")],
            save_var="confirm_choice",
            header="Confirm your bet",
            transitions=[
                {"to_step": "do_place", "condition_config": _id("bet:confirm")},
                {"to_step": "bet_cancelled", "condition_config": _id("bet:cancel")},
            ],
        ),
        _betting_action(
            "do_place", "place_slip",
            transitions=[
                {"to_step": "place_success", "priority": 1, "condition_config": _eq("route", "placed")},
                {"to_step": "place_failed", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _text("place_success", "{{ flow_context.place_ticket_message }}",
              [{"to_step": "post_bet", "condition_config": _ALWAYS}]),
        _buttons_question(
            "post_bet",
            body="Anything else?",
            buttons=[("menu:browse", "⚽ More bets"), ("menu:mybets", "🎫 My bets"), ("nav:menu", "🏠 Menu")],
            save_var="post_bet_choice",
            transitions=[
                {"to_step": "browse_reset", "condition_config": _id("menu:browse")},
                {"to_step": "do_my_bets", "condition_config": _id("menu:mybets")},
                {"to_step": "main_menu", "condition_config": _id("nav:menu")},
            ],
        ),
        _text("place_failed", "❌ {{ flow_context.place_ticket_message }}",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        _betting_action("do_clear_slip", "clear_slip",
                        transitions=[{"to_step": "slip_cleared", "condition_config": _ALWAYS}]),
        _text("slip_cleared", "🧾 Your bet slip has been cleared.",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        _text("slip_empty", "🧾 Your bet slip is empty. Tap *Browse matches* to add a pick.",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        _text("bet_cancelled", "Your bet was cancelled. Your slip is still saved.",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        # -------------------------------------------------------------- my bets
        _betting_action(
            "do_my_bets", "my_bets",
            transitions=[
                {"to_step": "show_my_bets", "priority": 1, "condition_config": _eq("route", "has_bets")},
                {"to_step": "no_bets", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _list_question(
            "show_my_bets",
            body="Here are your recent bets. Tap one for details.",
            button="My bets",
            sections_var="flow_context.my_bets_sections",
            save_var="selected_ticket",
            header="My Bets",
            transitions=[{"to_step": "route_ticket", "condition_config": _ALWAYS}],
        ),
        _betting_action(
            "route_ticket", "view_ticket",
            selection_template="{{ flow_context.selected_ticket }}",
            transitions=[
                {"to_step": "show_ticket", "priority": 1, "condition_config": _eq("route", "shown")},
                {"to_step": "ticket_error", "priority": 99, "condition_config": _ALWAYS},
            ],
        ),
        _text("show_ticket", "{{ flow_context.ticket_detail_message }}",
              [{"to_step": "after_ticket", "condition_config": _ALWAYS}]),
        _buttons_question(
            "after_ticket",
            body="View another?",
            buttons=[("menu:mybets", "🎫 My bets"), ("nav:menu", "🏠 Menu")],
            save_var="after_ticket_choice",
            transitions=[
                {"to_step": "do_my_bets", "condition_config": _id("menu:mybets")},
                {"to_step": "main_menu", "condition_config": _id("nav:menu")},
            ],
        ),
        _text("no_bets", "{{ flow_context.my_bets_message }}",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        _text("ticket_error", "Sorry, that ticket could not be found.",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        # ------------------------------------------------- safer gambling (RG)
        _betting_action(
            "do_rg_menu", "rg_menu",
            transitions=[{"to_step": "show_rg_menu", "condition_config": _ALWAYS}],
        ),
        _list_question(
            "show_rg_menu",
            body="{{ flow_context.rg_summary }}",
            button="Options",
            sections_var="flow_context.__rg_sections",  # static, injected below
            save_var="rg_choice",
            header="Safer Gambling",
            transitions=[
                {"to_step": "ask_exclude", "condition_config": _id("rg:exclude")},
                {"to_step": "ask_deposit_limit", "condition_config": _id("rg:deplimit")},
                {"to_step": "ask_stake_limit", "condition_config": _id("rg:stakelimit")},
                {"to_step": "main_menu", "condition_config": _id("nav:menu")},
            ],
        ),
        _buttons_question(
            "ask_exclude",
            body="Take a break — you won't be able to bet or deposit during this period. Choose a length:",
            buttons=[("excl:1", "24 hours"), ("excl:7", "7 days"), ("excl:30", "30 days")],
            save_var="excl_choice",
            transitions=[{"to_step": "do_exclude", "condition_config": _ALWAYS}],
        ),
        _betting_action(
            "do_exclude", "rg_self_exclude",
            selection_template="{{ flow_context.excl_choice }}",
            transitions=[{"to_step": "show_rg_result", "condition_config": _ALWAYS}],
        ),
        {
            "name": "ask_deposit_limit",
            "step_type": "question",
            "config": {
                "message_config": {"message_type": "text",
                                   "text": {"body": "Enter your daily deposit limit in dollars (e.g. 100), or 0 to remove it:"}},
                "reply_config": {"save_to_variable": "deposit_limit_reply", "expected_type": "any"},
            },
            "transitions": [{"to_step": "do_deposit_limit", "condition_config": _ALWAYS}],
        },
        _betting_action(
            "do_deposit_limit", "rg_set_deposit_limit",
            selection_template="{{ flow_context.deposit_limit_reply }}",
            transitions=[{"to_step": "show_rg_result", "condition_config": _ALWAYS}],
        ),
        {
            "name": "ask_stake_limit",
            "step_type": "question",
            "config": {
                "message_config": {"message_type": "text",
                                   "text": {"body": "Enter your daily stake limit in dollars (e.g. 50), or 0 to remove it:"}},
                "reply_config": {"save_to_variable": "stake_limit_reply", "expected_type": "any"},
            },
            "transitions": [{"to_step": "do_stake_limit", "condition_config": _ALWAYS}],
        },
        _betting_action(
            "do_stake_limit", "rg_set_stake_limit",
            selection_template="{{ flow_context.stake_limit_reply }}",
            transitions=[{"to_step": "show_rg_result", "condition_config": _ALWAYS}],
        ),
        _text("show_rg_result", "{{ flow_context.rg_message }}",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        # -------------------------------------------------------------- balance
        _betting_action("do_balance", "check_wallet_balance",
                        transitions=[{"to_step": "show_balance", "condition_config": _ALWAYS}]),
        _text("show_balance", "{{ flow_context.check_wallet_balance_message }}",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        # ------------------------------------------------------- misc / errors
        _text("no_fixtures", "{{ flow_context.fixtures_body }}",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        _text("fixture_no_markets", "{{ flow_context.open_fixture_message }}",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        _text("market_error", "Sorry, that market has no options right now.",
              [{"to_step": "main_menu", "condition_config": _ALWAYS}]),
        _text("account_failed", "❌ We couldn't set up your account. {{ flow_context.account_creation_message }}",
              [{"to_step": "end_betting", "condition_config": _ALWAYS}]),
        {"name": "end_betting", "step_type": "end_flow",
         "config": {"message_config": {"message_type": "text",
                    "text": {"body": "Thanks for using BetBlitz! Reply *bet* any time. Good luck! 🍀"}}}},
    ]

    # The main menu is a fixed set of options; inject it as a static section so
    # the same _list_question helper (which expects sections_from) can render it.
    for step in steps:
        if step["name"] == "main_menu":
            action = step["config"]["message_config"]["interactive"]["action"]
            action.pop("sections_from", None)
            action["sections"] = [{
                "title": "Main menu",
                "rows": [
                    {"id": "menu:browse", "title": "⚽ Browse matches", "description": "See upcoming matches and odds"},
                    {"id": "menu:mybets", "title": "🎫 My bets", "description": "View your open and settled bets"},
                    {"id": "menu:slip", "title": "🧾 Bet slip", "description": "Review your current selections"},
                    {"id": "menu:balance", "title": "💰 Balance", "description": "Check your wallet balance"},
                    {"id": "menu:safer", "title": "🛡️ Safer gambling", "description": "Limits, breaks and self-exclusion"},
                ],
            }]
        if step["name"] == "show_rg_menu":
            action = step["config"]["message_config"]["interactive"]["action"]
            action.pop("sections_from", None)
            action["sections"] = [{
                "title": "Safer gambling",
                "rows": [
                    {"id": "rg:deplimit", "title": "💵 Deposit limit", "description": "Set a daily deposit limit"},
                    {"id": "rg:stakelimit", "title": "🎯 Stake limit", "description": "Set a daily stake limit"},
                    {"id": "rg:exclude", "title": "⏸️ Take a break", "description": "Self-exclude for a period"},
                    {"id": "nav:menu", "title": "🏠 Back to menu", "description": "Return to the main menu"},
                ],
            }]

    return {
        "name": "Betting Flow",
        "description": "Tap-driven BetBlitz betting: browse matches, build a slip, stake, confirm, place, and track bets.",
        "trigger_keywords": ["bet", "play", "ticket", "matches", "odds", "fixtures", "upcoming games", "my bets", "bet slip"],
        "is_active": True,
        "requires_login": True,
        "steps": steps,
    }
