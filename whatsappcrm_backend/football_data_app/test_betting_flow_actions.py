# whatsappcrm_backend/football_data_app/test_betting_flow_actions.py
"""
Coverage for football_data_app.betting_flow_actions.handle_betting_ux_action --
the tap-driven conversational Betting Flow's action handlers (flows/betting_flow.py).
This module had zero test coverage before, despite being the shared backend for
browsing fixtures, placing bets, and viewing tickets.

Two things this session's user asked about directly:
- "why don't we have a way to view all matches" -> the fixtures browser only
  ever paged forward; there was no way back once you'd paged past a match.
- "can't the view ticket screen show odds and multipliers" -> it already
  built a "Combined odds" line, but BetTicket.total_odds was never actually
  persisted at placement time (see test_bet_flow.py's regression test), so
  every ticket showed "Combined odds: 1.00" regardless of the real odds.
"""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from conversations.models import Contact
from customer_data.models import CustomerProfile, UserWallet, BetTicket
from .models import League, Team, Bookmaker, MarketCategory, Market, MarketOutcome, FootballFixture
from .betting_flow_actions import handle_betting_ux_action
from . import betting_ux as ux


class ViewTicketOddsTests(TestCase):
    """The ticket-detail screen (view_ticket) must show the real combined
    odds and each leg's own odds, not a stale 1.00 placeholder."""

    def setUp(self):
        self.user = User.objects.create_user('ticketviewer')
        UserWallet.objects.filter(user=self.user).update(balance=Decimal('500'))
        self.contact = Contact.objects.create(whatsapp_id='263779990001')
        CustomerProfile.objects.create(contact=self.contact, user=self.user,
                                       date_of_birth=timezone.localdate().replace(year=1990))
        league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        home = Team.objects.create(name='Chelsea')
        away = Team.objects.create(name='Arsenal')
        bk = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        fixture = FootballFixture.objects.create(
            league=league, home_team=home, away_team=away, api_id='v3_5001',
            match_date=timezone.now() + timedelta(hours=4),
            status=FootballFixture.FixtureStatus.SCHEDULED)
        cat = MarketCategory.objects.create(name='Match Winner')
        market = Market.objects.create(fixture=fixture, bookmaker=bk, api_market_key='h2h',
                                       category=cat, last_updated_odds_api=timezone.now())
        self.outcome = MarketOutcome.objects.create(market=market, outcome_name='Home', odds=Decimal('2.50'))

    def test_single_ticket_shows_real_combined_and_leg_odds(self):
        slip, added, _msg = ux.slip_add([], self.outcome)
        self.assertTrue(added)
        flow_context = {'slip': slip}
        result = handle_betting_ux_action(
            contact=None, action_type='set_stake', flow_context=flow_context,
            user=self.user, selection='stake:10')
        self.assertEqual(result['data']['route'], 'confirm')

        result = handle_betting_ux_action(
            contact=self.contact, action_type='place_slip', flow_context=flow_context, user=self.user)
        self.assertEqual(result['data']['route'], 'placed')
        ticket_id = result['data']['ticket_id']

        # total_odds must be the real multiplier, not the model default.
        ticket = BetTicket.objects.get(id=ticket_id)
        self.assertEqual(Decimal(str(ticket.total_odds)), Decimal('2.500'))

        result = handle_betting_ux_action(
            contact=None, action_type='view_ticket', flow_context={}, user=self.user,
            selection=f"mybet:{ticket_id}")
        message = result['data']['ticket_detail_message']
        self.assertIn('Combined odds: 2.50', message)
        self.assertIn('Home @ 2.50', message)

    def test_accumulator_ticket_shows_multiplied_combined_odds(self):
        home2 = Team.objects.create(name='Spurs')
        away2 = Team.objects.create(name='Everton')
        league2 = League.objects.create(name='La Liga', api_id='v3_140', sport_key='soccer')
        bk2 = Bookmaker.objects.create(name='williamhill', api_bookmaker_key='11')
        fixture2 = FootballFixture.objects.create(
            league=league2, home_team=home2, away_team=away2, api_id='v3_5002',
            match_date=timezone.now() + timedelta(hours=6),
            status=FootballFixture.FixtureStatus.SCHEDULED)
        cat = MarketCategory.objects.get(name='Match Winner')
        market2 = Market.objects.create(fixture=fixture2, bookmaker=bk2, api_market_key='h2h',
                                        category=cat, last_updated_odds_api=timezone.now())
        outcome2 = MarketOutcome.objects.create(market=market2, outcome_name='Home', odds=Decimal('1.80'))

        slip, _, _ = ux.slip_add([], self.outcome)
        slip, _, _ = ux.slip_add(slip, outcome2)
        flow_context = {'slip': slip}
        handle_betting_ux_action(contact=None, action_type='set_stake', flow_context=flow_context,
                                 user=self.user, selection='stake:10')
        result = handle_betting_ux_action(contact=self.contact, action_type='place_slip',
                                          flow_context=flow_context, user=self.user)
        ticket_id = result['data']['ticket_id']

        ticket = BetTicket.objects.get(id=ticket_id)
        # 2.50 * 1.80 = 4.50
        self.assertEqual(Decimal(str(ticket.total_odds)), Decimal('4.500'))

        result = handle_betting_ux_action(
            contact=None, action_type='view_ticket', flow_context={}, user=self.user,
            selection=f"mybet:{ticket_id}")
        self.assertIn('Combined odds: 4.50', result['data']['ticket_detail_message'])


