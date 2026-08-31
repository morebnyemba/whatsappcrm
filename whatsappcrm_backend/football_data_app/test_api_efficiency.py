# whatsappcrm_backend/football_data_app/test_api_efficiency.py
"""
Tests for the cost-saving API-Football v3 request changes: /odds pagination,
fixture id batching, and bulk per-league-day odds fetching.
"""
from decimal import Decimal
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from .api_football_v3_client import APIFootballV3Client
from .models import League, Team, FootballFixture


class ClientPaginationTests(TestCase):
    def test_request_all_pages_concatenates(self):
        client = APIFootballV3Client(api_key='x')
        pages = [
            {'response': [{'a': 1}, {'a': 2}], 'paging': {'current': 1, 'total': 3}},
            {'response': [{'a': 3}], 'paging': {'current': 2, 'total': 3}},
            {'response': [{'a': 4}], 'paging': {'current': 3, 'total': 3}},
        ]
        with mock.patch.object(client, '_request', side_effect=pages) as m:
            out = client._request_all_pages('odds', {'league': 1})
        self.assertEqual([o['a'] for o in out], [1, 2, 3, 4])
        self.assertEqual(m.call_count, 3)  # exactly one request per page

    def test_request_all_pages_respects_max(self):
        client = APIFootballV3Client(api_key='x')
        page = {'response': [{'a': 1}], 'paging': {'current': 1, 'total': 999}}
        with mock.patch.object(client, '_request', return_value=page) as m:
            client._request_all_pages('odds', {}, max_pages=5)
        self.assertEqual(m.call_count, 5)

    def test_get_odds_single_page_by_default(self):
        client = APIFootballV3Client(api_key='x')
        with mock.patch.object(client, '_request', return_value={'response': [{'x': 1}], 'paging': {'total': 3}}) as m:
            out = client.get_odds(fixture_id=42)
        self.assertEqual(out, [{'x': 1}])
        self.assertEqual(m.call_count, 1)  # per-fixture stays one call

    def test_get_fixtures_ids_batch_param(self):
        client = APIFootballV3Client(api_key='x')
        captured = {}
        def fake_request(endpoint, params=None):
            captured['params'] = params
            return {'response': []}
        with mock.patch.object(client, '_request', side_effect=fake_request):
            client.get_fixtures(ids=[10, 20, 30])
        self.assertEqual(captured['params']['ids'], '10-20-30')


class BulkOddsTaskTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.home = Team.objects.create(name='Home FC', api_team_id='1')
        self.away = Team.objects.create(name='Away FC', api_team_id='2')
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away,
            api_id='v3_5001', match_date=timezone.now(),
            status=FootballFixture.FixtureStatus.SCHEDULED,
        )

    def _bulk_odds_response(self):
        # Shape of an API-Football /odds response item (grouped by fixture).
        return [{
            'fixture': {'id': 5001},
            'league': {'id': 39},
            'bookmakers': [{
                'id': 8, 'name': 'bet365',
                'bets': [{
                    'id': 1, 'name': 'Match Winner',
                    'values': [
                        {'value': 'Home', 'odd': '2.10'},
                        {'value': 'Draw', 'odd': '3.30'},
                        {'value': 'Away', 'odd': '3.50'},
                    ],
                }],
            }],
        }]

    def test_bulk_task_processes_and_marks_updated(self):
        from . import tasks_api_football_v3 as T
        fake_client = mock.Mock()
        fake_client.get_odds.return_value = self._bulk_odds_response()
        with mock.patch.object(T, 'get_current_season', return_value=2024), \
             mock.patch.object(T, 'APIFootballV3Client', return_value=fake_client):
            result = T.fetch_odds_for_league_date_v3_task.run(self.league.id, '2024-08-01')

        # One bulk call, scoped to the league+season+date, paginated.
        fake_client.get_odds.assert_called_once()
        _, kwargs = fake_client.get_odds.call_args
        self.assertEqual(kwargs.get('league_id'), 39)
        self.assertTrue(kwargs.get('paginate'))
        self.assertEqual(kwargs.get('date'), '2024-08-01')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['fixtures'], 1)
        self.fixture.refresh_from_db()
        self.assertIsNotNone(self.fixture.last_odds_update)
        # Odds were actually written for the fixture.
        self.assertTrue(self.fixture.markets.filter(category__name='Match Winner').exists())


