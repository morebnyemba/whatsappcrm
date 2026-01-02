# Quick Reference: Tasks and First-Time Setup

## The Answer to Your Questions

### Q: "Where are the tasks?"
**A:** Tasks are defined in:
- `whatsappcrm_backend/football_data_app/tasks_apifootball.py` (legacy)
- `whatsappcrm_backend/football_data_app/tasks_api_football_v3.py` (recommended)

After this PR is merged and services are restarted, they will appear in Django admin under:
**DJANGO CELERY BEAT → Periodic Tasks → Add Periodic Task → Task (registered)** dropdown

### Q: "How do I schedule the tasks?"
**A:** Via Django Admin:
1. Go to http://your-domain/admin/
2. Navigate to **DJANGO CELERY BEAT → Periodic Tasks**
3. Click **Add Periodic Task**
4. Select task from dropdown, set interval, save

### Q: "What's the first time command?"
**A:** Before scheduling tasks, you MUST run:

```bash
# For legacy APIFootball.com (without dash)
docker-compose exec backend python manage.py football_league_setup

# OR for API-Football v3 (with dash) - RECOMMENDED
docker-compose exec backend python manage.py football_league_setup_v3
```

This initializes the leagues in your database. Without this, tasks will report "0 active leagues".

## Task Names for Scheduling

### Legacy APIFootball.com Tasks:
- Main update: `football_data_app.run_apifootball_full_update`
- Score & settlement: `football_data_app.run_score_and_settlement_task`

### API-Football v3 Tasks (Recommended):
- Main update: `football_data_app.run_api_football_v3_full_update`
- Score & settlement: `football_data_app.run_score_and_settlement_v3_task`

## League Season Field

**Yes, it IS editable!** 
- Go to Django Admin → Football Data & Betting → Leagues
- Click any league
- Edit the `league_season` field (e.g., "2024" or "2023/2024")
- The confusion was likely from seeing `last_fetched_events` which is now clearly marked as readonly

## Complete Documentation

For detailed information, see:
- [TASK_REGISTRATION_ADMIN_FIX.md](TASK_REGISTRATION_ADMIN_FIX.md) - What was fixed and how
- [FOOTBALL_TASKS_SETUP_GUIDE.md](FOOTBALL_TASKS_SETUP_GUIDE.md) - Complete setup guide
- [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md) - New API-Football v3 guide

## After Merging This PR

1. Restart services: `docker-compose restart backend celery_beat celery_cpu_worker`
2. Run first-time setup command (if not done before)
3. Go to Django admin and schedule tasks
4. Verify tasks are running: `docker-compose logs -f celery_cpu_worker`

That's it! 🎉
