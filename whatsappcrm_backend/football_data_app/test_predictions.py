# whatsappcrm_backend/football_data_app/test_predictions.py
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import League, Team, FootballFixture
from . import predictions as P
from . import ai_gateway as AI


class PredictionModelTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name='Test League', api_id='test_lg', sport_key='soccer')
        self.strong = Team.objects.create(name='Strong FC')
        self.weak = Team.objects.create(name='Weak FC')
        self.other = Team.objects.create(name='Other FC')
        now = timezone.now()

        def finished(home, away, hs, aws, days_ago):
            FootballFixture.objects.create(
                league=self.league, home_team=home, away_team=away,
                api_id=f'h_{home.id}_{away.id}_{days_ago}',
                match_date=now - timedelta(days=days_ago),
                status=FootballFixture.FixtureStatus.FINISHED,
                home_team_score=hs, away_team_score=aws,
            )
        # Strong team wins big and often; weak team loses.
        finished(self.strong, self.other, 4, 0, 30)
        finished(self.strong, self.weak, 3, 0, 25)
        finished(self.other, self.strong, 0, 3, 20)
        finished(self.weak, self.other, 0, 2, 15)
        finished(self.other, self.weak, 3, 0, 10)

        self.fixture = FootballFixture.objects.create(
            league=self.league, home_team=self.strong, away_team=self.weak,
            api_id='upcoming', match_date=now + timedelta(days=2),
            status=FootballFixture.FixtureStatus.SCHEDULED,
        )

    def test_probabilities_are_valid_distribution(self):
        pred = P.compute_prediction(self.fixture)
        self.assertIsNotNone(pred)
        total = pred.prob_home + pred.prob_draw + pred.prob_away
        self.assertAlmostEqual(total, 1.0, places=3)
        for p in (pred.prob_home, pred.prob_draw, pred.prob_away):
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_strong_team_is_favored(self):
        pred = P.compute_prediction(self.fixture)
        self.assertGreater(pred.prob_home, pred.prob_away)

    def test_save_and_sentence(self):
        obj = P.save_prediction(self.fixture)
        self.assertIsNotNone(obj)
        self.assertEqual(obj.favored_side, 'home')
        self.fixture.refresh_from_db()
        sentence = P.prediction_sentence(self.fixture)
        self.assertIn('Strong FC', sentence)

    def test_no_history_returns_prediction_with_priors(self):
        # A fixture between brand-new teams still yields a valid (prior-based) prediction.
        a = Team.objects.create(name='New A')
        b = Team.objects.create(name='New B')
        fx = FootballFixture.objects.create(
            league=self.league, home_team=a, away_team=b, api_id='fresh',
            match_date=timezone.now() + timedelta(days=1),
            status=FootballFixture.FixtureStatus.SCHEDULED,
        )
        pred = P.compute_prediction(fx)
        self.assertIsNotNone(pred)
        self.assertAlmostEqual(pred.prob_home + pred.prob_draw + pred.prob_away, 1.0, places=3)


class AiGatewayIntentTests(TestCase):
    def test_intent_classification(self):
        self.assertEqual(AI.classify_intent("what's my balance?"), AI.INTENT_BALANCE)
        self.assertEqual(AI.classify_intent("how's my last ticket doing"), AI.INTENT_LAST_TICKET)
        self.assertEqual(AI.classify_intent("any tips tonight"), AI.INTENT_TIP)
        self.assertEqual(AI.classify_intent("blah blah"), AI.INTENT_HELP)

    def test_gateway_disabled_without_key(self):
        with self.settings(GEMINI_API_KEY=''):
            self.assertFalse(AI.GeminiGateway().enabled)
