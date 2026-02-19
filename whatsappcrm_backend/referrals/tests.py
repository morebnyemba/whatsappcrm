from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User

from referrals.models import ReferralProfile, ReferralSettings, AgentEarning
from referrals.utils import (
    get_or_create_referral_profile,
    link_referral,
    award_agent_commission,
)
from customer_data.models import BetTicket, UserWallet


class AgentEarningModelTest(TestCase):
    """Tests for the AgentEarning model."""

    def setUp(self):
        self.agent_user = User.objects.create_user(username='agent1', password='pass123')
        self.referred_user = User.objects.create_user(username='bettor1', password='pass123')
        self.agent_profile = get_or_create_referral_profile(self.agent_user)
        self.referred_profile = get_or_create_referral_profile(self.referred_user)
        self.referred_profile.referred_by = self.agent_user
        self.referred_profile.save()

    def test_agent_earning_creation(self):
        """Test that AgentEarning records can be created correctly."""
        ticket = BetTicket.objects.create(
            user=self.referred_user,
            total_stake=Decimal('100.00'),
            status=BetTicket.TicketStatus.LOST,
        )
        earning = AgentEarning.objects.create(
            agent_profile=self.agent_profile,
            bet_ticket=ticket,
            referred_user=self.referred_user,
            bet_stake=Decimal('100.00'),
            commission_percentage=Decimal('0.0500'),
            commission_amount=Decimal('5.00'),
        )
        self.assertEqual(earning.commission_amount, Decimal('5.00'))
        self.assertEqual(earning.agent_profile, self.agent_profile)

    def test_total_earnings_property(self):
        """Test the total_earnings property on ReferralProfile."""
        self.assertEqual(self.agent_profile.total_earnings, Decimal('0.00'))

        for i in range(3):
            ticket = BetTicket.objects.create(
                user=self.referred_user,
                total_stake=Decimal('100.00'),
                status=BetTicket.TicketStatus.LOST,
            )
            AgentEarning.objects.create(
                agent_profile=self.agent_profile,
                bet_ticket=ticket,
                referred_user=self.referred_user,
                bet_stake=Decimal('100.00'),
                commission_percentage=Decimal('0.0500'),
                commission_amount=Decimal('5.00'),
            )

        self.assertEqual(self.agent_profile.total_earnings, Decimal('15.00'))


class ReferralSettingsAgentCommissionTest(TestCase):
    """Tests for agent commission settings."""

    def test_default_agent_commission_percentage(self):
        """Test that the default agent commission percentage is 5%."""
        settings = ReferralSettings.load()
        self.assertEqual(settings.agent_commission_percentage, Decimal('0.0500'))

    def test_update_agent_commission_percentage(self):
        """Test updating the commission percentage."""
        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.1000')
        settings.save()
        settings.refresh_from_db()
        self.assertEqual(settings.agent_commission_percentage, Decimal('0.1000'))


class AwardAgentCommissionTest(TestCase):
    """Tests for the award_agent_commission utility function."""

    def setUp(self):
        self.agent_user = User.objects.create_user(username='agent2', password='pass123')
        self.referred_user = User.objects.create_user(username='bettor2', password='pass123')
        self.agent_profile = get_or_create_referral_profile(self.agent_user)
        self.referred_profile = get_or_create_referral_profile(self.referred_user)
        self.referred_profile.referred_by = self.agent_user
        self.referred_profile.save()

        # Ensure settings are loaded
        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.0500')
        settings.save()

    @patch('referrals.utils.send_bonus_notification_task')
    def test_award_commission_on_lost_bet(self, mock_notification):
        """Test that agent gets commission when referred user loses a bet."""
        ticket = BetTicket.objects.create(
            user=self.referred_user,
            total_stake=Decimal('200.00'),
            status=BetTicket.TicketStatus.LOST,
        )

        agent_balance_before = self.agent_user.wallet.balance
        award_agent_commission(ticket)

        self.agent_user.wallet.refresh_from_db()
        expected_commission = Decimal('200.00') * Decimal('0.0500')  # $10.00
        self.assertEqual(
            self.agent_user.wallet.balance,
            agent_balance_before + expected_commission,
        )

        # Check AgentEarning record was created
        earning = AgentEarning.objects.get(agent_profile=self.agent_profile, bet_ticket=ticket)
        self.assertEqual(earning.commission_amount, expected_commission)
        self.assertEqual(earning.bet_stake, Decimal('200.00'))

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_commission_for_user_without_agent(self, mock_notification):
        """Test that no commission is awarded for users without an agent."""
        no_agent_user = User.objects.create_user(username='solo_bettor', password='pass123')
        ticket = BetTicket.objects.create(
            user=no_agent_user,
            total_stake=Decimal('100.00'),
            status=BetTicket.TicketStatus.LOST,
        )

        award_agent_commission(ticket)
        self.assertEqual(AgentEarning.objects.count(), 0)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_duplicate_commission(self, mock_notification):
        """Test that commission is not awarded twice for the same ticket."""
        ticket = BetTicket.objects.create(
            user=self.referred_user,
            total_stake=Decimal('100.00'),
            status=BetTicket.TicketStatus.LOST,
        )

        award_agent_commission(ticket)
        award_agent_commission(ticket)  # Call again

        self.assertEqual(AgentEarning.objects.filter(bet_ticket=ticket).count(), 1)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_commission_when_percentage_is_zero(self, mock_notification):
        """Test that no commission is awarded when percentage is 0."""
        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.0000')
        settings.save()

        ticket = BetTicket.objects.create(
            user=self.referred_user,
            total_stake=Decimal('100.00'),
            status=BetTicket.TicketStatus.LOST,
        )

        award_agent_commission(ticket)
        self.assertEqual(AgentEarning.objects.count(), 0)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_commission_for_ticket_without_user(self, mock_notification):
        """Test that no commission is awarded for tickets without a user."""
        ticket = BetTicket.objects.create(
            user=None,
            total_stake=Decimal('100.00'),
            status=BetTicket.TicketStatus.LOST,
        )

        award_agent_commission(ticket)
        self.assertEqual(AgentEarning.objects.count(), 0)
