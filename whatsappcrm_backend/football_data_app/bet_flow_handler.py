# whatsappcrm_backend/football_data_app/bet_flow_handler.py
"""
Server logic for the native WhatsApp **Flow** betting hub (data_exchange).

The Meta Flow endpoint (meta_integration.views.WhatsAppFlowEndpointView) decrypts
each screen submission and calls into here. The Flow opens on a menu and folds
the whole BetBlitz experience into native WhatsApp UI:

    BET_MENU ─┬─ Place a bet → BROWSE → MARKETS → OUTCOMES ─┬─ (single) STAKE → CONFIRM → SUCCESS
              │                                             └─ (add)    → SLIP
              ├─ Bet slip / accumulator → SLIP → SUCCESS / DONE (cleared)
              ├─ My bets → MYBETS → DONE (ticket detail)
              ├─ My balance → DONE
              └─ Safer gambling → SAFER → DONE

Meta requires routing_model to be a forward-only DAG (no cycles, not even a
direct A<->B pair) — the Flow client rejects any data_exchange response whose
`screen` isn't a declared forward target of the CURRENT screen with
"could not switch to the requested section". Two consequences drive this file:

  1. Error recovery never jumps to an earlier screen (e.g. BET_MARKETS can't
     fall back to BET_BROWSE) — it always stays on the screen the client is
     currently displaying (a self-return is never a "switch").
  2. "Keep browsing to add another leg" from BET_SLIP is architecturally
     impossible via a server-issued screen jump, since BET_BROWSE already has
     a forward path into BET_SLIP (via MARKETS/OUTCOMES) — declaring the
     reverse edge would create a cycle. Users add more legs via the Flow's own
     native back button (client-side, no data_exchange call), so the running
     **bet slip** is persisted server-side (Redis, keyed by flow_token) rather
     than trusted solely from the client-echoed `data.slip` — otherwise a leg
     added after the client cached an older screen would be silently lost the
     next time that stale screen is resubmitted.

Odds and labels are always re-derived from the database, and placement
re-fetches odds server-side, so a tampered slip payload can never change the
price of a bet.

`flow_token` is the contact's whatsapp_id, which identifies the player. All bet
rules (funds/age/limits/odds) are reused from customer_data.ticket_processing;
safer-gambling controls from customer_data.compliance; balance from
customer_data.utils — no bet or compliance logic is duplicated here.

Screen names are namespaced BET_* so the Flow endpoint can route them without
clashing with the login/register screens.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

SCREENS = ('BET_MENU', 'BET_BROWSE', 'BET_MARKETS', 'BET_OUTCOMES', 'BET_STAKE',
           'BET_CONFIRM', 'BET_SUCCESS', 'BET_SLIP', 'BET_MYBETS', 'BET_SAFER', 'BET_DONE')
MAX_FLOW_OPTIONS = 20  # keep dropdowns comfortably within Meta's limits
SLIP_TTL_SECONDS = 1800  # 30 minutes — matches typical WhatsApp Flow session lifetimes

# Static option lists for this Flow's four small, fixed menus. These are
# imported into flows/definitions/bet_whatsapp_flow.py and inlined as literal
# `data-source` arrays in the screen JSON at publish time, NOT resolved from
# screen `data` per-request -- every RadioButtonsGroup/Dropdown bound to a
# *dynamic* data-source (`"${data.X}"`) in this Flow submitted with no value
# at all, on every device tested, regardless of component type or item schema
# (see git history on this file and on bet_whatsapp_flow.py for the full
# trail). A static data-source is a genuinely different code path per Meta's
# Flow JSON docs. The genuinely variable-length lists (fixtures/markets/
# outcomes/tickets) can't be static and remain dynamic.
#
# Every item needs a non-blank "description" -- Meta's publish-time validator
# rejects a static data-source item with an empty string ("Property
# 'description' should not be blank or an empty string", PATTERN_MISMATCH).
# The dynamic dropdowns elsewhere in this Flow got away with omitting/blanking
# it because Meta can only validate the *declared schema* of a "${data.X}"
# reference at publish time, not runtime values -- a static array's actual
# content is checked directly.
#
# No emoji in these titles. This is the only static list whose titles ever
# had emoji, and BET_MENU is the only screen actually reached in production
# so far -- every attempt (RadioButtonsGroup, Dropdown, static data-source,
# non-blank descriptions) still submitted with the "action" key entirely
# absent from the payload. Untested until now: whether an emoji in a
# data-source item's "title", specifically inside a native Flow's own
# RadioButtonsGroup/Dropdown rendering (a different client code path from
# the plain WhatsApp interactive list messages elsewhere in this bot, where
# the identical emoji render and submit fine), breaks the client's binding
# of that item's value.
MENU_ITEMS = [
    {"id": "browse", "title": "Place a bet", "description": "See upcoming matches and odds"},
    {"id": "slip", "title": "Bet slip", "description": "Review your current selections"},
    {"id": "mybets", "title": "My bets", "description": "View your open and settled bets"},
    {"id": "balance", "title": "My balance", "description": "Check your wallet balance"},
    {"id": "safer", "title": "Safer gambling", "description": "Limits, breaks and self-exclusion"},
]
MENU_MODES = [
    {"id": "bet_now", "title": "Bet this now", "description": "Place this single selection immediately"},
    {"id": "add_slip", "title": "Add to slip & keep browsing", "description": "Build an accumulator with more legs"},
]
# No "add another selection" entry: Meta's routing model can't legally route
# BET_SLIP back into the browse chain (see module docstring). Users add more
# legs with the Flow's native back button instead.
SLIP_ACTIONS = [
    {"id": "place", "title": "Place bet", "description": "Submit your slip as a bet"},
    {"id": "clear", "title": "Clear slip", "description": "Remove all selections"},
]
SAFER_ACTIONS = [
    {"id": "exclude_1", "title": "Take a 1-day break", "description": "Pause betting for 1 day"},
    {"id": "exclude_7", "title": "Self-exclude 7 days", "description": "Pause betting for 7 days"},
    {"id": "exclude_30", "title": "Self-exclude 30 days", "description": "Pause betting for 30 days"},
    {"id": "deposit_limit", "title": "Set daily deposit limit ($)", "description": "Cap how much you can deposit per day"},
    {"id": "stake_limit", "title": "Set daily stake limit ($)", "description": "Cap how much you can stake per day"},
]


def is_bet_screen(screen: str) -> bool:
    return bool(screen) and screen.startswith('BET_')


def _label(text, limit=30):
    text = (text or '').strip()
    return text if len(text) <= limit else text[: limit - 1] + '…'


def _err(screen, message, extra=None):
    # `extra` is typically a screen builder's own ['data'] dict, which always
    # carries its own is_error=False/error_message="" -- applying it after the
    # error fields would silently clobber them back to "no error", leaving the
    # Flow stuck on the same screen with no explanation shown to the user.
    data = dict(extra) if extra else {}
    data["is_error"] = True
    data["error_message"] = message
    return {"screen": screen, "data": data}


# --------------------------------------------------------------------------- #
#  Player / wallet helpers                                                     #
# --------------------------------------------------------------------------- #

def _user_for(flow_token):
    """Resolve the Django user behind a flow_token (whatsapp_id), or None."""
    from customer_data.models import CustomerProfile
    from conversations.models import Contact
    contact = Contact.objects.filter(whatsapp_id=flow_token).first()
    if not contact:
        return None
    profile = (CustomerProfile.objects.filter(contact=contact, user__isnull=False)
               .select_related('user').first())
    return profile.user if profile else None


def _balance_str(flow_token) -> str:
    from customer_data.utils import get_customer_wallet_balance
    res = get_customer_wallet_balance(flow_token)
    return f"{float(res.get('balance') or 0):.2f}"


# --------------------------------------------------------------------------- #
#  Bet slip: server-persisted (Redis), keyed by flow_token                     #
# --------------------------------------------------------------------------- #
# Flows are stateless on Meta's side and the client only supports FORWARD
# navigation via data_exchange, so a user builds a multi-leg accumulator by
# submitting a leg (→ BET_SLIP), then tapping the Flow's native back button to
# return to a screen the client already has cached, and submitting again.
# That cached screen's `data.slip` reflects the slip as of when it was last
# fetched from the server — it does NOT include legs added afterwards on
# BET_SLIP. Storing the authoritative slip server-side (rather than trusting
# only the client echo) means resubmitting from a stale cached screen still
# merges onto the up-to-date slip instead of silently dropping newer legs.

_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is None:
        import redis
        from django.conf import settings
        url = getattr(settings, 'CELERY_BROKER_URL', None) or 'redis://localhost:6379/0'
        _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


def _slip_cache_key(flow_token) -> str:
    return f"betslip:{flow_token}"


def _parse_slip(slip_str) -> list[int]:
    ids = []
    for part in str(slip_str or '').split(','):
        part = part.strip()
        if part.isdigit():
            iv = int(part)
            if iv not in ids:
                ids.append(iv)
    return ids


def _slip_str(ids) -> str:
    return ','.join(str(i) for i in ids)


def _load_server_slip(flow_token) -> list[int]:
    if not flow_token:
        return []
    try:
        raw = _redis().get(_slip_cache_key(flow_token))
    except Exception:
        logger.warning("Bet Flow: Redis unavailable for slip persistence; using client-echoed slip only.", exc_info=True)
        return []
    return _parse_slip(raw) if raw else []


def _save_server_slip(flow_token, ids) -> None:
    if not flow_token:
        return
    key = _slip_cache_key(flow_token)
    try:
        if ids:
            _redis().set(key, _slip_str(ids), ex=SLIP_TTL_SECONDS)
        else:
            _redis().delete(key)
    except Exception:
        logger.warning("Bet Flow: Redis unavailable for slip persistence; slip may not survive stale-screen navigation.", exc_info=True)


def _current_slip_ids(flow_token, slip_str_from_client='') -> list[int]:
    """The authoritative slip: server-stored legs merged with whatever the
    client just echoed, so a stale cached screen never drops an already-added
    leg. Persists the merge back so it becomes the new baseline."""
    server_ids = _load_server_slip(flow_token)
    client_ids = _parse_slip(slip_str_from_client)
    merged = list(server_ids)
    for i in client_ids:
        if i not in merged:
            merged.append(i)
    if merged != server_ids:
        _save_server_slip(flow_token, merged)
    return merged


def _slip_items(ids):
    """Rebuild the betting_ux slip (list of dicts) from outcome ids, in order."""
    from . import betting_ux as ux
    from .models import MarketOutcome
    outcomes = (MarketOutcome.objects.filter(id__in=ids, is_active=True)
                .select_related('market__fixture__home_team', 'market__fixture__away_team', 'market__category'))
    by_id = {o.id: o for o in outcomes}
    slip = []
    for i in ids:
        o = by_id.get(int(i))
        if o:
            slip, _added, _msg = ux.slip_add(slip, o)
    return slip


# --------------------------------------------------------------------------- #
#  Screen builders                                                             #
# --------------------------------------------------------------------------- #

def _menu_screen(flow_token, slip_str='', message=''):
    ids = _current_slip_ids(flow_token, slip_str)
    n = len(ids)
    if not message:
        message = (f"What would you like to do? You have {n} selection{'s' if n != 1 else ''} "
                    f"in your bet slip." if n else "What would you like to do?")
    return {
        "screen": "BET_MENU",
        "data": {
            "slip": _slip_str(ids),
            "message": message,
            "is_error": False, "error_message": " ",
        },
    }


# Fixtures beyond a single dropdown's worth are reached by paging rather
# than crammed into one list: MAX_FLOW_OPTIONS caps *all* dropdown items
# (Meta's practical limit), so up to 2 of those slots are reserved for
# "More matches" / "Previous matches" nav rows whenever a page needs them,
# leaving FIXTURES_PAGE_SIZE for actual fixtures. The 'more:<n>'/'prev:<n>'
# ids are sentinels: the BET_BROWSE handler recognises them and re-renders
# BET_BROWSE at that page (a self-return, not a screen switch -- Meta's
# forward-only routing model only constrains switching to a *different*
# declared screen) instead of treating them as a real fixture_id.
FIXTURES_PAGE_SIZE = MAX_FLOW_OPTIONS - 2


def _fixtures_options(page=0):
    from .betting_ux import _bettable_fixtures_qs, _kickoff_label
    page = max(0, int(page or 0))
    qs = list(_bettable_fixtures_qs())
    start = page * FIXTURES_PAGE_SIZE
    page_fixtures = qs[start:start + FIXTURES_PAGE_SIZE]
    has_more = len(qs) > start + FIXTURES_PAGE_SIZE

    opts = []
    if page > 0:
        opts.append({"id": f"prev:{page - 1}", "title": "⬅️ Previous matches",
                     "description": "See the previous page of fixtures"})
    for fx in page_fixtures:
        opts.append({
            "id": str(fx.id),
            "title": _label(f"{fx.home_team.name} v {fx.away_team.name}", 30),
            "description": _label(_kickoff_label(fx), 30),
        })
    if has_more:
        opts.append({"id": f"more:{page + 1}", "title": "➡️ More matches",
                     "description": "See the next page of fixtures"})
    return opts


def _browse_screen(flow_token, slip_str='', page=0):
    fixtures = _fixtures_options(page=page)
    return {
        "screen": "BET_BROWSE",
        "data": {
            "slip": _slip_str(_current_slip_ids(flow_token, slip_str)),
            "fixtures": fixtures or [{"id": "none", "title": "No matches available",
                                       "description": "Check back closer to kickoff"}],
            "has_fixtures": bool(fixtures),
            "is_error": False, "error_message": " ",
        },
    }


def init_screen(flow_token=None) -> dict:
    """The first screen shown when the Flow opens (INIT): the betting hub menu.
    Starts each session with a fresh (empty) slip."""
    _save_server_slip(flow_token, [])
    return _menu_screen(flow_token, '')


def _markets_screen(fixture_id, flow_token, slip_str=''):
    """Build the BET_MARKETS screen for a fixture, or None if it can't be built."""
    from .betting_ux import build_markets_screen
    scr = build_markets_screen(int(fixture_id))
    if not scr or not scr.get('has_markets'):
        return None
    fixture = scr['fixture']
    markets = [{"id": r['id'].split(':', 1)[1], "title": _label(r['title'], 30)}
               for r in scr['sections'][0]['rows']][:MAX_FLOW_OPTIONS]
    return {
        "screen": "BET_MARKETS",
        "data": {
            "slip": _slip_str(_current_slip_ids(flow_token, slip_str)),
            "fixture_id": str(fixture_id),
            "fixture_label": _label(f"{fixture.home_team.name} v {fixture.away_team.name}", 40),
            "markets": markets,
            "is_error": False, "error_message": " ",
        },
    }


