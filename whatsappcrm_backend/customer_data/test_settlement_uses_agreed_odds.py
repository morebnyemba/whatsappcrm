# whatsappcrm_backend/customer_data/test_settlement_uses_agreed_odds.py
"""
A winning ticket must pay out at the odds the bettor agreed to when they
placed the bet -- not whatever the odds happen to be when settlement runs.

settle_ticket() computed winnings as `total_odds *= bet.market_outcome.odds`,
reading the *live* MarketOutcome row at settlement time. Before in-play
betting existed a fixture's odds effectively froze at kick-off, so this was
usually harmless. Now that live odds refresh every 60 seconds throughout the
match, the price on a winning selection has typically collapsed (or spiked)
by full time, so settlement paid an amount the bettor never agreed to --
in either direction.
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from football_data_app.models import (
    League, Team, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome,
)
from football_data_app.utils import settle_ticket
from .models import BetTicket, Bet, UserWallet

User = get_user_model()


def settle(ticket_id):
    """settle_ticket() with the WhatsApp settlement-notification task stubbed
    out -- these tests are about payout arithmetic, not message delivery, and
    dispatching to a real broker would make them network-dependent."""
    with patch('football_data_app.tasks.send_bet_ticket_settlement_notification_task.delay'):
        return settle_ticket(ticket_id)


class SettlementUsesAgreedOddsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='odds_bettor', password='x')
        self.wallet, _ = UserWallet.objects.get_or_create(
            user=self.user, defaults={'balance': Decimal('100.00')})
        self.wallet.balance = Decimal('100.00')
        self.wallet.save()

        self.league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        self.home = Team.objects.create(name='Home FC')
        self.away = Team.objects.create(name='Away FC')
        self.bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.category = MarketCategory.objects.create(name='Match Winner')
        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.home, away_team=self.away,
            api_id='v3_odds_1', match_date=timezone.now(),
            status=FootballFixture.FixtureStatus.FINISHED)
        self.market = Market.objects.create(
            fixture=self.fixture, bookmaker=self.bookmaker, api_market_key='h2h',
            category=self.category, last_updated_odds_api=timezone.now())

    def _placed_ticket(self, agreed_odds, stake=Decimal('10.00')):
        """A ticket placed at `agreed_odds`, mirroring what
        process_bet_ticket_submission persists at placement time."""
        outcome = MarketOutcome.objects.create(
            market=self.market, outcome_name='Home FC', odds=agreed_odds)
        ticket = BetTicket.objects.create(
            user=self.user, total_stake=stake,
            potential_winnings=stake * agreed_odds,
            status='PLACED', bet_type='SINGLE', total_odds=agreed_odds)
        bet = Bet.objects.create(
            ticket=ticket, market_outcome=outcome, odds=agreed_odds,
            amount=stake, potential_winnings=stake * agreed_odds, status='PENDING')
        return ticket, bet, outcome

    def test_payout_uses_placement_odds_not_collapsed_live_odds(self):
        # Bettor backs Home at 2.00 pre-match: $10 stake -> $20 payout.
        ticket, bet, outcome = self._placed_ticket(Decimal('2.00'))
        balance_before = self.wallet.balance

        # Home goes 2-0 up; the live-odds pipeline marks the price down to 1.05.
        outcome.odds = Decimal('1.05')
        outcome.save(update_fields=['odds'])

        bet.status = 'WON'
        bet.save(update_fields=['status'])
        settle(ticket.id)

        self.wallet.refresh_from_db()
        payout = self.wallet.balance - balance_before
        # Must be the agreed $20.00, not $10.50 at the collapsed live price.
        self.assertEqual(payout, Decimal('20.00'))

    def test_payout_uses_placement_odds_not_drifted_out_live_odds(self):
        # The mirror case: the house must not overpay either.
        ticket, bet, outcome = self._placed_ticket(Decimal('1.50'))
        balance_before = self.wallet.balance

        # Underdog falls behind, live price drifts out to 8.00, then wins.
        outcome.odds = Decimal('8.00')
        outcome.save(update_fields=['odds'])

        bet.status = 'WON'
        bet.save(update_fields=['status'])
        settle(ticket.id)

        self.wallet.refresh_from_db()
        payout = self.wallet.balance - balance_before
        self.assertEqual(payout, Decimal('15.00'))

    def test_accumulator_pays_the_product_of_agreed_odds(self):
        stake = Decimal('10.00')
        o1 = MarketOutcome.objects.create(market=self.market, outcome_name='Leg A', odds=Decimal('2.00'))
        o2 = MarketOutcome.objects.create(market=self.market, outcome_name='Leg B', odds=Decimal('3.00'))
        ticket = BetTicket.objects.create(
            user=self.user, total_stake=stake, potential_winnings=stake * Decimal('6.00'),
            status='PLACED', bet_type='MULTIPLE', total_odds=Decimal('6.00'))
        b1 = Bet.objects.create(ticket=ticket, market_outcome=o1, odds=Decimal('2.00'),
                                amount=stake, potential_winnings=stake * Decimal('2.00'), status='WON')
        b2 = Bet.objects.create(ticket=ticket, market_outcome=o2, odds=Decimal('3.00'),
                                amount=stake, potential_winnings=stake * Decimal('3.00'), status='WON')
        balance_before = self.wallet.balance

        # Both legs' live prices move after placement.
        o1.odds = Decimal('1.10'); o1.save(update_fields=['odds'])
        o2.odds = Decimal('1.20'); o2.save(update_fields=['odds'])

        settle(ticket.id)

        self.wallet.refresh_from_db()
        # 10 * (2.00 * 3.00) = 60.00, not 10 * (1.10 * 1.20) = 13.20
        self.assertEqual(self.wallet.balance - balance_before, Decimal('60.00'))

    def test_pushed_leg_is_treated_as_odds_one_and_does_not_use_live_odds(self):
        stake = Decimal('10.00')
        won = MarketOutcome.objects.create(market=self.market, outcome_name='Won leg', odds=Decimal('2.00'))
        push = MarketOutcome.objects.create(market=self.market, outcome_name='Push leg', odds=Decimal('3.00'))
        ticket = BetTicket.objects.create(
            user=self.user, total_stake=stake, potential_winnings=stake * Decimal('6.00'),
            status='PLACED', bet_type='MULTIPLE', total_odds=Decimal('6.00'))
        Bet.objects.create(ticket=ticket, market_outcome=won, odds=Decimal('2.00'),
                           amount=stake, potential_winnings=stake * Decimal('2.00'), status='WON')
        Bet.objects.create(ticket=ticket, market_outcome=push, odds=Decimal('3.00'),
                           amount=stake, potential_winnings=stake * Decimal('3.00'), status='REFUNDED')
        balance_before = self.wallet.balance

        won.odds = Decimal('1.01'); won.save(update_fields=['odds'])

        settle(ticket.id)

        self.wallet.refresh_from_db()
        # Push counts as 1.0, so 10 * 2.00 = 20.00 at the agreed price.
        self.assertEqual(self.wallet.balance - balance_before, Decimal('20.00'))


class LegacyBetOddsRecoveryTests(TestCase):
    """Bets placed before Bet.odds existed have odds=NULL. They must still
    settle at their agreed price, not the live one -- potential_winnings was
    stored as amount * odds at placement, so it's exactly recoverable."""

    def setUp(self):
        self.user = User.objects.create_user(username='legacy_bettor', password='x')
        self.wallet, _ = UserWallet.objects.get_or_create(
            user=self.user, defaults={'balance': Decimal('100.00')})
        self.wallet.balance = Decimal('100.00')
        self.wallet.save()
        league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        home = Team.objects.create(name='Legacy Home')
        away = Team.objects.create(name='Legacy Away')
        bookmaker = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        category = MarketCategory.objects.create(name='Match Winner')
        fixture = FootballFixture.objects.create(
            league=league, home_team=home, away_team=away, api_id='v3_legacy_1',
            match_date=timezone.now(), status=FootballFixture.FixtureStatus.FINISHED)
        self.market = Market.objects.create(
            fixture=fixture, bookmaker=bookmaker, api_market_key='h2h',
            category=category, last_updated_odds_api=timezone.now())

    def test_legacy_bet_with_null_odds_still_settles_at_its_agreed_price(self):
        stake = Decimal('10.00')
        outcome = MarketOutcome.objects.create(
            market=self.market, outcome_name='Legacy Home', odds=Decimal('2.50'))
        ticket = BetTicket.objects.create(
            user=self.user, total_stake=stake, potential_winnings=stake * Decimal('2.50'),
            status='PLACED', bet_type='SINGLE', total_odds=Decimal('2.50'))
        # odds deliberately NOT set -- this is a pre-migration row.
        bet = Bet.objects.create(
            ticket=ticket, market_outcome=outcome,
            amount=stake, potential_winnings=stake * Decimal('2.50'), status='WON')
        self.assertIsNone(bet.odds)
        self.assertEqual(bet.agreed_odds, Decimal('2.500'))

        balance_before = self.wallet.balance
        outcome.odds = Decimal('1.02')  # live price collapsed during the match
        outcome.save(update_fields=['odds'])

        settle(ticket.id)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance - balance_before, Decimal('25.00'))
