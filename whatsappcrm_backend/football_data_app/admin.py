# whatsappcrm_backend/football_data_app/admin.py
from django.contrib import admin, messages
from .models import FootballFixture, FootballTaskRunState # Import both models
from .tasks import update_football_fixtures_data

# Action function to trigger the Celery task manually
def trigger_fixture_synchronization_action(modeladmin, request, queryset):
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
trigger_fixture_synchronization_action.short_description = "Manually Sync Football Fixtures (Cycles One League)"


@admin.register(FootballFixture)
class FootballFixtureAdmin(admin.ModelAdmin):
    list_display = ('match_datetime_utc', 'competition_name', 'home_team_name', 'away_team_name', 'status', 'home_score', 'away_score', 'last_api_update')
    list_filter = ('status', 'competition_name', 'match_datetime_utc')
    search_fields = ('home_team_name', 'away_team_name', 'competition_name')
    ordering = ('-match_datetime_utc',)
    actions = [trigger_fixture_synchronization_action] # You can keep this if useful for manual trigger


@admin.register(FootballTaskRunState)
class FootballTaskRunStateAdmin(admin.ModelAdmin):
    list_display = ('task_marker', 'last_processed_league_index', 'last_run_at')
    readonly_fields = ('last_run_at',)
    # Prevent adding new states from admin if only one fixed state marker is used.
    # def has_add_permission(self, request):
    #     return False