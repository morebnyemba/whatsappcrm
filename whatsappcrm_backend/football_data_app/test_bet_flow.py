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
        bk = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        self.fx = FootballFixture.objects.create(
            league=league, home_team=home, away_team=away, api_id='v3_9001',
            match_date=timezone.now() + timedelta(hours=4),
            status=FootballFixture.FixtureStatus.SCHEDULED)
        cat = MarketCategory.objects.create(name='Match Winner')
        self.mk = Market.objects.create(fixture=self.fx, bookmaker=bk, api_market_key='h2h',
                                        category=cat, last_updated_odds_api=timezone.now())
        self.home_outcome = MarketOutcome.objects.create(market=self.mk, outcome_name='Home', odds=Decimal('2.00'))
        MarketOutcome.objects.create(market=self.mk, outcome_name='Draw', odds=Decimal('3.30'))
        MarketOutcome.objects.create(market=self.mk, outcome_name='Away', odds=Decimal('3.50'))

    def test_full_flow_places_bet(self):
        init = H.init_screen()
        self.assertEqual(init['screen'], 'BET_BROWSE')
        self.assertTrue(any(o['id'] == str(self.fx.id) for o in init['data']['fixtures']))

        s = H.handle_data_exchange('BET_BROWSE', {'fixture_id': str(self.fx.id)}, self.wa)
        self.assertEqual(s['screen'], 'BET_MARKETS')
        market_id = s['data']['markets'][0]['id']

        s = H.handle_data_exchange('BET_MARKETS', {'market_id': market_id}, self.wa)
        self.assertEqual(s['screen'], 'BET_OUTCOMES')
        outcome_id = str(self.home_outcome.id)

        s = H.handle_data_exchange('BET_OUTCOMES', {'outcome_id': outcome_id}, self.wa)
        self.assertEqual(s['screen'], 'BET_STAKE')
        self.assertEqual(s['data']['balance'], '500.00')

        s = H.handle_data_exchange('BET_STAKE', {'outcome_id': outcome_id, 'stake': '50'}, self.wa)
        self.assertEqual(s['screen'], 'BET_CONFIRM')
        self.assertIn('Potential payout: $100.00', s['data']['summary'])

        s = H.handle_data_exchange('BET_CONFIRM', {'outcome_id': outcome_id, 'stake': '50'}, self.wa)
        self.assertEqual(s['screen'], 'BET_SUCCESS')
        self.assertEqual(BetTicket.objects.filter(user=self.user).count(), 1)
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal('450.00'))

    def test_invalid_stake_stays_on_stake(self):
        s = H.handle_data_exchange('BET_STAKE', {'outcome_id': str(self.home_outcome.id), 'stake': 'abc'}, self.wa)
        self.assertEqual(s['screen'], 'BET_STAKE')
        self.assertTrue(s['data']['is_error'])

    def test_insufficient_funds_stays_on_confirm(self):
        UserWallet.objects.filter(user=self.user).update(balance=Decimal('1'))
        s = H.handle_data_exchange('BET_CONFIRM', {'outcome_id': str(self.home_outcome.id), 'stake': '50'}, self.wa)
        self.assertEqual(s['screen'], 'BET_CONFIRM')
        self.assertTrue(s['data']['is_error'])
        self.assertEqual(BetTicket.objects.filter(user=self.user).count(), 0)
