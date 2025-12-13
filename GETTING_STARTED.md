# 🚀 Getting Started with the Fixed Celery Setup

This guide will help you quickly deploy the fixed Celery worker configuration.

## ⚡ Quick Start

### Step 1: Review the Changes
Read the [FIX_SUMMARY.md](FIX_SUMMARY.md) to understand what was fixed.

### Step 2: Deploy
```bash
# Stop existing services
docker-compose down

# Rebuild and start with new configuration
docker-compose up -d --build

# Wait for services to start (about 30 seconds)
sleep 30
```

### Step 3: Verify
```bash
# Run the verification script
./verify_celery_workers.sh
```

### Step 4: Set Up Scheduled Tasks
**Important**: You need to configure periodic tasks in Django Admin.

See [SCHEDULED_TASKS_SETUP.md](SCHEDULED_TASKS_SETUP.md) for detailed instructions.

Quick setup:
1. Go to `http://your-domain/admin/`
2. Navigate to **Periodic Tasks** under DJANGO CELERY BEAT
3. Create schedules for:
   - `football_data_app.run_apifootball_full_update` (every 10 minutes)
   - `football_data_app.run_score_and_settlement_task` (every 5 minutes)

### Step 5: Initialize Football Leagues
**Critical**: Before scheduled tasks can fetch betting data, you need to initialize leagues.

```bash
# Initialize football leagues from APIFootball.com
docker-compose exec backend python manage.py football_league_setup
```

This command:
- Fetches available football leagues from APIFootball API
- Populates the database with league data
- Marks leagues as active by default

**Without this step**, you'll see "Found 0 active leagues" in logs and no betting data will be available.

**Verification**:
```bash
# Check that leagues were initialized
docker-compose exec backend python manage.py shell -c "from football_data_app.models import League; print(f'Active leagues: {League.objects.filter(active=True).count()}')"

# Monitor logs - should now show leagues being processed
docker-compose logs -f celery_cpu_worker | grep -i league
```

If all checks pass, you're ready to go! 🎉

## 📚 Documentation Index

| Document | Purpose | When to Read |
|----------|---------|--------------|
| [FIX_SUMMARY.md](FIX_SUMMARY.md) | Overview of what was fixed | **Start here** - Read first |
| [CELERY_WORKER_SETUP.md](CELERY_WORKER_SETUP.md) | Complete setup guide | For deployment and configuration |
| [SCHEDULED_TASKS_SETUP.md](SCHEDULED_TASKS_SETUP.md) | Periodic task configuration | **Required** - Set up scheduled tasks |
| [CELERY_QUICK_REFERENCE.md](CELERY_QUICK_REFERENCE.md) | Developer cheat sheet | For daily development tasks |
| [.env.example](.env.example) | Configuration template | When setting up new environments |

## 🔍 What Was Fixed?

### Before (Broken) ❌
```
[ERROR] consumer: Cannot connect to redis://:**@redis:6379/0: 
invalid username-password pair or user is disabled.
```

**Problem**: Environment variable substitution `${REDIS_PASSWORD}` doesn't work with Python's dotenv library.

### After (Working) ✅
```
[INFO] Celery Worker (WhatsApp): Redis is up.
[INFO] Starting Celery worker (WhatsApp) with Pool: gevent and Concurrency: 100
[INFO] celery@whatsapp_worker ready.
```

**Solution**: Direct password value in `CELERY_BROKER_URL='redis://:mindwell@redis:6379/0'`

## 🎯 New Architecture

### Two Specialized Workers

#### 1. WhatsApp Worker
- **Queue**: `whatsapp` (default)
- **Pool**: gevent (I/O optimized)
- **Concurrency**: 100
- **Handles**: Messaging, conversations, payments, referrals

#### 2. Football Data Worker
- **Queue**: `football_data`
- **Pool**: prefork (CPU optimized)
- **Concurrency**: 4
- **Handles**: Fixtures, odds, scores, settlements

### Benefits
✅ No more Redis authentication errors  
✅ Task isolation (football data won't block messaging)  
✅ Optimized performance (right pool for each workload)  
✅ Independent scaling  

## 🛠️ Common Commands

```bash
# View logs
docker-compose logs -f celery_io_worker          # I/O worker (WhatsApp, flows, general tasks)
docker-compose logs -f celery_cpu_worker # CPU worker (football data tasks)

# Check status
docker-compose ps

# Restart workers
docker-compose restart celery_io_worker celery_cpu_worker

# Check active tasks
docker exec -it whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect active

# Verify worker connectivity
docker exec -it whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect ping
```

## 🧪 Testing the Setup

### Manual Test
```bash
# 1. Check both workers are running
docker-compose ps | grep celery

# 2. Check logs for errors
docker-compose logs celery_io_worker | tail -20
docker-compose logs celery_cpu_worker | tail -20

# 3. Test connectivity
docker exec whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect ping
docker exec whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect ping
```

### Automated Test
```bash
./verify_celery_workers.sh
```

## 🔐 Security Notes

⚠️ **Important**: The `.env` files contain credentials and are tracked in the repository (pre-existing issue).

For production:
1. Use a strong, randomly generated Redis password
2. Consider using Docker secrets or Kubernetes secrets
3. Rotate credentials regularly
4. See `.env.example` for proper configuration structure

## 📊 Monitoring

### Check Worker Health
```bash
# WhatsApp worker stats
docker exec -it whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect stats

# Football worker stats
docker exec -it whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect stats
```

### Check Queue Lengths
```bash
# All queues
docker exec whatsappcrm_redis redis-cli -a mindwell llen whatsapp
docker exec whatsappcrm_redis redis-cli -a mindwell llen football_data
```

## 🆘 Troubleshooting

### Redis Connection Errors
1. Check Redis is running: `docker-compose ps redis`
2. Verify password in `.env`: `grep REDIS_PASSWORD .env`
3. Check Redis logs: `docker-compose logs redis`

### Worker Not Starting
1. Check for errors: `docker-compose logs celery_worker`
2. Verify dependencies: `docker-compose ps db redis`
3. Check health: `docker inspect whatsappcrm_celery_io_worker`

### Tasks Not Processing
1. Check worker is connected: `celery inspect ping`
2. Verify task routing: See [CELERY_QUICK_REFERENCE.md](CELERY_QUICK_REFERENCE.md)
3. Check queue: `docker exec whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect active_queues`

## 🔄 Rollback Plan

If you need to rollback:
```bash
# Revert to previous commit
git revert HEAD~4  # Revert last 4 commits

# Or checkout previous version
git checkout <previous-commit-hash>

# Rebuild and restart
docker-compose down
docker-compose up -d --build
```

## 📈 Scaling

Scale workers independently:
```bash
# Scale WhatsApp worker
docker-compose up -d --scale celery_io_worker=2

# Scale Football worker
docker-compose up -d --scale celery_cpu_worker=3
```

Note: Remove `container_name` from docker-compose.yml when scaling.

## 🎓 Learn More

- [Celery Documentation](https://docs.celeryproject.org/)
- [Redis Documentation](https://redis.io/docs/)
- [Django Celery Integration](https://docs.celeryproject.org/en/stable/django/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)

## 💬 Support

For issues or questions:
1. Check the [FIX_SUMMARY.md](FIX_SUMMARY.md) troubleshooting section
2. Review [CELERY_WORKER_SETUP.md](CELERY_WORKER_SETUP.md) for detailed setup
3. Run `./verify_celery_workers.sh` for diagnostics

---

**Last Updated**: 2025-12-11  
**Status**: ✅ All changes deployed and tested  
**Security Scan**: ✅ 0 vulnerabilities found