class GlobalEventFetchTests(TestCase):
    """
    fetch_events_global_v3_task replaced the old per-league chord (one API
    request per league, every cycle) with a single global date-range
    request whose response is fanned out to leagues locally -- see the
    task's docstring for why the chord was a quota-burning bottleneck at
    scale (1000+ tracked leagues).
    """

    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer', active=True)
        self.other_league = League.objects.create(name='La Liga', api_id='v3_140', sport_key='soccer', active=True)

    def _fixture_item(self, league_id, fixture_id, home='Home FC', away='Away FC'):
        return {
            'fixture': {'id': fixture_id, 'date': '2024-08-01T15:00:00+00:00', 'status': {'short': 'NS'}},
            'league': {'id': league_id},
            'teams': {'home': {'id': 1, 'name': home}, 'away': {'id': 2, 'name': away}},
            'goals': {'home': None, 'away': None},
        }

    def test_single_global_request_covers_every_tracked_league(self):
        from . import tasks_api_football_v3 as T

        fake_client = mock.Mock()
        fake_client.get_fixtures.return_value = [
            self._fixture_item(39, 5001, 'Arsenal', 'Chelsea'),
            self._fixture_item(140, 5002, 'Barcelona', 'Real Madrid'),
        ]
        with mock.patch.object(T, 'APIFootballV3Client', return_value=fake_client):
            result = T.fetch_events_global_v3_task.run()

        # Exactly one API call total, regardless of how many leagues are tracked.
        fake_client.get_fixtures.assert_called_once()
        _, kwargs = fake_client.get_fixtures.call_args
        self.assertNotIn('league_id', kwargs)

        self.assertEqual(result[0]['status'], 'success')
        self.assertEqual(result[0]['events_processed'], 2)
        self.assertTrue(FootballFixture.objects.filter(api_id='v3_5001', league=self.league).exists())
        self.assertTrue(FootballFixture.objects.filter(api_id='v3_5002', league=self.other_league).exists())

        self.league.refresh_from_db()
        self.other_league.refresh_from_db()
        self.assertIsNotNone(self.league.last_fetched_events)
        self.assertIsNotNone(self.other_league.last_fetched_events)

    def test_fixtures_for_untracked_leagues_are_skipped(self):
        from . import tasks_api_football_v3 as T

        fake_client = mock.Mock()
        fake_client.get_fixtures.return_value = [self._fixture_item(9999, 5003)]
        with mock.patch.object(T, 'APIFootballV3Client', return_value=fake_client):
            result = T.fetch_events_global_v3_task.run()

        self.assertEqual(result[0]['events_processed'], 0)
        self.assertFalse(FootballFixture.objects.filter(api_id='v3_5003').exists())

    def test_retries_on_api_error(self):
        from . import tasks_api_football_v3 as T
        from .api_football_v3_client import APIFootballV3Exception

        fake_client = mock.Mock()
        fake_client.get_fixtures.side_effect = APIFootballV3Exception("boom")
        with mock.patch.object(T, 'APIFootballV3Client', return_value=fake_client):
            task = T.fetch_events_global_v3_task
            task.push_request(retries=0)
            try:
                with self.assertRaises(APIFootballV3Exception):
                    task.run()
            finally:
                task.pop_request()


