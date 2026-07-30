# whatsappcrm_backend/football_data_app/test_api_efficiency.py
"""
Tests for the cost-saving API-Football v3 request changes: /odds pagination,
fixture id batching, and bulk per-league-day odds fetching.
"""
from decimal import Decimal
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
