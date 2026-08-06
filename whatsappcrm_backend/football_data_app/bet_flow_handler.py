# whatsappcrm_backend/football_data_app/bet_flow_handler.py
"""
Server logic for the native WhatsApp **Flow** betting journey (data_exchange).

The Meta Flow endpoint (meta_integration.views.WhatsAppFlowEndpointView) decrypts
each screen submission and calls into here. Each call returns the next screen and
its dynamic data:

    BROWSE  → pick a fixture   → MARKETS
    MARKETS → pick a market    → OUTCOMES
    OUTCOMES→ pick an outcome  → STAKE
    STAKE   → enter a stake    → CONFIRM
    CONFIRM → place the bet    → SUCCESS (terminal)

Selection state is threaded through the screen `data`/payloads (Flows are
stateless server-side), and `flow_token` is the contact's whatsapp_id, which
identifies the player. Placement reuses the exact
customer_data.ticket_processing validation — no bet logic is duplicated here.

Screen names are namespaced BET_* so the Flow endpoint can route them without
clashing with the login/register screens.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.utils import timezone

logger = logging.getLogger(__name__)

SCREENS = ('BET_BROWSE', 'BET_MARKETS', 'BET_OUTCOMES', 'BET_STAKE', 'BET_CONFIRM', 'BET_SUCCESS')
MAX_FLOW_OPTIONS = 20  # keep dropdowns comfortably within Meta's limits


def is_bet_screen(screen: str) -> bool:
    return bool(screen) and screen.startswith('BET_')


def _label(text, limit=30):
    text = (text or '').strip()
    return text if len(text) <= limit else text[: limit - 1] + '…'


def _err(screen, message):
    return {"screen": screen, "data": {"is_error": True, "error_message": message}}


def _fixtures_options():
    from .betting_ux import _bettable_fixtures_qs, _kickoff_label
    opts = []
    for fx in list(_bettable_fixtures_qs())[:MAX_FLOW_OPTIONS]:
        opts.append({
            "id": str(fx.id),
            "title": _label(f"{fx.home_team.name} v {fx.away_team.name}", 30),
            "description": _label(_kickoff_label(fx), 30),
        })
    return opts


def init_screen() -> dict:
    """The first screen shown when the Flow opens (INIT)."""
    fixtures = _fixtures_options()
    return {
        "screen": "BET_BROWSE",
        "data": {
            "fixtures": fixtures or [{"id": "none", "title": "No matches available", "description": ""}],
            "has_fixtures": bool(fixtures),
            "is_error": False,
            "error_message": "",
        },
    }


def _markets_screen(fixture_id):
    from .betting_ux import build_markets_screen
    scr = build_markets_screen(int(fixture_id))
    if not scr or not scr.get('has_markets'):
        return _err("BET_BROWSE", "That match has no open markets. Pick another.")
    fixture = scr['fixture']
    markets = [{"id": r['id'].split(':', 1)[1], "title": _label(r['title'], 30)}
               for r in scr['sections'][0]['rows']][:MAX_FLOW_OPTIONS]
    return {
        "screen": "BET_MARKETS",
        "data": {
            "fixture_id": str(fixture_id),
            "fixture_label": _label(f"{fixture.home_team.name} v {fixture.away_team.name}", 40),
            "markets": markets,
            "is_error": False, "error_message": "",
        },
    }


def _outcomes_screen(market_id):
    from .betting_ux import build_outcomes_screen
    scr = build_outcomes_screen(int(market_id))
    if not scr or not scr.get('has_outcomes'):
        return _err("BET_BROWSE", "That market has no options right now. Start again.")
    outcomes = [{"id": r['id'].split(':', 1)[1], "title": _label(r['title'] + ' · ' + r['description'].replace('Odds ', '@ '), 40)}
                for r in scr['sections'][0]['rows']][:MAX_FLOW_OPTIONS]
    return {
        "screen": "BET_OUTCOMES",
        "data": {
            "market_label": _label(scr['market'].category.name, 40),
            "outcomes": outcomes,
            "is_error": False, "error_message": "",
        },
    }


def _stake_screen(outcome_id, flow_token):
    from .models import MarketOutcome
    from customer_data.models import CustomerProfile, UserWallet
    from conversations.models import Contact
    outcome = (MarketOutcome.objects.filter(id=int(outcome_id), is_active=True)
               .select_related('market__fixture__home_team', 'market__fixture__away_team', 'market__category').first())
    if not outcome:
        return _err("BET_BROWSE", "That selection is no longer available. Start again.")
    fx = outcome.market.fixture
    balance = "0.00"
    contact = Contact.objects.filter(whatsapp_id=flow_token).first()
    if contact:
        profile = CustomerProfile.objects.filter(contact=contact, user__isnull=False).select_related('user').first()
        if profile:
            wallet, _ = UserWallet.objects.get_or_create(user=profile.user)
            balance = f"{wallet.balance:.2f}"
    selection = f"{fx.home_team.name} v {fx.away_team.name} — {outcome.outcome_name} @ {outcome.odds:.2f}"
    return {
        "screen": "BET_STAKE",
        "data": {
            "outcome_id": str(outcome_id),
            "selection_label": _label(selection, 60),
            "odds": f"{outcome.odds:.2f}",
            "balance": balance,
            "is_error": False, "error_message": "",
        },
    }


def _confirm_screen(outcome_id, stake):
    from .models import MarketOutcome
    try:
        stake_val = Decimal(str(stake))
    except (InvalidOperation, TypeError):
        return _err("BET_STAKE", "Enter a valid stake amount.")
    if stake_val <= 0:
        return _err("BET_STAKE", "Stake must be greater than zero.")
    outcome = MarketOutcome.objects.filter(id=int(outcome_id), is_active=True).select_related(
        'market__fixture__home_team', 'market__fixture__away_team').first()
    if not outcome:
        return _err("BET_BROWSE", "That selection is no longer available. Start again.")
    fx = outcome.market.fixture
    payout = stake_val * outcome.odds
    summary = (f"{fx.home_team.name} v {fx.away_team.name}\n"
               f"{outcome.outcome_name} @ {outcome.odds:.2f}\n"
               f"Stake: ${stake_val:.2f}\nPotential payout: ${payout:.2f}")
    return {
        "screen": "BET_CONFIRM",
        "data": {
            "outcome_id": str(outcome_id),
            "stake": f"{stake_val:.2f}",
            "summary": summary,
            "is_error": False, "error_message": "",
        },
    }


def _place(outcome_id, stake, flow_token):
    from customer_data.ticket_processing import process_bet_ticket_submission
    result = process_bet_ticket_submission(
        whatsapp_id=flow_token, market_outcome_ids=[str(outcome_id)], stake=float(stake))
    if result.get('success'):
        return {"screen": "BET_SUCCESS", "data": {"message": result.get('message', 'Bet placed!')}}
    # Stay on confirm with the reason (funds/limits/status).
    return {"screen": "BET_CONFIRM", "data": {
        "outcome_id": str(outcome_id), "stake": str(stake),
        "summary": result.get('message', 'Could not place the bet.'),
        "is_error": True, "error_message": result.get('message', 'Could not place the bet.')}}


def handle_data_exchange(screen: str, data: dict, flow_token: str) -> dict:
    """Route a betting-Flow screen submission to the next screen."""
    data = data or {}
    logger.info(f"Bet Flow data_exchange: screen={screen}")
    if screen == 'BET_BROWSE':
        fid = data.get('fixture_id')
        if not fid or fid == 'none':
            return _err("BET_BROWSE", "Please choose a match.")
        return _markets_screen(fid)
    if screen == 'BET_MARKETS':
        mid = data.get('market_id')
        if not mid:
            return _err("BET_MARKETS", "Please choose a market.")
        return _outcomes_screen(mid)
    if screen == 'BET_OUTCOMES':
        oid = data.get('outcome_id')
        if not oid:
            return _err("BET_OUTCOMES", "Please choose an option.")
        return _stake_screen(oid, flow_token)
    if screen == 'BET_STAKE':
        return _confirm_screen(data.get('outcome_id'), data.get('stake'))
    if screen == 'BET_CONFIRM':
        return _place(data.get('outcome_id'), data.get('stake'), flow_token)
    return _err("BET_BROWSE", "Something went wrong. Start again.")
