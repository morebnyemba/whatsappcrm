# whatsappcrm_backend/football_data_app/betting_flow_actions.py
"""
Flow-action handlers for the tap-driven WhatsApp betting experience.

Each handler is a small state-machine step invoked by the flow engine's
`handle_betting_action` dispatch. It reads the user's last tap (`selection`) and
the running slip (held in `flow_context`), mutates the context, and returns the
standard {success, message, data} dict. `data` is merged back into the flow
context by the engine, so handlers expose a `route` variable that the flow's
transitions branch on, plus the `*_sections` / `*_body` variables that the
interactive `sections_from` primitive renders.

Bet placement is never assembled from free text here — selections are always
real MarketOutcome ids and placement is delegated to
customer_data.ticket_processing.process_bet_ticket_submission, which owns all
fund / status / odds / stake validation.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User

from customer_data.models import BetTicket
from customer_data.ticket_processing import process_bet_ticket_submission
from . import betting_ux as ux
from .models import MarketOutcome

logger = logging.getLogger(__name__)

# Betting-action names handled by this module (routed from flow_actions.py).
BETTING_UX_ACTIONS = {
    'browse_fixtures', 'open_fixture', 'open_market', 'select_outcome',
    'view_slip', 'clear_slip', 'remove_last_selection', 'set_stake',
    'place_slip', 'my_bets', 'view_ticket',
    'rg_menu', 'rg_self_exclude', 'rg_set_deposit_limit', 'rg_set_stake_limit',
}

QUICK_STAKES = ('10', '50', '100')


def _ok(message, **data):
    return {"success": True, "message": message, "data": data}


def _fail(message, **data):
    return {"success": False, "message": message, "data": data}


def _parse_selection(selection: str, prefix: str):
    """Return the payload after 'prefix:' if selection matches, else None."""
    if isinstance(selection, str) and selection.startswith(prefix + ':'):
        return selection.split(':', 1)[1]
    return None


def _preferred_league_ids(user: User) -> list[int]:
    """Leagues the user bets on most, to float their fixtures up (personalization)."""
    if not user:
        return []
    try:
        from django.db.models import Count
        rows = (
            BetTicket.objects.filter(user=user)
            .values('bets__market_outcome__market__fixture__league_id')
            .annotate(n=Count('id'))
            .order_by('-n')[:3]
        )
        return [r['bets__market_outcome__market__fixture__league_id'] for r in rows
                if r['bets__market_outcome__market__fixture__league_id']]
    except Exception:
        return []


def handle_betting_ux_action(contact, action_type, flow_context, user, selection=None, stake=None):
    slip = flow_context.get('slip') or []

    # --------------------------------------------------------------- browse
    if action_type == 'browse_fixtures':
        page = int(flow_context.get('fixtures_page') or 0)
        screen = ux.build_fixtures_screen(page=page, preferred_league_ids=_preferred_league_ids(user))
        flow_context['fixtures_sections'] = screen['sections']
        return _ok(screen['body'], fixtures_body=screen['body'],
                   fixtures_has_more=screen['has_more'], fixtures_count=screen['count'])

    # ------------------------------------------------- fixture tapped / paging
    if action_type == 'open_fixture':
        page = _parse_selection(selection, 'fxpage')
        if page is not None:
            flow_context['fixtures_page'] = int(page)
            return _ok("Loading more matches…", route='rebrowse')

        fx_id = _parse_selection(selection, 'fx')
        if not fx_id:
            return _fail("Please tap one of the matches from the list.", route='invalid')
        screen = ux.build_markets_screen(int(fx_id))
        if not screen or not screen['has_markets']:
            return _fail("Sorry, that match has no open markets right now.", route='no_markets')
        flow_context['markets_sections'] = screen['sections']
        flow_context['current_fixture_id'] = int(fx_id)
        return _ok(screen['body'], markets_body=screen['body'], route='markets')

    # ------------------------------------------------------- market tapped
    if action_type == 'open_market':
        mk_id = _parse_selection(selection, 'mk')
        if not mk_id:
            return _fail("Please tap one of the markets.", route='invalid')
        screen = ux.build_outcomes_screen(int(mk_id))
        if not screen or not screen['has_outcomes']:
            return _fail("Sorry, that market has no options right now.", route='no_outcomes')
        flow_context['outcomes_sections'] = screen['sections']
        flow_context['current_market_id'] = int(mk_id)
        return _ok(screen['body'], outcomes_body=screen['body'], route='outcomes')

    # ------------------------------------------------------ outcome tapped
    if action_type == 'select_outcome':
        ou_id = _parse_selection(selection, 'ou')
        if not ou_id:
            return _fail("Please tap one of the options.", route='invalid')
        outcome = (
            MarketOutcome.objects.filter(id=int(ou_id), is_active=True)
            .select_related('market__fixture__home_team', 'market__fixture__away_team', 'market__category')
            .first()
        )
        if not outcome:
            return _fail("That option is no longer available.", route='invalid')
        slip, added, msg = ux.slip_add(slip, outcome)
        flow_context['slip'] = slip
        flow_context['slip_summary'] = ux.slip_summary_text(slip)
        return _ok(msg, slip_last_message=msg, slip_size=len(slip), route='added')

    # --------------------------------------------------------- view slip
    if action_type == 'view_slip':
        flow_context['slip_summary'] = ux.slip_summary_text(slip)
        route = 'empty' if not slip else 'has_items'
        return _ok(flow_context['slip_summary'], slip_size=len(slip), route=route)

    if action_type == 'clear_slip':
        flow_context['slip'] = []
        flow_context['slip_summary'] = ux.slip_summary_text([])
        return _ok("🧾 Your bet slip has been cleared.", slip_size=0, route='cleared')

    if action_type == 'remove_last_selection':
        if slip:
            removed = slip.pop()
            flow_context['slip'] = slip
            flow_context['slip_summary'] = ux.slip_summary_text(slip)
            return _ok(f"Removed: {removed.get('pick', removed.get('label'))}",
                       slip_size=len(slip), route='removed')
        return _ok("Your slip is already empty.", slip_size=0, route='empty')

    # ----------------------------------------------------------- staking
    if action_type == 'set_stake':
        if not slip:
            return _fail("Your slip is empty. Add a selection first.", route='empty')
        raw = _parse_selection(selection, 'stake')
        raw = raw if raw is not None else stake
        try:
            stake_val = float(Decimal(str(raw)))
        except (InvalidOperation, TypeError, ValueError):
            return _fail("Please enter a valid stake amount (e.g. 10).", route='invalid_stake')
        if stake_val <= 0:
            return _fail("Stake must be greater than zero.", route='invalid_stake')
        # Refresh against current odds before showing the confirm preview --
        # legs may have been added a while ago (live odds move every minute).
        slip, _changed = ux.refresh_slip_odds(slip)
        flow_context['slip'] = slip
        if not slip:
            flow_context['stake'] = None
            return _fail(
                "Those selections are no longer available. Your slip has been cleared — please pick again.",
                route='empty',
            )
        flow_context['stake'] = stake_val
        summary = ux.slip_summary_text(slip, stake=stake_val)
        flow_context['bet_confirmation_message'] = summary
        return _ok(summary, bet_confirmation_message=summary, route='confirm')

    # --------------------------------------------------------- placement
    if action_type == 'place_slip':
        if not slip:
            return _fail("Your slip is empty.", route='empty')
        stake_val = flow_context.get('stake')
        if not stake_val:
            return _fail("Please choose a stake first.", route='no_stake')
        # Odds can move between the confirm screen rendering and the bettor
        # actually tapping "Place bet" (especially in-play). Re-check right
        # before submission rather than silently placing at a different
        # price than what was last shown.
        refreshed_slip, changed = ux.refresh_slip_odds(slip)
        if changed:
            flow_context['slip'] = refreshed_slip
            if not refreshed_slip:
                flow_context['stake'] = None
                return _fail(
                    "Those selections are no longer available. Your slip has been cleared — please pick again.",
                    route='empty',
                )
            summary = ux.slip_summary_text(refreshed_slip, stake=stake_val)
            flow_context['bet_confirmation_message'] = summary
            return _fail(
                "⚠️ Odds have changed since you confirmed. Here's the updated slip — please review and confirm again:\n\n" + summary,
                route='odds_changed',
                bet_confirmation_message=summary,
            )
        result = process_bet_ticket_submission(
            whatsapp_id=contact.whatsapp_id,
            market_outcome_ids=ux.slip_outcome_ids(slip),
            stake=float(stake_val),
        )
        if result.get('success'):
            # Clear the slip so a new bet starts fresh.
            flow_context['slip'] = []
            flow_context['stake'] = None
            flow_context['slip_summary'] = ux.slip_summary_text([])
        return {
            "success": result.get('success', False),
            "message": result.get('message', 'An unknown error occurred.'),
            "data": {
                "route": 'placed' if result.get('success') else 'place_failed',
                "place_ticket_message": result.get('message'),
                "ticket_id": result.get('ticket_id'),
                "new_balance": result.get('new_balance'),
            },
        }

    # ----------------------------------------------------------- my bets
    if action_type == 'my_bets':
        if not user:
            return _fail("You need an account to view your bets.", route='no_user')
        tickets = (
            BetTicket.objects.filter(user=user)
            .order_by('-created_at')[:10]
        )
        rows = []
        for t in tickets:
            status = t.get_status_display()
            emoji = {'WON': '✅', 'LOST': '❌', 'PLACED': '⏳', 'PENDING': '⏳',
                     'REFUNDED': '↩️'}.get(t.status, '•')
            rows.append({
                'id': f"mybet:{t.id}",
                'title': ux._truncate(f"#{t.id} · ${float(t.total_stake):.2f}", 24),
                'description': ux._truncate(
                    f"{emoji} {status} · win ${float(t.potential_winnings):.2f}", 72),
            })
        if not rows:
            return _ok("You have no bets yet. Tap *Browse matches* to place your first bet!",
                       route='empty', my_bets_count=0)
        flow_context['my_bets_sections'] = [{'title': 'Your bets', 'rows': rows[:10]}]
        return _ok("Here are your recent bets. Tap one to see details.",
                   route='has_bets', my_bets_count=len(rows))

    # ------------------------------------------------------- view a ticket
    if action_type == 'view_ticket':
        tid = _parse_selection(selection, 'mybet') or selection
        try:
            ticket = (
                BetTicket.objects.filter(user=user, id=int(tid))
                .prefetch_related(
                    'bets__market_outcome__market__fixture__home_team',
                    'bets__market_outcome__market__fixture__away_team',
                    'bets__market_outcome__market__category',
                )
                .first()
            )
        except (TypeError, ValueError):
            return _fail("That ticket could not be found.", route='not_found')
        if not ticket:
            return _fail("That ticket could not be found.", route='not_found')

        emoji = {'WON': '✅', 'LOST': '❌', 'PLACED': '⏳', 'PENDING': '⏳',
                 'REFUNDED': '↩️'}.get(ticket.status, '•')
        lines = [
            f"🎫 *Ticket #{ticket.id}* {emoji} {ticket.get_status_display()}",
            f"Type: {ticket.get_bet_type_display()}",
            f"Stake: ${float(ticket.total_stake):.2f}",
            f"Combined odds: {float(ticket.total_odds):.2f}",
            f"Potential payout: ${float(ticket.potential_winnings):.2f}",
            "",
            "*Selections:*",
        ]
        for bet in ticket.bets.all():
            fx = bet.market_outcome.market.fixture
            lines.append(f"• {fx.home_team.name} v {fx.away_team.name}")
            lines.append(f"   {bet.market_outcome.market.category.name}: "
                         f"{bet.market_outcome.outcome_name} @ {float(bet.market_outcome.odds):.2f} "
                         f"({bet.get_status_display()})")
        msg = "\n".join(lines)[:4096]
        flow_context['ticket_detail_message'] = msg
        return _ok(msg, ticket_detail_message=msg, route='shown')

    # ------------------------------------------------- responsible gambling
    if action_type in ('rg_menu', 'rg_self_exclude', 'rg_set_deposit_limit', 'rg_set_stake_limit'):
        if not user:
            return _fail("You need an account to manage safer-gambling settings.", route='no_user')
        from customer_data import compliance

        if action_type == 'rg_menu':
            summary = compliance.limits_summary(user)
            flow_context['rg_summary'] = summary
            return _ok(summary, rg_summary=summary, route='shown')

        if action_type == 'rg_self_exclude':
            days = _parse_selection(selection, 'excl') or selection
            try:
                days = int(days)
            except (TypeError, ValueError):
                return _fail("Please choose a valid self-exclusion period.", route='invalid')
            compliance.set_self_exclusion(user, days)
            msg = (f"🛡️ You have been self-excluded for {days} day(s). Betting and deposits are "
                   f"blocked during this time. Take care.")
            return _ok(msg, rg_message=msg, route='done')

        # rg_set_deposit_limit / rg_set_stake_limit accept a typed amount (0 = remove)
        raw = selection if selection is not None else stake
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            return _fail("Please enter a valid amount (e.g. 100), or 0 to remove.", route='invalid')
        remove = value <= 0
        if action_type == 'rg_set_deposit_limit':
            compliance.set_daily_deposit_limit(user, None if remove else value)
            what = "daily deposit limit"
        else:
            compliance.set_daily_stake_limit(user, None if remove else value)
            what = "daily stake limit"
        msg = (f"✅ Your {what} has been removed." if remove
               else f"✅ Your {what} is now ${value:.2f}.")
        return _ok(msg, rg_message=msg, route='done')

    return _fail(f"Unsupported betting action: {action_type}", route='unsupported')
