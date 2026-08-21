# whatsappcrm_backend/football_data_app/betting_ux.py
"""
Builders for the tap-driven WhatsApp betting experience (BetBlitz).

These functions turn database state (fixtures, markets, outcomes, tickets, and a
running bet slip stored in the flow context) into the interactive-message
structures the flow engine sends: lists of "sections" (each with up to 10 rows)
and lists of reply "buttons" (up to 3). The flow engine splices these into a
declarative interactive message via the `sections_from` / `buttons_from`
primitive (see flows/services.py).

Row/button `id`s follow a compact `prefix:payload` scheme so a single question
step can capture the tap and a dispatcher action can route on the prefix:
    fx:<fixture_id>        a fixture in the browser
    fxpage:<n>             go to browser page n
    mk:<market_id>         a specific market of the open fixture
    ou:<outcome_id>        a market outcome
    mybet:<ticket_id>      one of the user's tickets

WhatsApp constraints respected here: list row title <= 24 chars, description
<= 72 chars, section title <= 24 chars, at most 10 rows across a whole list,
reply button title <= 20 chars, at most 3 buttons.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.db.models import Case, IntegerField, Prefetch, Q, When
from django.utils import timezone

from .models import FootballFixture, Market, MarketOutcome

# WhatsApp interactive-list hard limit: total rows across all sections.
MAX_LIST_ROWS = 10
# How many fixtures to show per browser page. Middle pages can show both a
# "Previous" and a "More" nav row, so 2 of the 10-row WhatsApp list cap are
# always reserved for navigation, leaving 8 for fixtures.
FIXTURES_PER_PAGE = 8
# Only offer bets on fixtures kicking off within this window.
BROWSE_WINDOW_DAYS = 10

# Categories surfaced first in the fixture detail view, in this order.
PREFERRED_MARKET_ORDER = [
    'Match Winner', 'Double Chance', 'Draw No Bet', 'Totals',
    'Both Teams To Score', 'Odd/Even Goals', 'Asian Handicap', 'Correct Score',
]


def _truncate(text: str, limit: int) -> str:
    text = (text or '').strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + '…'


def _fixture_label(fixture: FootballFixture) -> str:
    """A compact 'Home v Away' label for a row title (<= 24 chars)."""
    return _truncate(f"{fixture.home_team.name} v {fixture.away_team.name}", 24)


def _kickoff_label(fixture: FootballFixture) -> str:
    if fixture.status == FootballFixture.FixtureStatus.LIVE:
        if fixture.home_team_score is not None and fixture.away_team_score is not None:
            return f"🔴 LIVE · {fixture.home_team_score}-{fixture.away_team_score}"
        return "🔴 LIVE"
    if not fixture.match_date:
        return 'TBD'
    return timezone.localtime(fixture.match_date).strftime('%a %d %b, %H:%M')


def _day_bucket(fixture_dt) -> tuple[int, str]:
    """Return (sort_key, human label) grouping a fixture by kickoff day."""
    now = timezone.localtime(timezone.now())
    local = timezone.localtime(fixture_dt)
    delta_days = (local.date() - now.date()).days
    if delta_days <= 0:
        return (0, 'Today')
    if delta_days == 1:
        return (1, 'Tomorrow')
    return (local.date().toordinal(), local.strftime('%a %d %b'))


def _one_x_two_summary(fixture: FootballFixture) -> Optional[str]:
    """Short '1X2 2.10/3.40/2.80' summary from the Match Winner market, if any."""
    market = (
        fixture.markets.filter(category__name='Match Winner', is_active=True)
        .prefetch_related('outcomes')
        .order_by('-last_updated_odds_api')
        .first()
    )
    if not market:
        return None
    odds = {o.outcome_name.lower(): o.odds for o in market.outcomes.all() if o.is_active}
    home, draw, away = odds.get('home'), odds.get('draw'), odds.get('away')
    if home and draw and away:
        return f"1X2 {home:.2f}/{draw:.2f}/{away:.2f}"
    return None


def _bettable_fixtures_qs():
    """Fixtures currently open for betting: upcoming scheduled fixtures
    within the browse window, plus fixtures that have gone LIVE (kickoff has
    passed, so the match_date window no longer applies to them) and still
    have at least one active market -- a LIVE fixture whose markets were all
    suspended by the live-odds provider is naturally excluded by the
    markets__is_active=True join, same as any other fixture with no
    currently-offered market."""
    now = timezone.now()
    return (
        FootballFixture.objects.filter(
            Q(status=FootballFixture.FixtureStatus.SCHEDULED,
              match_date__gte=now, match_date__lte=now + timedelta(days=BROWSE_WINDOW_DAYS))
            | Q(status=FootballFixture.FixtureStatus.LIVE),
            markets__is_active=True,
        )
        .select_related('league', 'home_team', 'away_team')
        .distinct()
        # LIVE fixtures first (sort key 0), then upcoming fixtures by kickoff.
        .order_by(
            Case(When(status=FootballFixture.FixtureStatus.LIVE, then=0), default=1,
                 output_field=IntegerField()),
            'match_date',
        )
    )


def build_fixtures_screen(page: int = 0, preferred_league_ids: Optional[list[int]] = None) -> dict:
    """
    Build the fixture-browser list for a page.

    Returns a dict with:
        sections:  list of interactive-list section dicts (grouped by day)
        has_more:  whether a further page exists
        count:     fixtures shown on this page
        body:      body text for the message
    Fixtures whose league is in `preferred_league_ids` are floated to the top
    (used by personalization later); ordering otherwise is by kickoff.
    """
    page = max(0, int(page or 0))
    qs = list(_bettable_fixtures_qs())

    if preferred_league_ids:
        pref = set(preferred_league_ids)
        qs.sort(key=lambda f: (0 if f.league_id in pref else 1,))  # stable: keeps kickoff order within groups

    start = page * FIXTURES_PER_PAGE
    page_fixtures = qs[start:start + FIXTURES_PER_PAGE]
    has_more = len(qs) > start + FIXTURES_PER_PAGE

    # Group this page's fixtures into day sections (each section <= 10 rows; a
    # page is <= 9 fixtures so we never exceed the whole-list cap of 10).
    buckets: dict[tuple, dict] = {}
    for fx in page_fixtures:
        if fx.status == FootballFixture.FixtureStatus.LIVE:
            # Its own section ahead of "Today" -- a live fixture's match_date
            # is now in the past and no longer means anything as a grouping
            # key, and it shouldn't be mixed in with today's not-yet-started
            # matches.
            sort_key, label = (-1, '🔴 Live Now')
        else:
            sort_key, label = _day_bucket(fx.match_date)
        section = buckets.setdefault((sort_key, label), {'title': _truncate(label, 24), 'rows': []})
        desc_bits = [_kickoff_label(fx)]
        summary = _one_x_two_summary(fx)
        if summary:
            desc_bits.append(summary)
        section['rows'].append({
            'id': f"fx:{fx.id}",
            'title': _fixture_label(fx),
            'description': _truncate(' · '.join(desc_bits), 72),
        })

    sections = [buckets[k] for k in sorted(buckets.keys())]

    nav_rows = []
    if page > 0:
        nav_rows.append({'id': f"fxpage:{page - 1}", 'title': '⬅️ Previous matches',
                          'description': 'See the previous page of fixtures'})
    if has_more:
        nav_rows.append({'id': f"fxpage:{page + 1}", 'title': '➡️ More matches',
                          'description': 'See the next page of fixtures'})
    if nav_rows:
        sections.append({'title': 'More', 'rows': nav_rows})

    if not page_fixtures:
        body = "No upcoming matches are open for betting right now. Please check back later."
    elif page > 0:
        total_pages = -(-len(qs) // FIXTURES_PER_PAGE)  # ceil division
        body = f"Page {page + 1} of {total_pages}. Tap a match to see its markets and place a bet. 👇"
    else:
        body = "Tap a match to see its markets and place a bet. 👇"

    return {'sections': sections, 'has_more': has_more, 'count': len(page_fixtures), 'body': body}


def _ordered_markets(fixture: FootballFixture) -> list[Market]:
    """One representative active Market per category, in a friendly order.

    Real ingestion stores a Market per bookmaker; we pick the most recently
    updated market for each category so displayed odds match a real outcome row.
    """
    markets = (
        fixture.markets.filter(is_active=True)
        .select_related('category')
        .prefetch_related('outcomes')
        .order_by('-last_updated_odds_api')
    )
    by_category: dict[str, Market] = {}
    for m in markets:
        by_category.setdefault(m.category.name, m)  # first (newest) wins per category

    order = {name: i for i, name in enumerate(PREFERRED_MARKET_ORDER)}
    return sorted(by_category.values(), key=lambda m: (order.get(m.category.name, 99), m.category.name))


def build_markets_screen(fixture_id: int) -> Optional[dict]:
    """Build the market list for one fixture. Returns None if fixture missing."""
    fixture = (
        FootballFixture.objects.filter(id=fixture_id)
        .select_related('home_team', 'away_team', 'league')
        .first()
    )
    if not fixture:
        return None

    markets = _ordered_markets(fixture)
    rows = []
    for m in markets[:MAX_LIST_ROWS]:
        active_outcomes = [o for o in m.outcomes.all() if o.is_active]
        if not active_outcomes:
            continue
        rows.append({
            'id': f"mk:{m.id}",
            'title': _truncate(m.category.name, 24),
            'description': _truncate(f"{len(active_outcomes)} option(s)", 72),
        })

    header = f"{fixture.home_team.name} vs {fixture.away_team.name}"
    body = f"*{_truncate(header, 60)}*\n{_kickoff_label(fixture)}\n\nChoose a market:"
    sections = [{'title': 'Markets', 'rows': rows}] if rows else []
    return {
        'fixture': fixture,
        'sections': sections,
        'body': _truncate(body, 1024),
        'has_markets': bool(rows),
    }


def build_outcomes_screen(market_id: int) -> Optional[dict]:
    """Build the outcome list for one market. Returns None if market missing."""
    market = (
        Market.objects.filter(id=market_id, is_active=True)
        .select_related('category', 'fixture__home_team', 'fixture__away_team')
        .prefetch_related('outcomes')
        .first()
    )
    if not market:
        return None

    fixture = market.fixture
    # For 1X2 (Match Winner) show the team names rather than generic Home/Away.
    is_1x2 = market.category.name == 'Match Winner'
    label_map = {
        'home': fixture.home_team.name,
        'away': fixture.away_team.name,
        'draw': 'Draw',
    }
    rows = []
    for o in sorted(market.outcomes.all(), key=lambda x: x.outcome_name):
        if not o.is_active:
            continue
        name = o.outcome_name
        if is_1x2:
            name = label_map.get(o.outcome_name.lower(), o.outcome_name)
        if o.point_value is not None:
            name = f"{name} {o.point_value}"
        rows.append({
            'id': f"ou:{o.id}",
            'title': _truncate(name, 24),
            'description': _truncate(f"Odds {o.odds:.2f}", 72),
        })

    body = (
        f"*{_truncate(f'{fixture.home_team.name} vs {fixture.away_team.name}', 60)}*\n"
        f"{market.category.name}\n\nTap your pick:"
    )
    sections = [{'title': _truncate(market.category.name, 24), 'rows': rows[:MAX_LIST_ROWS]}] if rows else []
    return {'market': market, 'sections': sections, 'body': _truncate(body, 1024), 'has_outcomes': bool(rows)}


# --------------------------------------------------------------------------- #
#  Bet slip (running selections held in the flow context)                     #
# --------------------------------------------------------------------------- #

def slip_add(slip: list, outcome: MarketOutcome) -> tuple[list, bool, str]:
    """Add an outcome to the slip. Returns (slip, added, message)."""
    slip = list(slip or [])
    if any(str(item.get('outcome_id')) == str(outcome.id) for item in slip):
        return slip, False, "That selection is already in your slip."

    fixture = outcome.market.fixture
    pick = outcome.outcome_name
    if outcome.market.category.name == 'Match Winner':
        pick = {'home': fixture.home_team.name, 'away': fixture.away_team.name}.get(pick.lower(), pick)
    if outcome.point_value is not None:
        pick = f"{pick} {outcome.point_value}"
    label = f"{fixture.home_team.name} v {fixture.away_team.name} — {pick}"
    slip.append({
        'outcome_id': outcome.id,
        'label': label,
        'odds': float(outcome.odds),
        'market': outcome.market.category.name,
        'pick': pick,
    })
    return slip, True, f"Added: {pick} @ {outcome.odds:.2f}"


def slip_combined_odds(slip: list) -> Decimal:
    total = Decimal('1.000')
    for item in (slip or []):
        total *= Decimal(str(item.get('odds', 1)))
    return total


def slip_summary_text(slip: list, stake: Optional[float] = None) -> str:
    """Human-readable slip summary with live combined odds and potential payout."""
    slip = slip or []
    if not slip:
        return "🧾 Your bet slip is empty. Browse matches and tap *Add to slip* on a pick."

    lines = ["🧾 *Your Bet Slip*", ""]
    for i, item in enumerate(slip, 1):
        lines.append(f"{i}. {item['label']}")
        lines.append(f"   {item['market']} @ {item['odds']:.2f}")
    combined = slip_combined_odds(slip)
    bet_type = 'Single' if len(slip) == 1 else f"Accumulator ({len(slip)} legs)"
    lines.append("")
    lines.append(f"Type: {bet_type}")
    lines.append(f"Combined odds: *{combined:.2f}*")
    if stake:
        payout = Decimal(str(stake)) * combined
        lines.append(f"Stake: ${float(stake):.2f}")
        lines.append(f"Potential payout: *${float(payout):.2f}*")
    return "\n".join(lines)[:1024]


def slip_outcome_ids(slip: list) -> list[str]:
    return [str(item['outcome_id']) for item in (slip or [])]
