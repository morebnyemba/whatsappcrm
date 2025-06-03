# football_data_app/admin.py
from django.contrib import admin, messages
from .models import FootballFixture

# Import your Celery task
# Make sure the task name matches what's defined in football_data_app/tasks.py
from .tasks import update_football_fixtures_data

# This is the action function
def trigger_fixture_synchronization_action(modeladmin, request, queryset):
    """
    Django admin action to manually trigger the Celery task for updating football fixtures.
    """
    try:
        update_football_fixtures_data.delay()
        modeladmin.message_user(request, 
                                "Successfully queued the football fixture update task. "
                                "Check Celery worker logs for progress.", 
                                messages.SUCCESS)
    except Exception as e:
        modeladmin.message_user(request, 
                                f"Failed to queue the football fixture update task: {e}", 
                                messages.ERROR)

# Set a user-friendly description for the action
trigger_fixture_synchronization_action.short_description = "Manually Sync Football Fixtures & Results"


@admin.register(FootballFixture)
class FootballFixtureAdmin(admin.ModelAdmin):
    list_display = ('match_datetime_utc', 'competition_name', 'home_team_name', 'away_team_name', 'status', 'home_score', 'away_score', 'last_api_update')
    list_filter = ('status', 'competition_name', 'match_datetime_utc')
    search_fields = ('home_team_name', 'away_team_name', 'competition_name')
    ordering = ('-match_datetime_utc',)
    
    # Add the custom action to the list of actions
    actions = [trigger_fixture_synchronization_action]