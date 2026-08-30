# whatsappcrm_backend/football_data_app/test_live_odds.py
"""
Live/in-play betting: before this, a fixture disappeared from every browse
list -- both the native WhatsApp Flow and the conversational Betting Flow,
which share football_data_app.betting_ux -- the instant it kicked off
(status flips SCHEDULED -> LIVE, and _bettable_fixtures_qs() only ever
matched SCHEDULED). There was also no live-odds pipeline at all: only
pre-match /odds was ever fetched.

This covers the three new pieces:
- APIFootballV3Client.get_live_odds() -- the new /odds/live client method.
- _process_api_football_v3_live_odds_data() / fetch_live_odds_v3_task() --
  the live-odds ingestion pipeline. It reuses the same upsert-in-place
  Market/MarketOutcome semantics the pre-match pipeline already uses (never
  delete-and-recreate, so a placed Bet's foreign key never dangles), and
  treats the provider's own per-outcome "suspended" flag as the market-
  suspension mechanism: is_active=False on a suspended outcome already
  makes it invisible to both browse (outcomes filtered to is_active=True)
  and placement (process_bet_ticket_submission only accepts is_active=True
  outcome ids) with zero other code changes needed.
- betting_ux._bettable_fixtures_qs() / _kickoff_label() -- LIVE fixtures
  with an active market now appear in browse, labelled with a live score
  instead of a (now meaningless) kickoff time, sorted ahead of upcoming
  fixtures. Both bet_flow_handler.py (native Flow) and betting_flow_actions.py
  (conversational Flow) build their fixture lists from this same function,
  so fixing it here fixes both surfaces at once.
"""
import os
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from customer_data.models import BetTicket, Bet
from .models import League, Team, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome
from .api_football_v3_client import APIFootballV3Client, APIFootballV3Exception
from .tasks_api_football_v3 import (
    _process_api_football_v3_live_odds_data,
    fetch_live_odds_v3_task,
    fetch_scores_for_league_v3_task,
    run_score_and_settlement_v3_task,
)
from . import betting_ux as ux


class GetLiveOddsClientTests(TestCase):
    """The client method itself: correct endpoint, correct param passthrough,
    and it never raises just because the provider's plan doesn't include
    live odds -- that's an HTTP-level concern _request() already handles the
    same way get_odds() does, not something this method needs to special-case."""

    def setUp(self):
        with patch.object(APIFootballV3Client, '__init__', lambda self: None):
            self.client = APIFootballV3Client()

    def test_calls_the_live_odds_endpoint(self):
        with patch.object(self.client, '_request', return_value={'response': [{'fixture': {'id': 1}}]}) as mock_request:
            result = self.client.get_live_odds()
        mock_request.assert_called_once_with('odds/live', {})
        self.assertEqual(result, [{'fixture': {'id': 1}}])

    def test_passes_fixture_id_filter(self):
        with patch.object(self.client, '_request', return_value={'response': []}) as mock_request:
            self.client.get_live_odds(fixture_id=999)
        mock_request.assert_called_once_with('odds/live', {'fixture': 999})

    def test_missing_response_key_returns_empty_list(self):
        with patch.object(self.client, '_request', return_value={}):
            self.assertEqual(self.client.get_live_odds(), [])


