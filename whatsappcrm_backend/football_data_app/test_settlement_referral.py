# whatsappcrm_backend/football_data_app/test_settlement_referral.py
"""
settle_ticket() (football_data_app/utils.py) had no test coverage at all
before the affiliate win-deduction hook was added to its WON branch. These
tests cover: the existing win-payout behavior still works unchanged, and the
new agent win-deduction fires (or doesn't) exactly when expected — without
ever blocking the referred user's own payout, even if the deduction fails.
"""
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from conversations.models import Contact
from customer_data.models import CustomerProfile, UserWallet, BetTicket, Bet
from referrals.models import ReferralProfile, ReferralSettings, AgentDeduction
from referrals.utils import get_or_create_referral_profile
from .models import League, Team, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome
from .utils import settle_ticket


class SettleTicketAgentWinDeductionTests(TestCase):
    def setUp(self):
        self.agent_user = User.objects.create_user('settleagent')
        self.player_user = User.objects.create_user('settleplayer')
        UserWallet.objects.filter(user=self.player_user).update(balance=Decimal('0.00'))

        self.agent_profile = get_or_create_referral_profile(self.agent_user)
        self.agent_profile.is_agent = True
        self.agent_profile.save(update_fields=['is_agent'])
        self.player_profile = get_or_create_referral_profile(self.player_user)
        self.player_profile.referred_by = self.agent_user
        self.player_profile.save(update_fields=['referred_by'])

        settings = ReferralSettings.load()
        settings.agent_win_deduction_percentage = Decimal('0.2500')
        settings.save()

        player_contact = Contact.objects.create(whatsapp_id='263779990001')
        CustomerProfile.objects.create(contact=player_contact, user=self.player_user,
                                       date_of_birth=timezone.localdate().replace(year=1990))

        league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        home = Team.objects.create(name='Man City'); away = Team.objects.create(name='Liverpool')
        bk = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        fixture = FootballFixture.objects.create(
            league=league, home_team=home, away_team=away, api_id='v3_settle1',
            match_date=timezone.now() - timedelta(hours=2),
            status=FootballFixture.FixtureStatus.FINISHED)
        cat = MarketCategory.objects.create(name='Match Winner')
        market = Market.objects.create(fixture=fixture, bookmaker=bk, api_market_key='h2h',
                                       category=cat, last_updated_odds_api=timezone.now())
        self.outcome = MarketOutcome.objects.create(market=market, outcome_name='Home', odds=Decimal('2.50'))

    def _make_ticket(self, stake, bet_status):
        ticket = BetTicket.objects.create(
            user=self.player_user, total_stake=stake, status=BetTicket.TicketStatus.PLACED)
        Bet.objects.create(
            ticket=ticket, market_outcome=self.outcome, amount=stake,
            potential_winnings=stake * self.outcome.odds, status=bet_status)
        return ticket

    @patch('referrals.utils.send_bonus_notification_task')
    @patch('football_data_app.tasks.send_bet_ticket_settlement_notification_task')
    def test_won_ticket_still_pays_out_user_and_deducts_agent(self, mock_settlement_notif, mock_bonus_notif):
        ticket = self._make_ticket(Decimal('10.00'), Bet.BetStatus.WON)
        settle_ticket(ticket.id)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'WON')

        self.player_user.wallet.refresh_from_db()
        self.assertEqual(self.player_user.wallet.balance, Decimal('25.00'))  # 10 * 2.50

        self.agent_user.wallet.refresh_from_db()
        self.assertEqual(self.agent_user.wallet.balance, Decimal('-6.25'))  # 25 * 0.25

        deduction = AgentDeduction.objects.get(bet_ticket=ticket)
        self.assertEqual(deduction.deduction_amount, Decimal('6.25'))
        self.assertEqual(deduction.win_amount, Decimal('25.00'))

    @patch('referrals.utils.send_bonus_notification_task')
    @patch('football_data_app.tasks.send_bet_ticket_settlement_notification_task')
    def test_won_ticket_payout_unaffected_when_player_has_no_agent(self, mock_settlement_notif, mock_bonus_notif):
        self.player_profile.referred_by = None
        self.player_profile.save(update_fields=['referred_by'])

        ticket = self._make_ticket(Decimal('10.00'), Bet.BetStatus.WON)
        settle_ticket(ticket.id)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'WON')
        self.player_user.wallet.refresh_from_db()
        self.assertEqual(self.player_user.wallet.balance, Decimal('25.00'))
        self.assertEqual(AgentDeduction.objects.count(), 0)

    @patch('referrals.utils.apply_agent_win_deduction', side_effect=RuntimeError('boom'))
    @patch('football_data_app.tasks.send_bet_ticket_settlement_notification_task')
    def test_user_payout_survives_a_deduction_failure(self, mock_settlement_notif, mock_deduction):
        """A broken/erroring deduction must never roll back the player's own payout."""
        ticket = self._make_ticket(Decimal('10.00'), Bet.BetStatus.WON)
        settle_ticket(ticket.id)  # must not raise

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'WON')
        self.player_user.wallet.refresh_from_db()
        self.assertEqual(self.player_user.wallet.balance, Decimal('25.00'))