def _outcomes_screen(market_id, flow_token, slip_str=''):
    """Build the BET_OUTCOMES screen for a market, or None if it can't be built."""
    from .betting_ux import build_outcomes_screen
    scr = build_outcomes_screen(int(market_id))
    if not scr or not scr.get('has_outcomes'):
        return None
    outcomes = [{"id": r['id'].split(':', 1)[1],
                 "title": _label(r['title'] + ' · ' + r['description'].replace('Odds ', '@ '), 40)}
                for r in scr['sections'][0]['rows']][:MAX_FLOW_OPTIONS]
    return {
        "screen": "BET_OUTCOMES",
        "data": {
            "slip": _slip_str(_current_slip_ids(flow_token, slip_str)),
            "market_label": _label(scr['market'].category.name, 40),
            "outcomes": outcomes,
            "is_error": False, "error_message": " ",
        },
    }


def _stake_screen(outcome_id, flow_token, slip_str=''):
    """Build the BET_STAKE screen for an outcome, or None if it can't be built."""
    from .models import MarketOutcome
    outcome = (MarketOutcome.objects.filter(id=int(outcome_id), is_active=True)
               .select_related('market__fixture__home_team', 'market__fixture__away_team', 'market__category').first())
    if not outcome:
        return None
    fx = outcome.market.fixture
    selection = f"{fx.home_team.name} v {fx.away_team.name} — {outcome.outcome_name} @ {outcome.odds:.2f}"
    return {
        "screen": "BET_STAKE",
        "data": {
            "slip": _slip_str(_current_slip_ids(flow_token, slip_str)),
            "outcome_id": str(outcome_id),
            "selection_label": _label(selection, 60),
            "odds": f"{outcome.odds:.2f}",
            "balance": _balance_str(flow_token),
            "is_error": False, "error_message": " ",
        },
    }


