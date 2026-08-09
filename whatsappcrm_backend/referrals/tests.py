from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.contrib.auth.models import User

from referrals.models import ReferralProfile, ReferralSettings, AgentEarning, AgentDeduction, AgentDepositBonus
from referrals.utils import (
    get_or_create_referral_profile,
    link_referral,
    award_agent_commission,
    apply_agent_win_deduction,
    apply_referral_bonus,
)
from customer_data.models import BetTicket, UserWallet, WalletTransaction


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
            commission_percentage=Decimal('0.2500'),
            commission_amount=Decimal('25.00'),
        )
        self.assertEqual(earning.commission_amount, Decimal('25.00'))
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
                commission_percentage=Decimal('0.2500'),
                commission_amount=Decimal('25.00'),
            )

        self.assertEqual(self.agent_profile.total_earnings, Decimal('75.00'))

    def test_net_earnings_nets_off_deductions(self):
        """total_earnings includes deposit bonuses; net_earnings subtracts deductions."""
        ticket_lost = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('100.00'), status=BetTicket.TicketStatus.LOST)
        AgentEarning.objects.create(
            agent_profile=self.agent_profile, bet_ticket=ticket_lost, referred_user=self.referred_user,
            bet_stake=Decimal('100.00'), commission_percentage=Decimal('0.2500'), commission_amount=Decimal('25.00'))

        deposit_txn = WalletTransaction.objects.create(
            wallet=self.referred_user.wallet, amount=Decimal('40.00'), transaction_type='DEPOSIT',
            description='test deposit')
        AgentDepositBonus.objects.create(
            agent_profile=self.agent_profile, referred_user=self.referred_user, deposit_transaction=deposit_txn,
            deposit_amount=Decimal('40.00'), bonus_percentage=Decimal('0.2500'), bonus_amount=Decimal('10.00'))

        ticket_won = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('20.00'), status=BetTicket.TicketStatus.WON)
        AgentDeduction.objects.create(
            agent_profile=self.agent_profile, bet_ticket=ticket_won, referred_user=self.referred_user,
            win_amount=Decimal('60.00'), deduction_percentage=Decimal('0.2500'), deduction_amount=Decimal('15.00'))

        self.assertEqual(self.agent_profile.total_earnings, Decimal('35.00'))  # 25 + 10
        self.assertEqual(self.agent_profile.total_deductions, Decimal('15.00'))
        self.assertEqual(self.agent_profile.net_earnings, Decimal('20.00'))  # 35 - 15


class ReferralSettingsAgentCommissionTest(TestCase):
    """Tests for the affiliate program's default percentages."""

    def test_default_percentages_are_all_twenty_five_percent(self):
        """Deposit bonus, loss commission, and win deduction all default to 25%."""
        settings = ReferralSettings.load()
        self.assertEqual(settings.bonus_percentage_each, Decimal('0.2500'))
        self.assertEqual(settings.agent_commission_percentage, Decimal('0.2500'))
        self.assertEqual(settings.agent_win_deduction_percentage, Decimal('0.2500'))

    def test_update_agent_commission_percentage(self):
        """Test updating the commission percentage."""
        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.1000')
        settings.save()
        settings.refresh_from_db()
        self.assertEqual(settings.agent_commission_percentage, Decimal('0.1000'))


class AwardAgentCommissionTest(TestCase):
    """Tests for the award_agent_commission utility function (referred user LOSES)."""

    def setUp(self):
        self.agent_user = User.objects.create_user(username='agent2', password='pass123')
        self.referred_user = User.objects.create_user(username='bettor2', password='pass123')
        self.agent_profile = get_or_create_referral_profile(self.agent_user)
        self.agent_profile.is_agent = True
        self.agent_profile.save(update_fields=['is_agent'])
        self.referred_profile = get_or_create_referral_profile(self.referred_user)
        self.referred_profile.referred_by = self.agent_user
        self.referred_profile.save()

        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.2500')
        settings.save()

    @patch('referrals.utils.send_bonus_notification_task')
    def test_award_commission_on_lost_bet(self, mock_notification):
        """Test that agent gets commission when referred user loses a bet."""
        ticket = BetTicket.objects.create(
            user=self.referred_user,
            total_stake=Decimal('200.00'),
            status=BetTicket.TicketStatus.LOST,
        )

        agent_balance_before = Decimal(str(self.agent_user.wallet.balance))
        award_agent_commission(ticket)

        self.agent_user.wallet.refresh_from_db()
        expected_commission = Decimal('200.00') * Decimal('0.2500')  # $50.00
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
    def test_no_commission_when_referrer_is_not_a_designated_agent(self, mock_notification):
        """Referrers must be admin-designated agents (is_agent=True) to earn commission."""
        self.agent_profile.is_agent = False
        self.agent_profile.save(update_fields=['is_agent'])

        ticket = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('100.00'), status=BetTicket.TicketStatus.LOST)
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


