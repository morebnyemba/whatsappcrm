# whatsappcrm_backend/football_data_app/test_bet_flow.py
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from conversations.models import Contact
from customer_data.models import CustomerProfile, UserWallet, BetTicket
from .models import (League, Team, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome)
from . import bet_flow_handler as H


class BetFlowHandlerTests(TestCase):
    def setUp(self):
        self.wa = '263771234567'
        self.user = User.objects.create_user('flowbettor')
        UserWallet.objects.filter(user=self.user).update(balance=Decimal('500'))
        self.contact = Contact.objects.create(whatsapp_id=self.wa)
        CustomerProfile.objects.create(contact=self.contact, user=self.user,
                                       date_of_birth=timezone.localdate().replace(year=1990))
        league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        home = Team.objects.create(name='Chelsea'); away = Team.objects.create(name='Arsenal')
        home2 = Team.objects.create(name='Spurs'); away2 = Team.objects.create(name='Everton')
        bk = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.fx = FootballFixture.objects.create(
            league=league, home_team=home, away_team=away, api_id='v3_9001',
            match_date=timezone.now() + timedelta(hours=4),
            status=FootballFixture.FixtureStatus.SCHEDULED)
        self.fx2 = FootballFixture.objects.create(
            league=league, home_team=home2, away_team=away2, api_id='v3_9002',
            match_date=timezone.now() + timedelta(hours=6),
            status=FootballFixture.FixtureStatus.SCHEDULED)
        cat = MarketCategory.objects.create(name='Match Winner')
        self.mk = Market.objects.create(fixture=self.fx, bookmaker=bk, api_market_key='h2h',
                                        category=cat, last_updated_odds_api=timezone.now())
        self.home_outcome = MarketOutcome.objects.create(market=self.mk, outcome_name='Home', odds=Decimal('2.00'))
        MarketOutcome.objects.create(market=self.mk, outcome_name='Draw', odds=Decimal('3.30'))
        MarketOutcome.objects.create(market=self.mk, outcome_name='Away', odds=Decimal('3.50'))
        self.mk2 = Market.objects.create(fixture=self.fx2, bookmaker=bk, api_market_key='h2h',
                                         category=cat, last_updated_odds_api=timezone.now())
        self.home_outcome2 = MarketOutcome.objects.create(market=self.mk2, outcome_name='Home', odds=Decimal('1.50'))

    # ---- menu is the entry point ----
    def test_init_shows_menu(self):
        init = H.init_screen()
        self.assertEqual(init['screen'], 'BET_MENU')
        ids = {o['id'] for o in init['data']['menu']}
        self.assertEqual(ids, {'browse', 'slip', 'mybets', 'balance', 'safer'})

    def test_menu_balance(self):
        s = H.handle_data_exchange('BET_MENU', {'action': 'balance', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_DONE')
        self.assertIn('500.00', s['data']['message'])

    # ---- single bet path ----
    def test_full_single_bet(self):
        s = H.handle_data_exchange('BET_MENU', {'action': 'browse', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_BROWSE')
        self.assertTrue(any(o['id'] == str(self.fx.id) for o in s['data']['fixtures']))

        s = H.handle_data_exchange('BET_BROWSE', {'fixture_id': str(self.fx.id), 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_MARKETS')
        market_id = s['data']['markets'][0]['id']

        s = H.handle_data_exchange('BET_MARKETS', {'market_id': market_id, 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_OUTCOMES')
        outcome_id = str(self.home_outcome.id)

        s = H.handle_data_exchange('BET_OUTCOMES', {'outcome_id': outcome_id, 'mode': 'bet_now', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_STAKE')
        self.assertEqual(s['data']['balance'], '500.00')

        s = H.handle_data_exchange('BET_STAKE', {'outcome_id': outcome_id, 'stake': '50', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_CONFIRM')
        self.assertIn('Potential payout: $100.00', s['data']['summary'])

        s = H.handle_data_exchange('BET_CONFIRM', {'outcome_id': outcome_id, 'stake': '50', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_SUCCESS')
        self.assertEqual(BetTicket.objects.filter(user=self.user).count(), 1)
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal('450.00'))

    # ---- accumulator / bet slip path ----
    def test_accumulator_via_slip(self):
        # add first leg to slip
        s = H.handle_data_exchange('BET_OUTCOMES',
                                   {'outcome_id': str(self.home_outcome.id), 'mode': 'add_slip', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_SLIP')
        slip = s['data']['slip']
        self.assertEqual(slip, str(self.home_outcome.id))

        # add a second leg
        s = H.handle_data_exchange('BET_OUTCOMES',
                                   {'outcome_id': str(self.home_outcome2.id), 'mode': 'add_slip', 'slip': slip}, self.wa)
        self.assertEqual(s['screen'], 'BET_SLIP')
        slip = s['data']['slip']
        self.assertTrue(s['data']['has_slip'])
        self.assertIn('Accumulator', s['data']['summary'])

        # place the accumulator
        s = H.handle_data_exchange('BET_SLIP', {'slip_action': 'place', 'stake': '10', 'slip': slip}, self.wa)
        self.assertEqual(s['screen'], 'BET_SUCCESS')
        ticket = BetTicket.objects.filter(user=self.user).first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.bets.count(), 2)
        # combined odds 2.00 * 1.50 = 3.00, stake 10 → potential winnings 30.00
        self.assertEqual(Decimal(str(ticket.potential_winnings)), Decimal('30.00'))

    def test_slip_clear(self):
        s = H.handle_data_exchange('BET_SLIP',
                                   {'slip_action': 'clear', 'slip': str(self.home_outcome.id)}, self.wa)
        self.assertEqual(s['screen'], 'BET_MENU')
        self.assertEqual(s['data']['slip'], '')

    def test_slip_add_more_returns_browse(self):
        s = H.handle_data_exchange('BET_SLIP',
                                   {'slip_action': 'add_more', 'slip': str(self.home_outcome.id)}, self.wa)
        self.assertEqual(s['screen'], 'BET_BROWSE')
        self.assertEqual(s['data']['slip'], str(self.home_outcome.id))

    # ---- my bets ----
    def test_mybets_empty_then_detail(self):
        s = H.handle_data_exchange('BET_MENU', {'action': 'mybets', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_DONE')  # no bets yet

        # place one, then it shows up
        H.handle_data_exchange('BET_CONFIRM', {'outcome_id': str(self.home_outcome.id), 'stake': '50', 'slip': ''}, self.wa)
        s = H.handle_data_exchange('BET_MENU', {'action': 'mybets', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_MYBETS')
        tid = s['data']['tickets'][0]['id']
        s = H.handle_data_exchange('BET_MYBETS', {'ticket_id': tid, 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_DONE')
        self.assertIn('Ticket #', s['data']['message'])

    # ---- safer gambling ----
    def test_safer_self_exclude(self):
        s = H.handle_data_exchange('BET_MENU', {'action': 'safer', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_SAFER')
        s = H.handle_data_exchange('BET_SAFER', {'safer_action': 'exclude_7'}, self.wa)
        self.assertEqual(s['screen'], 'BET_DONE')
        from customer_data.compliance import get_controls
        self.assertTrue(get_controls(self.user).is_self_excluded())

    def test_safer_stake_limit(self):
        s = H.handle_data_exchange('BET_SAFER', {'safer_action': 'stake_limit', 'amount': '100'}, self.wa)
        self.assertEqual(s['screen'], 'BET_DONE')
        from customer_data.compliance import get_controls
        self.assertEqual(get_controls(self.user).daily_stake_limit, Decimal('100'))

    # ---- validation ----
    def test_invalid_stake_stays_on_stake(self):
        s = H.handle_data_exchange('BET_STAKE', {'outcome_id': str(self.home_outcome.id), 'stake': 'abc', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_STAKE')
        self.assertTrue(s['data']['is_error'])

    def test_insufficient_funds_stays_on_confirm(self):
        UserWallet.objects.filter(user=self.user).update(balance=Decimal('1'))
        s = H.handle_data_exchange('BET_CONFIRM', {'outcome_id': str(self.home_outcome.id), 'stake': '50', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_CONFIRM')
        self.assertTrue(s['data']['is_error'])
        self.assertEqual(BetTicket.objects.filter(user=self.user).count(), 0)
