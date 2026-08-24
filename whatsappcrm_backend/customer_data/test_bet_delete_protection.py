# whatsappcrm_backend/customer_data/test_bet_delete_protection.py
"""
Bet.market_outcome is PROTECT, and these tests are the reason why.

A Bet is a financial/audit record, but everything above it in the reference
chain cascades:

    League / Team -> FootballFixture -> Market -> MarketOutcome -> Bet

While Bet.market_outcome was also CASCADE, deleting *any* of those ancestors
silently deleted the bets underneath. That wasn't hypothetical -- the
odds-refresh pipeline hit exactly this and had to be rewritten to
upsert-in-place -- and Django admin still offers one-click deletion of
Leagues, Teams, Fixtures, Markets and Outcomes to staff, so deleting a single
Team would have wiped every bet ever placed on that team's fixtures.

Each test below deletes at a different level of that chain and asserts the
same two things: the delete is refused, and nothing at all is destroyed.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from football_data_app.models import (
    League, Team, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome,
)
from .models import BetTicket, Bet

User = get_user_model()


class BetDeleteProtectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='protected_bettor', password='x')
        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.home = Team.objects.create(name='Home FC')
        self.away = Team.objects.create(name='Away FC')
        self.bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.category = MarketCategory.objects.create(name='Match Winner')
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away,
            api_id='v3_protect_1', match_date=timezone.now(),
            status=FootballFixture.FixtureStatus.FINISHED,
        )
        self.market = Market.objects.create(
            fixture=self.fixture, bookmaker=self.bookmaker, api_market_key='h2h',
            category=self.category, last_updated_odds_api=timezone.now())
        self.outcome = MarketOutcome.objects.create(
            market=self.market, outcome_name='Home FC', odds=Decimal('2.00'))
        self.ticket = BetTicket.objects.create(
            user=self.user, total_stake=Decimal('10.00'), potential_winnings=Decimal('20.00'),
            status='WON', bet_type='SINGLE', total_odds=Decimal('2.00'))
        self.bet = Bet.objects.create(
            ticket=self.ticket, market_outcome=self.outcome,
            amount=Decimal('10.00'), potential_winnings=Decimal('20.00'), status='WON')

    def assertNothingDestroyed(self):
        """The bet and its whole reference chain must still be intact."""
        self.assertTrue(Bet.objects.filter(id=self.bet.id).exists())
        self.assertTrue(MarketOutcome.objects.filter(id=self.outcome.id).exists())
        self.assertTrue(Market.objects.filter(id=self.market.id).exists())
        self.assertTrue(FootballFixture.objects.filter(id=self.fixture.id).exists())
        # And the money on it is unchanged.
        self.assertEqual(Bet.objects.get(id=self.bet.id).amount, Decimal('10.00'))

    def test_deleting_the_outcome_is_refused(self):
        with self.assertRaises(ProtectedError):
            self.outcome.delete()
        self.assertNothingDestroyed()

    def test_deleting_the_market_is_refused(self):
        with self.assertRaises(ProtectedError):
            self.market.delete()
        self.assertNothingDestroyed()

    def test_deleting_the_fixture_is_refused(self):
        with self.assertRaises(ProtectedError):
            self.fixture.delete()
        self.assertNothingDestroyed()

    def test_deleting_the_team_is_refused(self):
        # The admin path that would previously have wiped every bet ever
        # placed on this team's fixtures.
        with self.assertRaises(ProtectedError):
            self.home.delete()
        self.assertNothingDestroyed()
        self.assertTrue(Team.objects.filter(id=self.home.id).exists())

    def test_deleting_the_league_is_refused(self):
        with self.assertRaises(ProtectedError):
            self.league.delete()
        self.assertNothingDestroyed()
        self.assertTrue(League.objects.filter(id=self.league.id).exists())

    def test_bulk_queryset_delete_is_refused_too(self):
        # Bulk deletes go through the same collector, so they're covered --
        # this is the shape the odds-refresh bug originally took.
        with self.assertRaises(ProtectedError):
            MarketOutcome.objects.filter(market__fixture=self.fixture).delete()
        self.assertNothingDestroyed()

    # ---- what must still be deletable ----

    def test_deleting_the_ticket_still_cascades_to_its_own_bets(self):
        # A ticket owns its legs; that CASCADE is correct and intentional.
        bet_id = self.bet.id
        self.ticket.delete()
        self.assertFalse(Bet.objects.filter(id=bet_id).exists())
        # The market data it referenced is untouched.
        self.assertTrue(MarketOutcome.objects.filter(id=self.outcome.id).exists())

    def test_market_data_with_no_bets_is_still_deletable(self):
        # PROTECT must not freeze ordinary market-data housekeeping.
        spare = MarketOutcome.objects.create(
            market=self.market, outcome_name='Away FC', odds=Decimal('4.00'))
        spare_id = spare.id
        spare.delete()
        self.assertFalse(MarketOutcome.objects.filter(id=spare_id).exists())

    def test_a_whole_fixture_with_no_bets_is_still_deletable(self):
        other = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away,
            api_id='v3_protect_2', match_date=timezone.now(),
            status=FootballFixture.FixtureStatus.FINISHED)
        market = Market.objects.create(
            fixture=other, bookmaker=self.bookmaker, api_market_key='h2h',
            category=self.category, last_updated_odds_api=timezone.now())
        MarketOutcome.objects.create(market=market, outcome_name='Home FC', odds=Decimal('2.00'))

        other.delete()

        self.assertFalse(FootballFixture.objects.filter(id=other.id).exists())
        self.assertFalse(Market.objects.filter(id=market.id).exists())