def _confirm_screen(outcome_id, stake, flow_token, slip_str=''):
    """Build the BET_CONFIRM screen, or None if the outcome can't be found
    (validation errors instead re-render BET_STAKE, the current screen)."""
    def _reshow_stake(msg):
        rebuilt = _stake_screen(outcome_id, flow_token, slip_str)
        if not rebuilt:
            return None
        rebuilt['data']['is_error'] = True
        rebuilt['data']['error_message'] = msg
        return rebuilt

    from .models import MarketOutcome
    try:
        stake_val = Decimal(str(stake))
    except (InvalidOperation, TypeError):
        return _reshow_stake("Enter a valid stake amount.")
    if stake_val <= 0:
        return _reshow_stake("Stake must be greater than zero.")
    outcome = MarketOutcome.objects.filter(id=int(outcome_id), is_active=True).select_related(
        'market__fixture__home_team', 'market__fixture__away_team').first()
    if not outcome:
        return None
    fx = outcome.market.fixture
    payout = stake_val * outcome.odds
    summary = (f"{fx.home_team.name} v {fx.away_team.name}\n"
               f"{outcome.outcome_name} @ {outcome.odds:.2f}\n"
               f"Stake: ${stake_val:.2f}\nPotential payout: ${payout:.2f}")
    return {
        "screen": "BET_CONFIRM",
        "data": {
            "slip": _slip_str(_current_slip_ids(flow_token, slip_str)),
            "outcome_id": str(outcome_id),
            "stake": f"{stake_val:.2f}",
            "summary": summary,
            "is_error": False, "error_message": " ",
        },
    }