class ApplyAgentWinDeductionTest(TestCase):
    """Tests for apply_agent_win_deduction (referred user WINS)."""

    def setUp(self):
        self.agent_user = User.objects.create_user(username='agent3', password='pass123')
        self.referred_user = User.objects.create_user(username='bettor3', password='pass123')
        self.agent_profile = get_or_create_referral_profile(self.agent_user)
        self.agent_profile.is_agent = True
        self.agent_profile.save(update_fields=['is_agent'])
        self.referred_profile = get_or_create_referral_profile(self.referred_user)
        self.referred_profile.referred_by = self.agent_user
        self.referred_profile.save()

        settings = ReferralSettings.load()
        settings.agent_win_deduction_percentage = Decimal('0.2500')
        settings.save()

    @patch('referrals.utils.send_bonus_notification_task')
    def test_deducts_from_agent_wallet_on_referred_win(self, mock_notification):
        ticket = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('10.00'), status=BetTicket.TicketStatus.WON)

        agent_balance_before = Decimal(str(self.agent_user.wallet.balance))
        apply_agent_win_deduction(ticket, winnings=Decimal('50.00'))

        self.agent_user.wallet.refresh_from_db()
        expected_deduction = Decimal('50.00') * Decimal('0.2500')  # $12.50
        self.assertEqual(self.agent_user.wallet.balance, agent_balance_before - expected_deduction)

        deduction = AgentDeduction.objects.get(agent_profile=self.agent_profile, bet_ticket=ticket)
        self.assertEqual(deduction.deduction_amount, expected_deduction)
        self.assertEqual(deduction.win_amount, Decimal('50.00'))

    @patch('referrals.utils.send_bonus_notification_task')
    def test_deduction_can_take_agent_wallet_negative(self, mock_notification):
        """The deduction is unconditional — it must never crash or be silently
        skipped just because the agent's wallet balance is too low."""
        self.assertEqual(self.agent_user.wallet.balance, Decimal('0.00'))
        ticket = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('100.00'), status=BetTicket.TicketStatus.WON)

        apply_agent_win_deduction(ticket, winnings=Decimal('500.00'))

        self.agent_user.wallet.refresh_from_db()
        self.assertEqual(self.agent_user.wallet.balance, Decimal('-125.00'))  # 500 * 0.25
        self.assertEqual(AgentDeduction.objects.filter(bet_ticket=ticket).count(), 1)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_deduction_when_referrer_is_not_a_designated_agent(self, mock_notification):
        self.agent_profile.is_agent = False
        self.agent_profile.save(update_fields=['is_agent'])

        ticket = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('10.00'), status=BetTicket.TicketStatus.WON)
        apply_agent_win_deduction(ticket, winnings=Decimal('50.00'))
        self.assertEqual(AgentDeduction.objects.count(), 0)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_deduction_for_user_without_agent(self, mock_notification):
        no_agent_user = User.objects.create_user(username='solo_winner', password='pass123')
        ticket = BetTicket.objects.create(
            user=no_agent_user, total_stake=Decimal('10.00'), status=BetTicket.TicketStatus.WON)
        apply_agent_win_deduction(ticket, winnings=Decimal('50.00'))
        self.assertEqual(AgentDeduction.objects.count(), 0)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_duplicate_deduction(self, mock_notification):
        ticket = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('10.00'), status=BetTicket.TicketStatus.WON)

        apply_agent_win_deduction(ticket, winnings=Decimal('50.00'))
        apply_agent_win_deduction(ticket, winnings=Decimal('50.00'))  # Call again

        self.assertEqual(AgentDeduction.objects.filter(bet_ticket=ticket).count(), 1)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_no_deduction_when_percentage_is_zero(self, mock_notification):
        settings = ReferralSettings.load()
        settings.agent_win_deduction_percentage = Decimal('0.0000')
        settings.save()

        ticket = BetTicket.objects.create(
            user=self.referred_user, total_stake=Decimal('10.00'), status=BetTicket.TicketStatus.WON)
        apply_agent_win_deduction(ticket, winnings=Decimal('50.00'))
        self.assertEqual(AgentDeduction.objects.count(), 0)


