# whatsappcrm_backend/football_data_app/test_prune_fixtures.py
"""
prune_old_fixtures() safety tests.

Nothing ever pruned fixture/market/odds data, so those tables grow for the
life of the deployment and every hot query (browse, the per-minute live-odds
task, the odds-dispatch sweep) gets slower forever.

The dangerous part is the FK chain:

    FootballFixture -CASCADE-> Market -CASCADE-> MarketOutcome -CASCADE-> Bet

Deleting a fixture silently takes any Bet rows under it too -- destroying
settled betting history, which is financial/audit data. The whole point of
these tests is to prove the pruner never does that, no matter how old the
fixture is.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customer_data.models import BetTicket, Bet
from django.contrib.auth import get_user_model

from .models import League, Team, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome
from .utils import prune_old_fixtures

User = get_user_model()


class PruneOldFixturesTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.category = MarketCategory.objects.create(name='Match Winner')
        self.user = User.objects.create_user(username='prune_bettor', password='x')

    def _fixture(self, name, status, days_ago, with_outcome=True):
        home = Team.objects.create(name=f'{name}H')
        away = Team.objects.create(name=f'{name}A')
        fx = FootballFixture.objects.create(
            league=self.league, home_team=home, away_team=away, api_id=f'v3_{name}',
            status=status, match_date=timezone.now() - timedelta(days=days_ago),
        )
        if with_outcome:
            market = Market.objects.create(
                fixture=fx, bookmaker=self.bookmaker, api_market_key='h2h',
                category=self.category, last_updated_odds_api=timezone.now())
            MarketOutcome.objects.create(market=market, outcome_name='Home', odds=Decimal('2.00'))
        return fx

    def _place_bet_on(self, fixture):
        outcome = MarketOutcome.objects.get(market__fixture=fixture)
        ticket = BetTicket.objects.create(
            user=self.user, total_stake=Decimal('10.00'), potential_winnings=Decimal('20.00'),
            status='WON', bet_type='SINGLE', total_odds=Decimal('2.00'))
        return Bet.objects.create(
            ticket=ticket, market_outcome=outcome,
            amount=Decimal('10.00'), potential_winnings=Decimal('20.00'), status='WON')

    # ---- the safety guarantee ----

    def test_a_fixture_with_a_bet_is_never_deleted_however_old(self):
        fx = self._fixture('betted', FootballFixture.FixtureStatus.FINISHED, days_ago=3650)
        bet = self._place_bet_on(fx)

        prune_old_fixtures(older_than_days=180)

        self.assertTrue(FootballFixture.objects.filter(id=fx.id).exists())
        # And crucially the financial record survives intact.
        self.assertTrue(Bet.objects.filter(id=bet.id).exists())

    def test_settled_bet_history_survives_a_prune_that_deletes_its_neighbours(self):
        kept = self._fixture('kept', FootballFixture.FixtureStatus.FINISHED, days_ago=400)
        bet = self._place_bet_on(kept)
        doomed = self._fixture('doomed', FootballFixture.FixtureStatus.FINISHED, days_ago=400)

        result = prune_old_fixtures(older_than_days=180)

        self.assertEqual(result['deleted'], 1)
        self.assertFalse(FootballFixture.objects.filter(id=doomed.id).exists())
        self.assertTrue(FootballFixture.objects.filter(id=kept.id).exists())
        self.assertTrue(Bet.objects.filter(id=bet.id).exists())
        self.assertEqual(Bet.objects.get(id=bet.id).amount, Decimal('10.00'))

    # ---- what it does prune ----

    def test_old_finished_fixture_with_no_bets_is_deleted_with_its_markets(self):
        fx = self._fixture('old', FootballFixture.FixtureStatus.FINISHED, days_ago=400)
        market_ids = list(Market.objects.filter(fixture=fx).values_list('id', flat=True))

        result = prune_old_fixtures(older_than_days=180)

        self.assertEqual(result['deleted'], 1)
        self.assertFalse(FootballFixture.objects.filter(id=fx.id).exists())
        self.assertFalse(Market.objects.filter(id__in=market_ids).exists())

    def test_cancelled_and_postponed_are_pruned_too(self):
        self._fixture('cancelled', FootballFixture.FixtureStatus.CANCELLED, days_ago=400)
        self._fixture('postponed', FootballFixture.FixtureStatus.POSTPONED, days_ago=400)

        result = prune_old_fixtures(older_than_days=180)

        self.assertEqual(result['deleted'], 2)

    # ---- what it must leave alone ----

    def test_recent_finished_fixture_is_kept(self):
        fx = self._fixture('recent', FootballFixture.FixtureStatus.FINISHED, days_ago=10)
        prune_old_fixtures(older_than_days=180)
        self.assertTrue(FootballFixture.objects.filter(id=fx.id).exists())

    def test_scheduled_and_live_fixtures_are_never_pruned(self):
        # Guards against a clock/data glitch (a stale SCHEDULED row with an
        # old match_date, or a LIVE fixture) taking out bettable inventory.
        scheduled = self._fixture('sched', FootballFixture.FixtureStatus.SCHEDULED, days_ago=400)
        live = self._fixture('live', FootballFixture.FixtureStatus.LIVE, days_ago=400)

        result = prune_old_fixtures(older_than_days=180)

        self.assertEqual(result['deleted'], 0)
        self.assertTrue(FootballFixture.objects.filter(id=scheduled.id).exists())
        self.assertTrue(FootballFixture.objects.filter(id=live.id).exists())

    def test_dry_run_reports_but_deletes_nothing(self):
        fx = self._fixture('dry', FootballFixture.FixtureStatus.FINISHED, days_ago=400)

        result = prune_old_fixtures(older_than_days=180, dry_run=True)

        self.assertEqual(result['eligible'], 1)
        self.assertEqual(result['deleted'], 0)
        self.assertTrue(FootballFixture.objects.filter(id=fx.id).exists())

    def test_batching_deletes_everything_across_multiple_batches(self):
        for i in range(5):
            self._fixture(f'batch{i}', FootballFixture.FixtureStatus.FINISHED, days_ago=400)

        result = prune_old_fixtures(older_than_days=180, batch_size=2)

        self.assertEqual(result['deleted'], 5)
        self.assertEqual(
            FootballFixture.objects.filter(status=FootballFixture.FixtureStatus.FINISHED).count(), 0)