def _slip_screen(flow_token, slip_str='', stake=None, message=''):
    from . import betting_ux as ux
    ids = _current_slip_ids(flow_token, slip_str)
    slip = _slip_items(ids)
    # Keep the canonical id order/validity (drops any that went inactive) and
    # persist the pruned list so a stale/inactive leg doesn't linger forever.
    ids = [int(i) for i in ux.slip_outcome_ids(slip)]
    _save_server_slip(flow_token, ids)
    if not slip:
        summary = "🧾 Your bet slip is empty.\n\nChoose *Place a bet*, pick a selection, then *Add to slip* to build an accumulator."
    else:
        summary = ux.slip_summary_text(slip, float(stake) if stake else None)
        summary += "\n\nWant to add another match? Tap the ← back arrow (top-left) to browse, then *Add to slip* again."
    return {
        "screen": "BET_SLIP",
        "data": {
            "slip": _slip_str(ids),
            "summary": message + ("\n\n" if message else "") + summary if message else summary,
            "has_slip": bool(slip),
            "is_error": False, "error_message": " ",
        },
    }


def _done_screen(message, heading="Done"):
    return {
        "screen": "BET_DONE",
        "data": {"heading": heading, "message": message[:4000]},
    }


def _mybets_screen(flow_token, slip_str=''):
    from customer_data.models import BetTicket
    user = _user_for(flow_token)
    if not user:
        return _done_screen("You need an account to view your bets. Type 'login' to sign in.", heading="My bets")
    OPEN_STATUSES = ('PENDING', 'PLACED')
    # Open bets first (regardless of recency) so a still-live bet can't be
    # bumped out of the dropdown's MAX_FLOW_OPTIONS window by more recently
    # settled ones -- the native Flow's single dropdown has no equivalent of
    # the conversational flow's sectioned "Open bets"/"Settled bets" lists.
    tickets = list(
        BetTicket.objects.filter(user=user, status__in=OPEN_STATUSES).order_by('-created_at')
    ) + list(
        BetTicket.objects.filter(user=user).exclude(status__in=OPEN_STATUSES).order_by('-created_at')
    )
    tickets = tickets[:MAX_FLOW_OPTIONS]
    if not tickets:
        return _done_screen("You have no bets yet. Choose *Place a bet* to get started!", heading="My bets")
    emoji = {'WON': '✅', 'LOST': '❌', 'PLACED': '⏳', 'PENDING': '⏳', 'REFUNDED': '↩️'}
    options = []
    for t in tickets:
        options.append({
            "id": str(t.id),
            "title": _label(f"#{t.id} · ${float(t.total_stake):.2f} · {t.get_status_display()}", 30),
            "description": _label(f"{emoji.get(t.status, '•')} win ${float(t.potential_winnings):.2f}", 30),
        })
    return {
        "screen": "BET_MYBETS",
        "data": {
            "slip": _slip_str(_current_slip_ids(flow_token, slip_str)),
            "tickets": options,
            "is_error": False, "error_message": " ",
        },
    }