class LiveOddsProcessingTests(TestCase):
    """_process_api_football_v3_live_odds_data: upsert-in-place (preserves a
    placed Bet's market_outcome across a live refresh, same as the pre-match
    pipeline), and the provider's "suspended" flag drives is_active."""

    def setUp(self):
        self.user = None  # created per-test where a placed Bet matters
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.home = Team.objects.create(name='Home Team')
        self.away = Team.objects.create(name='Away Team')
        self.bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away, api_id='v3_live_1',
            match_date=timezone.now() - timedelta(minutes=40),
            status=FootballFixture.FixtureStatus.LIVE,
            home_team_score=1, away_team_score=0,
        )
        self.category = MarketCategory.objects.create(name='Match Winner')
        self.market = Market.objects.create(
            fixture=self.fixture, bookmaker=self.bookmaker, api_market_key='h2h',
            category=self.category, last_updated_odds_api=timezone.now())
        self.outcome = MarketOutcome.objects.create(
            market=self.market, outcome_name='Home Team', odds=Decimal('1.80'))

    def _live_entry(self, home_odd='2.20', suspended=False):
        return {
            'fixture': {'id': 1},
            'odds': [{
                'id': 8,
                'name': 'bet365',
                'bets': [{
                    'id': 1,
                    'name': 'Match Winner',
                    'values': [
                        {'value': 'Home', 'odd': home_odd, 'suspended': suspended},
                        {'value': 'Draw', 'odd': '3.40', 'suspended': suspended},
                        {'value': 'Away', 'odd': '3.10', 'suspended': suspended},
                    ],
                }],
            }],
        }

    def test_refresh_updates_odds_in_place_and_preserves_a_placed_bet(self):
        from django.contrib.auth.models import User
        from conversations.models import Contact
        from customer_data.models import CustomerProfile, UserWallet
        user = User.objects.create_user('liveoddsbettor')
        UserWallet.objects.filter(user=user).update(balance=Decimal('500'))
        contact = Contact.objects.create(whatsapp_id='263779991111')
        CustomerProfile.objects.create(contact=contact, user=user,
                                       date_of_birth=timezone.localdate().replace(year=1990))
        ticket = BetTicket.objects.create(user=user, total_stake=Decimal('10.00'),
                                          potential_winnings=Decimal('18.00'), status='PENDING', bet_type='SINGLE')
        bet = Bet.objects.create(ticket=ticket, market_outcome=self.outcome, amount=Decimal('10.00'),
                                 potential_winnings=Decimal('18.00'), status='PENDING')

        _process_api_football_v3_live_odds_data(self.fixture, self._live_entry(home_odd='2.20'))

        self.assertTrue(Bet.objects.filter(id=bet.id).exists())
        self.outcome.refresh_from_db()
        self.assertEqual(self.outcome.odds, Decimal('2.20'))
        self.assertTrue(self.outcome.is_active)
        # Already-placed bet's own payout is unaffected by the later odds move.
        bet.refresh_from_db()
        self.assertEqual(bet.potential_winnings, Decimal('18.00'))

    def test_provider_suspended_flag_deactivates_the_outcome(self):
        _process_api_football_v3_live_odds_data(self.fixture, self._live_entry(suspended=True))
        self.outcome.refresh_from_db()
        self.assertFalse(self.outcome.is_active)

    def test_unsuspending_on_a_later_tick_reactivates_it(self):
        _process_api_football_v3_live_odds_data(self.fixture, self._live_entry(suspended=True))
        self.outcome.refresh_from_db()
        self.assertFalse(self.outcome.is_active)

        _process_api_football_v3_live_odds_data(self.fixture, self._live_entry(suspended=False))
        self.outcome.refresh_from_db()
        self.assertTrue(self.outcome.is_active)

    def test_suspended_outcome_cannot_be_bet_on(self):
        from customer_data.ticket_processing import process_bet_ticket_submission
        from django.contrib.auth.models import User
        from conversations.models import Contact
        from customer_data.models import CustomerProfile, UserWallet
        user = User.objects.create_user('suspendedbettor')
        UserWallet.objects.filter(user=user).update(balance=Decimal('500'))
        contact = Contact.objects.create(whatsapp_id='263779992222')
        CustomerProfile.objects.create(contact=contact, user=user,
                                       date_of_birth=timezone.localdate().replace(year=1990))

        _process_api_football_v3_live_odds_data(self.fixture, self._live_entry(suspended=True))

        result = process_bet_ticket_submission(
            whatsapp_id=contact.whatsapp_id,
            market_outcome_ids=[str(self.outcome.id)],
            stake=10.0,
        )
        self.assertFalse(result['success'])
        self.assertEqual(BetTicket.objects.filter(user=user).count(), 0)

    def test_accepts_legacy_bookmakers_key_as_well_as_odds_key(self):
        # Defensive fallback in case the provider's response shape uses the
        # same "bookmakers" key the pre-match /odds endpoint uses.
        entry = {
            'fixture': {'id': 1},
            'bookmakers': [{
                'id': 8, 'name': 'bet365',
                'bets': [{'id': 1, 'name': 'Match Winner', 'values': [
                    {'value': 'Home', 'odd': '2.50', 'suspended': False},
                ]}],
            }],
        }
        _process_api_football_v3_live_odds_data(self.fixture, entry)
        self.outcome.refresh_from_db()
        self.assertEqual(self.outcome.odds, Decimal('2.50'))


class FetchLiveOddsTaskTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.home = Team.objects.create(name='Home Team')
        self.away = Team.objects.create(name='Away Team')
        self.bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.category = MarketCategory.objects.create(name='Match Winner')

    def _make_fixture(self, api_id, status, with_market=True):
        fx = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away, api_id=api_id,
            match_date=timezone.now() - timedelta(minutes=30), status=status)
        if with_market:
            market = Market.objects.create(fixture=fx, bookmaker=self.bookmaker, api_market_key='h2h',
                                           category=self.category, last_updated_odds_api=timezone.now())
            MarketOutcome.objects.create(market=market, outcome_name='Home Team', odds=Decimal('2.00'))
        return fx

    def test_no_live_fixtures_skips_the_api_call_entirely(self):
        self._make_fixture('v3_sched_1', FootballFixture.FixtureStatus.SCHEDULED)
        with patch.object(APIFootballV3Client, 'get_live_odds') as mock_get_live_odds:
            fetch_live_odds_v3_task()
        mock_get_live_odds.assert_not_called()

    def test_live_fixture_without_any_existing_market_is_skipped(self):
        # Never opened for pre-match betting, so there's nothing worth
        # keeping priced through kickoff -- matches the task's own docstring.
        self._make_fixture('v3_live_nomkt', FootballFixture.FixtureStatus.LIVE, with_market=False)
        with patch.object(APIFootballV3Client, 'get_live_odds') as mock_get_live_odds:
            fetch_live_odds_v3_task()
        mock_get_live_odds.assert_not_called()

    def test_live_fixture_with_a_market_gets_refreshed(self):
        # fetch_live_odds_v3_task() fetches by the fixture's own numeric API
        # id (api_id == f"v3_{numeric_id}"), not a global bulk call.
        fx = self._make_fixture('v3_555', FootballFixture.FixtureStatus.LIVE)
        outcome = MarketOutcome.objects.get(market__fixture=fx)
        live_response = [{
            'fixture': {'id': 555},
            'odds': [{'id': 8, 'name': 'bet365', 'bets': [{'id': 1, 'name': 'Match Winner', 'values': [
                {'value': 'Home', 'odd': '3.00', 'suspended': False},
            ]}]}],
        }]
        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures', return_value=[]), \
                patch.object(APIFootballV3Client, 'get_live_odds', return_value=live_response) as mock_get_live_odds:
            fetch_live_odds_v3_task()
        mock_get_live_odds.assert_called_once_with(fixture_id=555)
        outcome.refresh_from_db()
        self.assertEqual(outcome.odds, Decimal('3.00'))

    def test_each_live_fixture_is_fetched_by_its_own_id_not_one_bulk_call(self):
        fx1 = self._make_fixture('v3_111', FootballFixture.FixtureStatus.LIVE)
        fx2 = self._make_fixture('v3_222', FootballFixture.FixtureStatus.LIVE)
        outcome1 = MarketOutcome.objects.get(market__fixture=fx1)
        outcome2 = MarketOutcome.objects.get(market__fixture=fx2)

        def fake_get_live_odds(fixture_id=None):
            odds_by_fixture = {111: '5.00', 222: '6.00'}
            return [{
                'fixture': {'id': fixture_id},
                'odds': [{'id': 8, 'name': 'bet365', 'bets': [{'id': 1, 'name': 'Match Winner', 'values': [
                    {'value': 'Home', 'odd': odds_by_fixture[fixture_id], 'suspended': False},
                ]}]}],
            }]

        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures', return_value=[]), \
                patch.object(APIFootballV3Client, 'get_live_odds', side_effect=fake_get_live_odds) as mock_get_live_odds:
            fetch_live_odds_v3_task()

        self.assertEqual(mock_get_live_odds.call_count, 2)
        called_fixture_ids = {c.kwargs.get('fixture_id') for c in mock_get_live_odds.call_args_list}
        self.assertEqual(called_fixture_ids, {111, 222})
        outcome1.refresh_from_db()
        outcome2.refresh_from_db()
        self.assertEqual(outcome1.odds, Decimal('5.00'))
        self.assertEqual(outcome2.odds, Decimal('6.00'))

    def test_one_fixtures_api_failure_does_not_block_the_others(self):
        fx1 = self._make_fixture('v3_301', FootballFixture.FixtureStatus.LIVE)
        fx2 = self._make_fixture('v3_302', FootballFixture.FixtureStatus.LIVE)
        outcome2 = MarketOutcome.objects.get(market__fixture=fx2)

        def fake_get_live_odds(fixture_id=None):
            if fixture_id == 301:
                raise RuntimeError("provider timeout")
            return [{
                'fixture': {'id': fixture_id},
                'odds': [{'id': 8, 'name': 'bet365', 'bets': [{'id': 1, 'name': 'Match Winner', 'values': [
                    {'value': 'Home', 'odd': '9.00', 'suspended': False},
                ]}]}],
            }]

        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures', return_value=[]), \
                patch.object(APIFootballV3Client, 'get_live_odds', side_effect=fake_get_live_odds):
            fetch_live_odds_v3_task()  # must not raise

        outcome2.refresh_from_db()
        self.assertEqual(outcome2.odds, Decimal('9.00'))


