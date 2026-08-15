# whatsappcrm_backend/football_data_app/test_odds_refresh_preserves_bets.py
"""
Regression coverage for a severe data-loss bug: all three odds-fetching
pipelines (API-Football v3, legacy APIFootball, legacy TheOddsAPI backup)
used to delete a fixture's Market rows and recreate them from scratch on
every odds-refresh cycle. Market -> MarketOutcome -> Bet are all
on_delete=CASCADE, so that silently cascade-deleted any Bet a user had
already placed against one of those outcomes -- not "settled late", actually
destroyed, leaving the BetTicket orphaned with zero Bet rows and no way to
ever pay out or refund it.

The fix upserts Market/MarketOutcome in place (update_or_create) instead of
delete+recreate, so a Bet's foreign key stays valid across every refresh.
These tests place a bet, then re-run each pipeline's odds-processing
function for the exact same fixture/bookmaker/market -- as the real
Celery Beat schedule does every few minutes -- and assert the bet survives.
"""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from conversations.models import Contact
from customer_data.models import CustomerProfile, UserWallet, BetTicket, Bet
from .models import League, Team, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome


class _BaseOddsRefreshTestCase(TestCase):
    # Each pipeline derives its Bookmaker.api_bookmaker_key lookup differently
    # (v3 uses the numeric bookmaker id when present; the legacy pipeline only
    # ever has a bookmaker name to key off). Subclasses override this so the
    # odds payload's bookmaker actually resolves to the same Bookmaker row the
    # pre-placed bet's Market/MarketOutcome were created against -- otherwise
    # the pipeline would just create an unrelated Bookmaker/Market and the
    # test would pass without ever touching the bet it's meant to protect.
    BOOKMAKER_API_KEY = '8'

    def setUp(self):
        self.user = User.objects.create_user('oddsrefreshbettor')
        UserWallet.objects.filter(user=self.user).update(balance=Decimal('500.00'))
        contact = Contact.objects.create(whatsapp_id='263779990099')
        CustomerProfile.objects.create(contact=contact, user=self.user,
                                       date_of_birth=timezone.localdate().replace(year=1990))

        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.home = Team.objects.create(name='Home Team')
        self.away = Team.objects.create(name='Away Team')
        self.bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key=self.BOOKMAKER_API_KEY)
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away, api_id='v3_1001',
            match_date=timezone.now() + timedelta(hours=4),
            status=FootballFixture.FixtureStatus.SCHEDULED)
        self.category = MarketCategory.objects.create(name='Match Winner')
        self.market = Market.objects.create(
            fixture=self.fixture, bookmaker=self.bookmaker, api_market_key='h2h',
            category=self.category, last_updated_odds_api=timezone.now())
        self.outcome = MarketOutcome.objects.create(
            market=self.market, outcome_name='Home Team', odds=Decimal('2.00'))

    def _place_bet(self):
        ticket = BetTicket.objects.create(
            user=self.user, total_stake=Decimal('10.00'),
            potential_winnings=Decimal('20.00'), status='PENDING', bet_type='SINGLE')
        bet = Bet.objects.create(
            ticket=ticket, market_outcome=self.outcome,
            amount=Decimal('10.00'), potential_winnings=Decimal('20.00'), status='PENDING')
        return ticket, bet


class ApiFootballV3OddsRefreshTests(_BaseOddsRefreshTestCase):
    """The actively-scheduled pipeline (settle-football-scores-v3's sibling,
    fetch-football-odds-v3, runs every 30 min via _process_api_football_v3_odds_data)."""

    def _odds_payload(self, home_odd='2.10'):
        return [{
            'bookmakers': [{
                'id': 8,
                'name': 'bet365',
                'bets': [{
                    'id': 1,
                    'name': 'Match Winner',
                    'values': [
                        {'value': 'Home', 'odd': home_odd},
                        {'value': 'Draw', 'odd': '3.20'},
                        {'value': 'Away', 'odd': '3.50'},
                    ],
                }],
            }],
        }]

    def test_refresh_does_not_delete_a_placed_bet(self):
        ticket, bet = self._place_bet()

        from .tasks_api_football_v3 import _process_api_football_v3_odds_data
        _process_api_football_v3_odds_data(self.fixture, self._odds_payload())

        # The Bet row -- and thus the ticket's only evidence of what was
        # staked -- must still exist, not be cascade-deleted.
        self.assertTrue(Bet.objects.filter(id=bet.id).exists())
        ticket.refresh_from_db()
        self.assertEqual(ticket.bets.count(), 1)

    def test_refresh_updates_odds_in_place_without_changing_bet_payout(self):
        ticket, bet = self._place_bet()
        original_outcome_id = bet.market_outcome_id

        from .tasks_api_football_v3 import _process_api_football_v3_odds_data
        _process_api_football_v3_odds_data(self.fixture, self._odds_payload(home_odd='2.50'))

        bet.refresh_from_db()
        # Same MarketOutcome row (same id), just with its odds updated --
        # not a new row that would have orphaned the existing Bet.
        self.assertEqual(bet.market_outcome_id, original_outcome_id)
        self.outcome.refresh_from_db()
        self.assertEqual(self.outcome.odds, Decimal('2.50'))
        # The already-placed bet's own payout is unaffected by the later
        # odds move -- it was fixed at placement time.
        self.assertEqual(bet.potential_winnings, Decimal('20.00'))

    def test_outcome_missing_from_a_later_refresh_is_deactivated_not_deleted(self):
        ticket, bet = self._place_bet()

        from .tasks_api_football_v3 import _process_api_football_v3_odds_data
        # Same market (so it's actually upserted, touching self.market), but
        # this refresh's response no longer includes the "Home" outcome the
        # bet was placed on -- e.g. the bookmaker pulled that specific line.
        _process_api_football_v3_odds_data(self.fixture, [{
            'bookmakers': [{
                'id': 8,
                'name': 'bet365',
                'bets': [{
                    'id': 1,
                    'name': 'Match Winner',
                    'values': [
                        {'value': 'Draw', 'odd': '3.20'},
                        {'value': 'Away', 'odd': '3.50'},
                    ],
                }],
            }],
        }])

        self.assertTrue(Bet.objects.filter(id=bet.id).exists())
        self.outcome.refresh_from_db()
        self.assertFalse(self.outcome.is_active)


class LegacyApiFootballOddsRefreshTests(_BaseOddsRefreshTestCase):
    """Legacy pipeline, not currently scheduled, but fixed for the same reason."""

    # This pipeline only ever keys a Bookmaker by name.lower().replace(' ', '_'),
    # never a numeric id -- see BOOKMAKER_API_KEY's docstring above.
    BOOKMAKER_API_KEY = 'bet365'

    def test_refresh_does_not_delete_a_placed_bet(self):
        ticket, bet = self._place_bet()

        from .tasks_apifootball import _process_apifootball_odds_data
        _process_apifootball_odds_data(self.fixture, {
            'odd_bookmakers': [{
                'bookmaker_name': 'bet365',
                'bookmaker_odds': [{'odd_1': '2.20', 'odd_x': '3.10', 'odd_2': '3.40'}],
            }],
        })

        self.assertTrue(Bet.objects.filter(id=bet.id).exists())
        ticket.refresh_from_db()
        self.assertEqual(ticket.bets.count(), 1)