def _ticket_detail(flow_token, ticket_id):
    from customer_data.models import BetTicket
    user = _user_for(flow_token)
    if not user:
        return _done_screen("You need an account to view that ticket.", heading="My bets")
    try:
        ticket = (BetTicket.objects.filter(user=user, id=int(ticket_id))
                  .prefetch_related('bets__market_outcome__market__fixture__home_team',
                                    'bets__market_outcome__market__fixture__away_team',
                                    'bets__market_outcome__market__category').first())
    except (TypeError, ValueError):
        ticket = None
    if not ticket:
        return _done_screen("That ticket could not be found.", heading="My bets")
    emoji = {'WON': '✅', 'LOST': '❌', 'PLACED': '⏳', 'PENDING': '⏳', 'REFUNDED': '↩️'}.get(ticket.status, '•')
    lines = [
        f"🎫 Ticket #{ticket.id} {emoji} {ticket.get_status_display()}",
        f"Type: {ticket.get_bet_type_display()}",
        f"Stake: ${float(ticket.total_stake):.2f}",
        f"Combined odds: {float(ticket.total_odds):.2f}",
        f"Potential payout: ${float(ticket.potential_winnings):.2f}",
        "", "Selections:",
    ]
    for bet in ticket.bets.all():
        fx = bet.market_outcome.market.fixture
        lines.append(f"• {fx.home_team.name} v {fx.away_team.name}")
        lines.append(f"   {bet.market_outcome.market.category.name}: "
                     f"{bet.market_outcome.outcome_name} @ {float(bet.market_outcome.odds):.2f} "
                     f"({bet.get_status_display()})")
    return _done_screen("\n".join(lines), heading=f"Ticket #{ticket.id}")