class LiveFixturesInBrowseTests(TestCase):
    """Both bet_flow_handler.py (native Flow) and betting_flow_actions.py
    (conversational Flow) build their fixture lists from
    betting_ux._bettable_fixtures_qs() / build_fixtures_screen(), so fixing
    it here is what actually answers "what about live matches" for both."""

    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.category = MarketCategory.objects.create(name='Match Winner')

    def _fixture_with_market(self, name_home, name_away, status, **kwargs):
        home = Team.objects.create(name=name_home)
        away = Team.objects.create(name=name_away)
        fx = FootballFixture.objects.create(
            league=self.league, home_team=home, away_team=away,
            api_id=f'v3_{name_home}_{name_away}', status=status,
            match_date=kwargs.pop('match_date', timezone.now() + timedelta(hours=2)),
            **kwargs)
        market = Market.objects.create(fixture=fx, bookmaker=self.bookmaker, api_market_key='h2h',
                                       category=self.category, last_updated_odds_api=timezone.now())
        MarketOutcome.objects.create(market=market, outcome_name='Home', odds=Decimal('2.00'))
        MarketOutcome.objects.create(market=market, outcome_name='Draw', odds=Decimal('3.00'))
        MarketOutcome.objects.create(market=market, outcome_name='Away', odds=Decimal('4.00'))
        return fx

    def test_live_fixture_appears_in_bettable_queryset(self):
        live_fx = self._fixture_with_market(
            'LiveHome', 'LiveAway', FootballFixture.FixtureStatus.LIVE,
            match_date=timezone.now() - timedelta(minutes=20),
            home_team_score=1, away_team_score=1)
        ids = {fx.id for fx in ux._bettable_fixtures_qs()}
        self.assertIn(live_fx.id, ids)

    def test_live_fixture_sorts_before_upcoming_fixtures(self):
        upcoming = self._fixture_with_market('UpHome', 'UpAway', FootballFixture.FixtureStatus.SCHEDULED)
        live_fx = self._fixture_with_market(
            'LiveHome2', 'LiveAway2', FootballFixture.FixtureStatus.LIVE,
            match_date=timezone.now() - timedelta(minutes=20))
        ordered_ids = [fx.id for fx in ux._bettable_fixtures_qs()]
        self.assertLess(ordered_ids.index(live_fx.id), ordered_ids.index(upcoming.id))

    def test_kickoff_label_shows_live_score_not_a_stale_kickoff_time(self):
        live_fx = self._fixture_with_market(
            'ScoreHome', 'ScoreAway', FootballFixture.FixtureStatus.LIVE,
            match_date=timezone.now() - timedelta(minutes=53),
            home_team_score=2, away_team_score=1)
        self.assertEqual(ux._kickoff_label(live_fx), '🔴 LIVE · 2-1')

    def test_kickoff_label_shows_elapsed_minutes_when_available(self):
        live_fx = self._fixture_with_market(
            'ClockHome', 'ClockAway', FootballFixture.FixtureStatus.LIVE,
            match_date=timezone.now() - timedelta(minutes=62),
            home_team_score=0, away_team_score=0, elapsed_minutes=62)
        self.assertEqual(ux._kickoff_label(live_fx), '🔴 62′ · LIVE · 0-0')

    def test_live_fixture_with_every_outcome_suspended_has_no_active_market_and_is_excluded(self):
        live_fx = self._fixture_with_market(
            'SuspHome', 'SuspAway', FootballFixture.FixtureStatus.LIVE,
            match_date=timezone.now() - timedelta(minutes=10))
        # Simulate a live-odds tick that suspended every outcome in the fixture's
        # only market, then deactivated the market itself (mirrors what
        # _process_api_football_v3_live_odds_data does when a bookmaker drops
        # a market entirely).
        Market.objects.filter(fixture=live_fx).update(is_active=False)
        ids = {fx.id for fx in ux._bettable_fixtures_qs()}
        self.assertNotIn(live_fx.id, ids)

    def test_build_fixtures_screen_groups_live_fixtures_into_their_own_section(self):
        self._fixture_with_market(
            'GroupLiveHome', 'GroupLiveAway', FootballFixture.FixtureStatus.LIVE,
            match_date=timezone.now() - timedelta(minutes=15))
        screen = ux.build_fixtures_screen(page=0)
        section_titles = [s['title'] for s in screen['sections']]
        self.assertIn('🔴 Live Now', section_titles)
        # The live section must be the first fixture section (nav "More" is
        # appended after, if present, so this checks position among the
        # fixture-grouping sections specifically).
        self.assertEqual(section_titles[0], '🔴 Live Now')

    def test_native_flow_fixture_options_include_the_live_fixture(self):
        # bet_flow_handler.py's own dropdown-building function -- proves the
        # native Flow surface (not just the conversational one) picks this up
        # for free via the shared betting_ux helpers.
        from . import bet_flow_handler as H
        live_fx = self._fixture_with_market(
            'NativeLiveHome', 'NativeLiveAway', FootballFixture.FixtureStatus.LIVE,
            match_date=timezone.now() - timedelta(minutes=8),
            home_team_score=0, away_team_score=0)
        opts = H._fixtures_options()
        matching = [o for o in opts if o['id'] == str(live_fx.id)]
        self.assertEqual(len(matching), 1)
        self.assertIn('LIVE', matching[0]['description'])


