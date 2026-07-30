# whatsappcrm_backend/football_data_app/prediction_tasks.py
"""
Celery tasks that (re)compute baseline fixture predictions.

Modelled on the periodic/triggered task style used elsewhere in this codebase.
Schedule generate_fixture_predictions_task periodically (e.g. hourly) via
django-celery-beat so upcoming fixtures always carry a fresh prediction.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import FootballFixture
from .predictions import save_prediction

logger = logging.getLogger(__name__)


@shared_task(name="football_data_app.generate_fixture_predictions", queue='cpu_heavy')
def generate_fixture_predictions_task(days_ahead: int = 10):
    """Compute predictions for upcoming scheduled fixtures within the window."""
    now = timezone.now()
    fixtures = FootballFixture.objects.filter(
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__gte=now,
        match_date__lte=now + timedelta(days=days_ahead),
    ).select_related('league', 'home_team', 'away_team')

    total = created = 0
    for fixture in fixtures:
        total += 1
        try:
            if save_prediction(fixture) is not None:
                created += 1
        except Exception as e:
            logger.error(f"Failed to compute prediction for fixture {fixture.id}: {e}", exc_info=True)

    logger.info(f"generate_fixture_predictions_task: computed {created}/{total} predictions.")
    return {"fixtures": total, "predictions": created}


@shared_task(name="football_data_app.generate_prediction_for_fixture")
def generate_prediction_for_fixture_task(fixture_id: int):
    """Compute (or refresh) the prediction for a single fixture."""
    try:
        fixture = FootballFixture.objects.select_related('league', 'home_team', 'away_team').get(pk=fixture_id)
    except FootballFixture.DoesNotExist:
        logger.warning(f"generate_prediction_for_fixture_task: fixture {fixture_id} not found.")
        return None
    obj = save_prediction(fixture)
    return {"fixture_id": fixture_id, "saved": obj is not None}