def _safer_screen(flow_token, message=''):
    from customer_data import compliance
    user = _user_for(flow_token)
    if not user:
        return _done_screen("You need an account to manage safer-gambling settings.", heading="Safer gambling")
    summary = compliance.limits_summary(user)
    return {
        "screen": "BET_SAFER",
        "data": {
            "summary": (message + "\n\n" + summary) if message else summary,
            "is_error": False, "error_message": " ",
        },
    }


# --------------------------------------------------------------------------- #
#  Placement                                                                   #
# --------------------------------------------------------------------------- #

def _place_single(outcome_id, stake, flow_token, slip_str=''):
    from customer_data.ticket_processing import process_bet_ticket_submission
    result = process_bet_ticket_submission(
        whatsapp_id=flow_token, market_outcome_ids=[str(outcome_id)], stake=float(stake))
    if result.get('success'):
        return {"screen": "BET_SUCCESS", "data": {"message": result.get('message', 'Bet placed!')}}
    return {"screen": "BET_CONFIRM", "data": {
        "slip": _slip_str(_current_slip_ids(flow_token, slip_str)),
        "outcome_id": str(outcome_id), "stake": str(stake),
        "summary": result.get('message', 'Could not place the bet.'),
        "is_error": True, "error_message": result.get('message', 'Could not place the bet.')}}