class ScoreAndSettlementDispatchTests(TestCase):
    """run_score_and_settlement_v3_task must fetch the global GET
    /fixtures?live=all response exactly once per cycle and hand the same
    data to every per-league task, instead of each league task
    independently re-requesting that same non-league-scoped endpoint.
    Previously that meant one call per active league every 5 minutes --
    almost all of them redundant -- and, being unguarded in the per-league
    task, a single failure there (e.g. a 403 because the API-Football plan
    doesn't include this endpoint) raised out of the whole league's
    score/settlement run and forced a retry, even though that failure has
    nothing to do with that specific league."""

    def setUp(self):
        self.league1 = League.objects.create(name='L1', api_id='v3_1', sport_key='soccer', active=True)
        self.league2 = League.objects.create(name='L2', api_id='v3_2', sport_key='soccer', active=True)

    def test_fetches_live_fixtures_once_and_shares_across_league_tasks(self):
        live_data = [{'fixture': {'id': 42}}]
        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures', return_value=live_data) as mock_get_live, \
                patch('football_data_app.tasks_api_football_v3.group') as mock_group:
            mock_group.return_value.apply_async = lambda: None
            run_score_and_settlement_v3_task()

        mock_get_live.assert_called_once()
        signatures = mock_group.call_args[0][0]
        self.assertEqual(len(signatures), 2)
        for sig in signatures:
            self.assertEqual(sig.kwargs.get('live_fixtures_data'), live_data)

    def test_get_live_fixtures_failure_does_not_block_dispatch(self):
        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures', side_effect=RuntimeError('boom')), \
                patch('football_data_app.tasks_api_football_v3.group') as mock_group:
            mock_group.return_value.apply_async = lambda: None
            run_score_and_settlement_v3_task()  # must not raise

        signatures = mock_group.call_args[0][0]
        self.assertEqual(len(signatures), 2)
        for sig in signatures:
            self.assertEqual(sig.kwargs.get('live_fixtures_data'), [])


