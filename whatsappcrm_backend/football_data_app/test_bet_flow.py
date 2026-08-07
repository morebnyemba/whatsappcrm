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
        H._save_server_slip(self.wa, [])  # each test starts with a clean server-side slip

    def tearDown(self):
        H._save_server_slip(self.wa, [])

    # ---- menu is the entry point ----
    def test_init_shows_menu(self):
        init = H.init_screen(self.wa)
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
        # BET_SLIP -> BET_MENU would be an illegal routing-model cycle (MENU
        # already has a forward path into SLIP via BROWSE/MARKETS/OUTCOMES),
        # so "clear" must target a terminal screen (BET_DONE) instead.
        s = H.handle_data_exchange('BET_SLIP',
                                   {'slip_action': 'clear', 'slip': str(self.home_outcome.id)}, self.wa)
        self.assertEqual(s['screen'], 'BET_DONE')
        self.assertEqual(H._load_server_slip(self.wa), [])

    def test_no_slip_action_navigates_backward(self):
        # "Add another selection" was removed: Meta's routing model can't
        # legally route BET_SLIP back into the browse chain (BET_BROWSE
        # already has a forward path into BET_SLIP). Guards against it
        # resurfacing as a data_exchange-driven jump.
        action_ids = {a['id'] for a in H.SLIP_ACTIONS}
        self.assertEqual(action_ids, {'place', 'clear'})

    # ---- error recovery never jumps to an earlier screen ----
    # Meta's Flow client rejects any data_exchange response whose `screen`
    # isn't a declared forward target of the CURRENT screen ("could not
    # switch to the requested section"). These guard every error path stays
    # on the screen the client is actually displaying.

    def test_invalid_market_id_stays_on_markets_screen(self):
        s = H.handle_data_exchange('BET_MARKETS', {'market_id': '999999', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_MARKETS')
        self.assertTrue(s['data']['is_error'])

    def test_invalid_outcome_id_stays_on_outcomes_screen(self):
        s = H.handle_data_exchange(
            'BET_OUTCOMES', {'outcome_id': '999999', 'mode': 'bet_now', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_OUTCOMES')
        self.assertTrue(s['data']['is_error'])

    def test_invalid_outcome_id_on_confirm_stays_on_stake_screen(self):
        s = H.handle_data_exchange(
            'BET_STAKE', {'outcome_id': '999999', 'stake': '10', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_STAKE')
        self.assertTrue(s['data']['is_error'])

    def test_no_handler_response_ever_targets_bet_browse_from_deeper_screens(self):
        # Systematic guard: none of the illegal-jump-prone paths should ever
        # resolve back to BET_BROWSE once the user is past it.
        cases = [
            ('BET_MARKETS', {'market_id': '999999', 'slip': ''}),
            ('BET_OUTCOMES', {'outcome_id': '999999', 'mode': 'bet_now', 'slip': ''}),
            ('BET_STAKE', {'outcome_id': '999999', 'stake': '10', 'slip': ''}),
        ]
        for current_screen, payload in cases:
            s = H.handle_data_exchange(current_screen, payload, self.wa)
            self.assertNotEqual(s['screen'], 'BET_BROWSE',
                                f"{current_screen} error path illegally jumped to BET_BROWSE")

    # ---- server-side slip persistence survives a stale cached screen ----

    def test_slip_survives_resubmission_from_stale_screen(self):
        # Leg 1: add the first outcome (server now authoritative for slip=[A]).
        s = H.handle_data_exchange(
            'BET_OUTCOMES', {'outcome_id': str(self.home_outcome.id), 'mode': 'add_slip', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_SLIP')
        self.assertEqual(H._load_server_slip(self.wa), [self.home_outcome.id])

        # Leg 2: simulate the user tapping the Flow's native back button to a
        # STALE cached BET_OUTCOMES screen (echoing an EMPTY slip — as it was
        # before leg 1 was added) and adding a second leg from there.
        s = H.handle_data_exchange(
            'BET_OUTCOMES', {'outcome_id': str(self.home_outcome2.id), 'mode': 'add_slip', 'slip': ''}, self.wa)
        self.assertEqual(s['screen'], 'BET_SLIP')

        # Both legs must be present — the stale client echo must not have
        # dropped leg 1.
        server_ids = set(H._load_server_slip(self.wa))
        self.assertEqual(server_ids, {self.home_outcome.id, self.home_outcome2.id})
        self.assertIn(str(self.home_outcome.id), s['data']['slip'].split(','))
        self.assertIn(str(self.home_outcome2.id), s['data']['slip'].split(','))

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