class StandaloneOddsDispatchTests(TestCase):
    """
    dispatch_odds_fetching_after_events_v3_task must also work when invoked on
    its own periodic schedule (no chord results), since CELERY_RESULT_BACKEND=
    'django-db' makes the events-fetch chord's callback unreliable at scale.
    """

    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.home = Team.objects.create(name='Home FC', api_team_id='1')
        self.away = Team.objects.create(name='Away FC', api_team_id='2')
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away,
            api_id='v3_5001', match_date=timezone.now() + timedelta(hours=2),
            status=FootballFixture.FixtureStatus.SCHEDULED,
        )

    def test_runs_with_no_argument_and_dispatches_stale_fixtures(self):
        from . import tasks_api_football_v3 as T
        with mock.patch.object(T, 'group') as fake_group:
            fake_group.return_value.apply_async = mock.Mock()
            T.dispatch_odds_fetching_after_events_v3_task.run()

        fake_group.assert_called_once()
        dispatched_tasks = fake_group.call_args[0][0]
        self.assertEqual(len(dispatched_tasks), 1)  # one league-day pair: our fixture


class ApiFootballBulkOddsTests(TestCase):
    """Legacy apifootball.com: bulk odds by date instead of one call per fixture."""

    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='152', sport_key='soccer')
        self.home = Team.objects.create(name='Home FC')
        self.away = Team.objects.create(name='Away FC')
        # apifootball fixtures store the raw match_id as api_id (no prefix).
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away,
            api_id='58819', match_date=timezone.now(),
            status=FootballFixture.FixtureStatus.SCHEDULED,
        )

    def test_bulk_by_date_groups_by_match_id(self):
        from . import tasks_apifootball as T
        bulk = [
            {'match_id': '58819', 'odd_bookmakers': [{'bookmaker_name': 'bet365'}]},
            {'match_id': '99999', 'odd_bookmakers': [{'bookmaker_name': 'bet365'}]},  # not ours
        ]
        fake_client = mock.Mock()
        fake_client.get_odds.return_value = bulk
        with mock.patch.object(T, 'APIFootballClient', return_value=fake_client), \
             mock.patch.object(T, '_process_apifootball_odds_data') as proc:
            result = T.fetch_odds_for_date_task.run('2024-08-01')

        fake_client.get_odds.assert_called_once_with(date_from='2024-08-01', date_to='2024-08-01')
        # Only our fixture's element is processed, exactly once.
        self.assertEqual(proc.call_count, 1)
        self.assertEqual(proc.call_args.args[0].id, self.fixture.id)
        self.assertEqual(result['fixtures'], 1)
        self.fixture.refresh_from_db()
        self.assertIsNotNone(self.fixture.last_odds_update)


class TheOddsApiBulkOddsTests(TestCase):
    """Legacy The Odds API: one /sports/{sport}/odds call per league (eventIds batch)."""

    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='soccer_epl', sport_key='soccer')
        self.home = Team.objects.create(name='Home FC')
        self.away = Team.objects.create(name='Away FC')
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away,
            api_id='evt_abc', match_date=timezone.now() + timezone.timedelta(hours=6),
            status=FootballFixture.FixtureStatus.SCHEDULED,
        )

    def test_bulk_per_league_uses_event_ids_and_applies(self):
        from . import tasks_theoddsapi_backup as T
        events = [
            {'id': 'evt_abc', 'home_team': 'Home FC', 'away_team': 'Away FC', 'bookmakers': []},
            {'id': 'evt_other', 'home_team': 'X', 'away_team': 'Y', 'bookmakers': []},  # not ours
        ]
        fake_client = mock.Mock()
        fake_client.get_odds.return_value = events
        with mock.patch.object(T, 'TheOddsAPIClient', return_value=fake_client):
            result = T.fetch_odds_for_league_bulk_task.run(self.league.id)

        # One bulk call, scoped to the league sport_key with our event id batch.
        fake_client.get_odds.assert_called_once()
        _, kwargs = fake_client.get_odds.call_args
        self.assertEqual(kwargs['sport_key'], 'soccer_epl')
        self.assertEqual(kwargs['event_ids'], ['evt_abc'])
        self.assertEqual(result['fixtures'], 1)
        self.fixture.refresh_from_db()
        self.assertIsNotNone(self.fixture.last_odds_update)