class FetchScoresForLeagueSharedLiveDataTests(TestCase):
    """fetch_scores_for_league_v3_task must use live_fixtures_data when the
    dispatcher already fetched it, rather than re-requesting the same
    global endpoint per league, but still work standalone (e.g. a manual
    invocation) with a failure there treated as "no live fixtures this
    cycle" rather than aborting the league's whole score/settlement run."""

    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer', active=True)
        self.home = Team.objects.create(name='Home Team')
        self.away = Team.objects.create(name='Away Team')
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away, api_id='v3_777',
            match_date=timezone.now() - timedelta(minutes=20),
            status=FootballFixture.FixtureStatus.LIVE,
        )

    def test_uses_shared_live_fixtures_data_without_calling_the_api_again(self):
        live_data = [{
            'fixture': {'id': 777, 'status': {'short': 'LIVE', 'elapsed': 20}},
            'league': {'id': 39},
            'goals': {'home': 1, 'away': 0},
        }]
        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures') as mock_get_live, \
                patch.object(APIFootballV3Client, 'get_fixtures', return_value=[]):
            fetch_scores_for_league_v3_task(self.league.id, live_fixtures_data=live_data)
        mock_get_live.assert_not_called()
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.status, FootballFixture.FixtureStatus.LIVE)
        self.assertEqual(self.fixture.home_team_score, 1)

    def test_falls_back_to_fetching_when_not_given_shared_data(self):
        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures', return_value=[]) as mock_get_live, \
                patch.object(APIFootballV3Client, 'get_fixtures', return_value=[]):
            fetch_scores_for_league_v3_task(self.league.id)
        mock_get_live.assert_called_once()

    def test_live_fixtures_fetch_failure_does_not_abort_the_task(self):
        with patch.dict(os.environ, {'API_FOOTBALL_V3_KEY': 'test-key'}), \
                patch.object(APIFootballV3Client, 'get_live_fixtures',
                             side_effect=APIFootballV3Exception('403 forbidden')), \
                patch.object(APIFootballV3Client, 'get_fixtures', return_value=[]):
            fetch_scores_for_league_v3_task(self.league.id)  # must not raise/retry