class FixturesBrowserPaginationTests(TestCase):
    """The fixtures browser paged forward only -- once you tapped "More
    matches" there was no way back to a match you'd already scrolled past.
    This is the concrete answer to "don't we have a way to view all matches":
    yes, via paging (WhatsApp interactive lists hard-cap at 10 rows total per
    message, so a single "show everything" screen isn't possible), but paging
    needs to work both directions to actually let you see all of them."""

    def setUp(self):
        league = League.objects.create(name='EPL', api_id='v3_39', sport_key='soccer')
        bk = Bookmaker.objects.create(name='bet365', api_bookmaker_key='8')
        cat = MarketCategory.objects.create(name='Match Winner')
        # 10 fixtures spans three pages at FIXTURES_PER_PAGE=8: page 0 (8),
        # page 1 (2, plus a "no more" state) -- comfortably exercises both
        # the forward-only first page and a true middle page.
        for i in range(10):
            home = Team.objects.create(name=f'Home{i}')
            away = Team.objects.create(name=f'Away{i}')
            fixture = FootballFixture.objects.create(
                league=league, home_team=home, away_team=away, api_id=f'v3_page_{i}',
                match_date=timezone.now() + timedelta(hours=1 + i),
                status=FootballFixture.FixtureStatus.SCHEDULED)
            market = Market.objects.create(fixture=fixture, bookmaker=bk, api_market_key='h2h',
                                           category=cat, last_updated_odds_api=timezone.now())
            MarketOutcome.objects.create(market=market, outcome_name='Home', odds=Decimal('2.00'))

    def _all_rows(self, screen):
        return [row for section in screen['sections'] for row in section['rows']]

    def test_first_page_has_no_previous_row_but_has_more_row(self):
        screen = ux.build_fixtures_screen(page=0)
        row_ids = {r['id'] for r in self._all_rows(screen)}
        nav_ids = {rid for rid in row_ids if rid.startswith('fxpage:')}
        self.assertEqual(nav_ids, {'fxpage:1'})  # only "More matches", no "Previous"
        self.assertTrue(screen['has_more'])
        # Never exceeds WhatsApp's hard 10-row-per-list cap.
        self.assertLessEqual(len(self._all_rows(screen)), 10)

    def test_second_page_can_navigate_back_to_first_page(self):
        screen = ux.build_fixtures_screen(page=1)
        row_ids = {r['id'] for r in self._all_rows(screen)}
        self.assertIn('fxpage:0', row_ids)  # "Previous matches" -> back to page 0
        self.assertLessEqual(len(self._all_rows(screen)), 10)

    def test_row_count_never_exceeds_whatsapp_cap_even_with_both_nav_rows(self):
        # Force a scenario with 20 fixtures so an interior page has both a
        # previous and a more row simultaneously -- the tightest case.
        league = League.objects.create(name='La Liga', api_id='v3_140', sport_key='soccer')
        bk = Bookmaker.objects.create(name='williamhill', api_bookmaker_key='11')
        cat = MarketCategory.objects.get(name='Match Winner')
        for i in range(20):
            home = Team.objects.create(name=f'ExtraHome{i}')
            away = Team.objects.create(name=f'ExtraAway{i}')
            fixture = FootballFixture.objects.create(
                league=league, home_team=home, away_team=away, api_id=f'v3_extra_{i}',
                match_date=timezone.now() + timedelta(hours=1 + i),
                status=FootballFixture.FixtureStatus.SCHEDULED)
            market = Market.objects.create(fixture=fixture, bookmaker=bk, api_market_key='h2h',
                                           category=cat, last_updated_odds_api=timezone.now())
            MarketOutcome.objects.create(market=market, outcome_name='Home', odds=Decimal('2.00'))

        screen = ux.build_fixtures_screen(page=1)
        row_ids = {r['id'] for r in self._all_rows(screen)}
        self.assertIn('fxpage:0', row_ids)
        self.assertIn('fxpage:2', row_ids)
        self.assertLessEqual(len(self._all_rows(screen)), 10)