class ApplyReferralBonusTest(TestCase):
    """Tests for apply_referral_bonus — first-deposit bonus to both the
    referred user and (if the referrer is a designated agent) the agent."""

    def setUp(self):
        self.referrer_user = User.objects.create_user(username='referrer1', password='pass123')
        self.new_user = User.objects.create_user(username='newuser1', password='pass123')
        self.referrer_profile = get_or_create_referral_profile(self.referrer_user)
        link_referral(self.new_user, self.referrer_profile.referral_code)

        settings = ReferralSettings.load()
        settings.bonus_percentage_each = Decimal('0.2500')
        settings.save()

    def _make_deposit(self, amount):
        return WalletTransaction.objects.create(
            wallet=self.new_user.wallet, amount=amount, transaction_type='DEPOSIT',
            status='COMPLETED', description='first deposit')

    @patch('referrals.utils.send_bonus_notification_task')
    def test_referred_user_always_gets_bonus(self, mock_notification):
        deposit = self._make_deposit(Decimal('40.00'))
        result = apply_referral_bonus(self.new_user, deposit)

        self.assertTrue(result['success'])
        self.new_user.wallet.refresh_from_db()
        self.assertEqual(self.new_user.wallet.balance, Decimal('10.00'))  # 40 * 0.25

    @patch('referrals.utils.send_bonus_notification_task')
    def test_agent_also_gets_bonus_when_referrer_is_designated_agent(self, mock_notification):
        self.referrer_profile.is_agent = True
        self.referrer_profile.save(update_fields=['is_agent'])

        deposit = self._make_deposit(Decimal('40.00'))
        apply_referral_bonus(self.new_user, deposit)

        self.referrer_user.wallet.refresh_from_db()
        self.assertEqual(self.referrer_user.wallet.balance, Decimal('10.00'))  # 40 * 0.25
        bonus = AgentDepositBonus.objects.get(agent_profile=self.referrer_profile, referred_user=self.new_user)
        self.assertEqual(bonus.bonus_amount, Decimal('10.00'))
        self.assertEqual(bonus.deposit_amount, Decimal('40.00'))

    @patch('referrals.utils.send_bonus_notification_task')
    def test_agent_gets_no_bonus_when_referrer_is_not_a_designated_agent(self, mock_notification):
        # is_agent is False by default — referrer only gets code-sharing, no payout.
        deposit = self._make_deposit(Decimal('40.00'))
        apply_referral_bonus(self.new_user, deposit)

        self.referrer_user.wallet.refresh_from_db()
        self.assertEqual(self.referrer_user.wallet.balance, Decimal('0.00'))
        self.assertEqual(AgentDepositBonus.objects.count(), 0)

    @patch('referrals.utils.send_bonus_notification_task')
    def test_bonus_not_applied_twice(self, mock_notification):
        self.referrer_profile.is_agent = True
        self.referrer_profile.save(update_fields=['is_agent'])

        deposit = self._make_deposit(Decimal('40.00'))
        apply_referral_bonus(self.new_user, deposit)
        result = apply_referral_bonus(self.new_user, deposit)  # Call again

        self.assertFalse(result['success'])
        self.assertEqual(AgentDepositBonus.objects.count(), 1)


class UpdateAffiliatePercentagesCommandTest(TestCase):
    """Since this project's migrations aren't committed to git (regenerated
    fresh per deploy), a data-only fix like bumping an existing settings row
    from the old 5% default to 25% needs a management command, not a data
    migration — makemigrations never regenerates those."""

    def test_updates_settings_still_at_old_default(self):
        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.0500')
        settings.save()

        out = StringIO()
        call_command('update_affiliate_percentages', stdout=out)

        settings.refresh_from_db()
        self.assertEqual(settings.agent_commission_percentage, Decimal('0.2500'))
        self.assertIn('updated', out.getvalue())

    def test_leaves_a_customised_value_untouched(self):
        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.1000')
        settings.save()

        out = StringIO()
        call_command('update_affiliate_percentages', stdout=out)

        settings.refresh_from_db()
        self.assertEqual(settings.agent_commission_percentage, Decimal('0.1000'))

    def test_force_overrides_any_value(self):
        settings = ReferralSettings.load()
        settings.agent_commission_percentage = Decimal('0.1000')
        settings.save()

        call_command('update_affiliate_percentages', '--force')

        settings.refresh_from_db()
        self.assertEqual(settings.agent_commission_percentage, Decimal('0.2500'))