def _place_slip(slip_str, stake, flow_token):
    from customer_data.ticket_processing import process_bet_ticket_submission
    from . import betting_ux as ux
    ids = _current_slip_ids(flow_token, slip_str)
    slip = _slip_items(ids)
    outcome_ids = ux.slip_outcome_ids(slip)
    if not outcome_ids:
        return _slip_screen(flow_token, '', message="Your bet slip is empty.")
    try:
        stake_val = Decimal(str(stake))
    except (InvalidOperation, TypeError):
        return _slip_screen(flow_token, _slip_str([int(i) for i in outcome_ids]), message="Enter a valid stake amount.")
    if stake_val <= 0:
        return _slip_screen(flow_token, _slip_str([int(i) for i in outcome_ids]), message="Stake must be greater than zero.")
    result = process_bet_ticket_submission(
        whatsapp_id=flow_token, market_outcome_ids=outcome_ids, stake=float(stake_val))
    if result.get('success'):
        _save_server_slip(flow_token, [])
        return {"screen": "BET_SUCCESS", "data": {"message": result.get('message', 'Bet placed!')}}
    return _slip_screen(flow_token, _slip_str([int(i) for i in outcome_ids]), stake=float(stake_val),
                        message=result.get('message', 'Could not place the accumulator.'))


# --------------------------------------------------------------------------- #
#  Dispatch                                                                    #
# --------------------------------------------------------------------------- #
# Every fallback below stays on the CURRENT screen (never a "switch") because
# Meta's routing model is a forward-only DAG — see module docstring.

