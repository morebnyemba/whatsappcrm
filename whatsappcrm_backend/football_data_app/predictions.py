# whatsappcrm_backend/football_data_app/predictions.py
"""
Baseline statistical predictions for football fixtures.

A lightweight Poisson goal model estimated from historical results already
ingested via the football data API. For each team we estimate an attacking and
defensive strength relative to the league average (separately for home and
away), then model each side's goals as independent Poisson variables and sum the
score matrix into win/draw/loss probabilities.

This is deliberately simple and dependency-free (no numpy/scipy): it degrades
gracefully when a team has little history, falling back to league averages and,
in the worst case, a neutral home-advantage prior. It is advisory only — it
never feeds bet placement or overrides bookmaker odds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from .models import FootballFixture

# How far back to look for form, and modelling constants.
HISTORY_DAYS = 365
MIN_MATCHES_FOR_TEAM = 3          # below this we lean on league averages
DEFAULT_HOME_GOALS = 1.45         # league priors used when no data at all
DEFAULT_AWAY_GOALS = 1.15
MAX_GOALS = 8                     # score-matrix truncation


@dataclass
class Prediction:
    prob_home: float
    prob_draw: float
    prob_away: float
    expected_home_goals: float
    expected_away_goals: float
    data_points: int
    method: str = 'poisson'


def _finished_qs(since):
    return FootballFixture.objects.filter(
        status=FootballFixture.FixtureStatus.FINISHED,
        match_date__gte=since,
        home_team_score__isnull=False,
        away_team_score__isnull=False,
    )


def _league_averages(league_id, since):
    """Average home and away goals per game across the league's finished matches."""
    qs = _finished_qs(since).filter(league_id=league_id)
    n = qs.count()
    if n == 0:
        return DEFAULT_HOME_GOALS, DEFAULT_AWAY_GOALS, 0
    total_home = sum(f.home_team_score for f in qs)
    total_away = sum(f.away_team_score for f in qs)
    return total_home / n, total_away / n, n


def _team_rates(team_id, since):
    """Return (scored_home, conceded_home, n_home, scored_away, conceded_away, n_away)."""
    home = _finished_qs(since).filter(home_team_id=team_id)
    away = _finished_qs(since).filter(away_team_id=team_id)
    h = list(home.values_list('home_team_score', 'away_team_score'))
    a = list(away.values_list('home_team_score', 'away_team_score'))
    sh = sum(x[0] for x in h); ch = sum(x[1] for x in h)
    sa = sum(x[1] for x in a); ca = sum(x[0] for x in a)
    return sh, ch, len(h), sa, ca, len(a)


def _poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _score_matrix_probs(lam_home, lam_away):
    """Sum the independent-Poisson score matrix into (home, draw, away) probs."""
    p_home = p_draw = p_away = 0.0
    home_pmf = [_poisson_pmf(i, lam_home) for i in range(MAX_GOALS + 1)]
    away_pmf = [_poisson_pmf(j, lam_away) for j in range(MAX_GOALS + 1)]
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = home_pmf[i] * away_pmf[j]
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return p_home / total, p_draw / total, p_away / total


def compute_prediction(fixture: FootballFixture) -> Optional[Prediction]:
    """Compute a Poisson-based prediction for a fixture, or None if unusable."""
    if not fixture.home_team_id or not fixture.away_team_id:
        return None

    since = timezone.now() - timezone.timedelta(days=HISTORY_DAYS)
    avg_home, avg_away, league_n = _league_averages(fixture.league_id, since)

    sh, ch, nh, sa, ca, na = _team_rates(fixture.home_team_id, since)
    osh, och, onh, osa, oca, ona = _team_rates(fixture.away_team_id, since)

    # Attack/defense strengths relative to the league average (1.0 = average).
    # Fall back to 1.0 (league-average) when a team lacks enough matches.
    def strength(scored, matches, base):
        if matches < MIN_MATCHES_FOR_TEAM or base <= 0:
            return 1.0
        return (scored / matches) / base

    home_attack = strength(sh, nh, avg_home)
    home_defense = strength(ch, nh, avg_away)
    away_attack = strength(osa, ona, avg_away)
    away_defense = strength(oca, ona, avg_home)

    lam_home = max(0.05, avg_home * home_attack * away_defense)
    lam_away = max(0.05, avg_away * away_attack * home_defense)

    p_home, p_draw, p_away = _score_matrix_probs(lam_home, lam_away)
    data_points = nh + na + onh + ona

    return Prediction(
        prob_home=round(p_home, 4),
        prob_draw=round(p_draw, 4),
        prob_away=round(p_away, 4),
        expected_home_goals=round(lam_home, 2),
        expected_away_goals=round(lam_away, 2),
        data_points=data_points,
    )


def save_prediction(fixture: FootballFixture) -> Optional["FixturePrediction"]:
    """Compute and persist a prediction for a fixture. Returns the saved row."""
    from .models import FixturePrediction
    pred = compute_prediction(fixture)
    if pred is None:
        return None
    obj, _ = FixturePrediction.objects.update_or_create(
        fixture=fixture,
        defaults=dict(
            prob_home=pred.prob_home, prob_draw=pred.prob_draw, prob_away=pred.prob_away,
            expected_home_goals=pred.expected_home_goals, expected_away_goals=pred.expected_away_goals,
            method=pred.method, data_points=pred.data_points,
        ),
    )
    return obj