def handle_data_exchange(screen: str, data: dict, flow_token: str) -> dict:
    """Route a betting-Flow screen submission to the next screen."""
    data = data or {}
    slip_str = data.get('slip', '')
    logger.info(f"Bet Flow data_exchange: screen={screen}")

    if screen == 'BET_MENU':
        action = data.get('menu_action')
        if action == 'browse':
            return _browse_screen(flow_token, slip_str)
        if action == 'slip':
            return _slip_screen(flow_token, slip_str)
        if action == 'mybets':
            return _mybets_screen(flow_token, slip_str)
        if action == 'balance':
            return _done_screen(f"💰 Your balance is *${_balance_str(flow_token)}*.", heading="My balance")
        if action == 'safer':
            return _safer_screen(flow_token)
        return _err("BET_MENU", "Please choose an option.", extra=_menu_screen(flow_token, slip_str)['data'])

    if screen == 'BET_BROWSE':
        fid = data.get('fixture_id')
        if fid and (fid.startswith('more:') or fid.startswith('prev:')):
            try:
                target_page = int(fid.split(':', 1)[1])
            except (TypeError, ValueError):
                target_page = 0
            return _browse_screen(flow_token, slip_str, page=target_page)
        if not fid or fid == 'none':
            return _err("BET_BROWSE", "Please choose a match.", extra=_browse_screen(flow_token, slip_str)['data'])
        result = _markets_screen(fid, flow_token, slip_str)
        if result is None:
            return _err("BET_BROWSE", "That match has no open markets. Pick another.",
                        extra=_browse_screen(flow_token, slip_str)['data'])
        return result

    if screen == 'BET_MARKETS':
        mid = data.get('market_id')
        if not mid:
            return _err("BET_MARKETS", "Please choose a market.",
                        extra={"fixture_id": "", "fixture_label": "", "markets": [],
                               "slip": _slip_str(_current_slip_ids(flow_token, slip_str))})
        result = _outcomes_screen(mid, flow_token, slip_str)
        if result is None:
            # Meta's routing model doesn't allow jumping back to BET_BROWSE from
            # here — stay on BET_MARKETS (the current screen) and have the user
            # pick a different market or restart.
            return _err("BET_MARKETS", "That market has no options right now. Please choose a "
                        "different market, or type 'bet' to start over.",
                        extra={"fixture_id": "", "fixture_label": "", "markets": [],
                               "slip": _slip_str(_current_slip_ids(flow_token, slip_str))})
        return result

    if screen == 'BET_OUTCOMES':
        oid = data.get('outcome_id')
        if not oid:
            return _err("BET_OUTCOMES", "Please choose an option.",
                        extra={"market_label": "", "outcomes": [],
                               "slip": _slip_str(_current_slip_ids(flow_token, slip_str))})
        mode = data.get('mode') or 'bet_now'
        if mode == 'add_slip':
            ids = _current_slip_ids(flow_token, slip_str)
            if int(oid) not in ids:
                ids.append(int(oid))
                _save_server_slip(flow_token, ids)
            return _slip_screen(flow_token, _slip_str(ids), message="✅ Added to your slip.")
        result = _stake_screen(oid, flow_token, slip_str)
        if result is None:
            # Can't jump back to BET_BROWSE either — stay on BET_OUTCOMES.
            return _err("BET_OUTCOMES", "That selection is no longer available. Please choose "
                        "another, or type 'bet' to start over.",
                        extra={"market_label": "", "outcomes": [],
                               "slip": _slip_str(_current_slip_ids(flow_token, slip_str))})
        return result

    if screen == 'BET_STAKE':
        result = _confirm_screen(data.get('outcome_id'), data.get('stake'), flow_token, slip_str)
        if result is None:
            return _err("BET_STAKE", "That selection is no longer available. Please type 'bet' to start over.",
                        extra={"outcome_id": data.get('outcome_id') or '', "selection_label": "",
                               "odds": "0.00", "balance": _balance_str(flow_token),
                               "slip": _slip_str(_current_slip_ids(flow_token, slip_str))})
        return result

    if screen == 'BET_CONFIRM':
        return _place_single(data.get('outcome_id'), data.get('stake'), flow_token, slip_str)

    if screen == 'BET_SLIP':
        nxt = data.get('slip_action') or 'place'
        if nxt == 'clear':
            _save_server_slip(flow_token, [])
            return _done_screen("🧾 Your bet slip has been cleared. Type 'bet' to start again.", heading="Bet slip")
        return _place_slip(slip_str, data.get('stake'), flow_token)

    if screen == 'BET_MYBETS':
        tid = data.get('ticket_id')
        if not tid:
            return _err("BET_MYBETS", "Please choose a ticket.")
        return _ticket_detail(flow_token, tid)

    if screen == 'BET_SAFER':
        return _handle_safer(data, flow_token)

    return _menu_screen(flow_token, slip_str)


def _handle_safer(data, flow_token):
    from customer_data import compliance
    user = _user_for(flow_token)
    if not user:
        return _done_screen("You need an account to manage safer-gambling settings.", heading="Safer gambling")
    action = data.get('safer_action')
    if not action:
        return _err("BET_SAFER", "Please choose an option.", extra=_safer_screen(flow_token)['data'])
    if action in ('exclude_1', 'exclude_7', 'exclude_30'):
        days = int(action.split('_', 1)[1])
        compliance.set_self_exclusion(user, days)
        return _done_screen(
            f"🛡️ You have been self-excluded for {days} day(s). Betting and deposits are blocked "
            f"during this time. Take care.", heading="Safer gambling")
    # deposit_limit / stake_limit take an amount (0 or empty removes the limit).
    raw = data.get('amount')
    try:
        value = Decimal(str(raw)) if str(raw or '').strip() else Decimal('0')
    except (InvalidOperation, TypeError):
        return _safer_screen(flow_token, message="Please enter a valid amount (e.g. 100), or 0 to remove.")
    remove = value <= 0
    if action == 'deposit_limit':
        compliance.set_daily_deposit_limit(user, None if remove else value)
        what = "daily deposit limit"
    else:
        compliance.set_daily_stake_limit(user, None if remove else value)
        what = "daily stake limit"
    msg = (f"✅ Your {what} has been removed." if remove
           else f"✅ Your {what} is now ${value:.2f}.")
    return _done_screen(msg, heading="Safer gambling")
