# Worker Setup Guide for Performance-Optimized Configuration

This guide explains how to set up Celery workers to take advantage of the performance optimizations implemented in this PR.

## Overview

The system now uses explicit queue routing with priorities to ensure:
- **WhatsApp/Flow messages** are processed instantly (< 1 second)
- **Football data tasks** are processed by dedicated workers
- **User-facing tasks** get priority over background tasks

## Queue Structure

### 1. `celery` Queue (Main/Fast Queue)
**Purpose**: Handle user-facing WhatsApp messages and flow processing

**Tasks**:
- `process_flow_for_message_task` (priority: 9)
- `send_whatsapp_message_task` (priority: 9)
- `send_read_receipt_task` (priority: 7)
- Other general business tasks

**Characteristics**:
- High priority tasks
- Requires fast response time
- Should have higher concurrency

### 2. `football_data` Queue (Background Queue)
**Purpose**: Handle football data fetching, odds updates, and settlement

**Tasks**:
- All football data fetching tasks
- Score and settlement tasks
- Bet ticket processing tasks

**Characteristics**:
- Lower priority (background tasks)
- Can handle longer processing times
- Lower concurrency is acceptable

## Worker Configuration

### Development Setup (Docker Compose)

Add/update workers in your `docker-compose.yml`:

```yaml
services:
  # Main worker for WhatsApp/Flow messages
  celery_worker:
    build: ./whatsappcrm_backend
    command: celery -A whatsappcrm_backend worker -Q celery -c 4 -l info -n celery_worker@%h
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - DATABASE_URL=postgresql://...
    depends_on:
      - redis
      - db
    restart: unless-stopped

  # Football data worker
  celery_football_worker:
    build: ./whatsappcrm_backend
    command: celery -A whatsappcrm_backend worker -Q football_data -c 2 -l info -n football_worker@%h
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - DATABASE_URL=postgresql://...
    depends_on:
      - redis
      - db
    restart: unless-stopped

  # Beat scheduler for periodic tasks
  celery_beat:
    build: ./whatsappcrm_backend
    command: celery -A whatsappcrm_backend beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - DATABASE_URL=postgresql://...
    depends_on:
      - redis
      - db
    restart: unless-stopped
```

### Production Setup (Systemd Services)

#### Main Worker Service (`/etc/systemd/system/celery-worker.service`)

```ini
[Unit]
Description=Celery Worker (Main Queue)
After=network.target redis.service postgresql.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/var/www/whatsappcrm/whatsappcrm_backend
EnvironmentFile=/var/www/whatsappcrm/.env
ExecStart=/var/www/whatsappcrm/venv/bin/celery -A whatsappcrm_backend worker \
    -Q celery \
    -c 4 \
    -l info \
    -n celery_worker@%h \
    --pidfile=/var/run/celery/celery-worker.pid \
    --logfile=/var/log/celery/celery-worker.log
ExecStop=/bin/kill -s TERM $MAINPID
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

#### Football Worker Service (`/etc/systemd/system/celery-football-worker.service`)

```ini
[Unit]
Description=Celery Worker (Football Data Queue)
After=network.target redis.service postgresql.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/var/www/whatsappcrm/whatsappcrm_backend
EnvironmentFile=/var/www/whatsappcrm/.env
ExecStart=/var/www/whatsappcrm/venv/bin/celery -A whatsappcrm_backend worker \
    -Q football_data \
    -c 2 \
    -l info \
    -n football_worker@%h \
    --pidfile=/var/run/celery/celery-football-worker.pid \
    --logfile=/var/log/celery/celery-football-worker.log
ExecStop=/bin/kill -s TERM $MAINPID
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

#### Beat Scheduler Service (`/etc/systemd/system/celery-beat.service`)

```ini
[Unit]
Description=Celery Beat Scheduler
After=network.target redis.service postgresql.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/var/www/whatsappcrm/whatsappcrm_backend
EnvironmentFile=/var/www/whatsappcrm/.env
ExecStart=/var/www/whatsappcrm/venv/bin/celery -A whatsappcrm_backend beat \
    -l info \
    --scheduler django_celery_beat.schedulers:DatabaseScheduler \
    --pidfile=/var/run/celery/celery-beat.pid \
    --logfile=/var/log/celery/celery-beat.log
ExecStop=/bin/kill -s TERM $MAINPID
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

### Enable and Start Services

```bash
# Create necessary directories
sudo mkdir -p /var/run/celery /var/log/celery
sudo chown www-data:www-data /var/run/celery /var/log/celery

# Enable services
sudo systemctl enable celery-worker.service
sudo systemctl enable celery-football-worker.service
sudo systemctl enable celery-beat.service

# Start services
sudo systemctl start celery-worker.service
sudo systemctl start celery-football-worker.service
sudo systemctl start celery-beat.service

# Check status
sudo systemctl status celery-worker.service
sudo systemctl status celery-football-worker.service
sudo systemctl status celery-beat.service
```

## Concurrency Settings Explained

### Main Worker (`-c 4`)
- **4 concurrent processes** for handling WhatsApp/Flow messages
- Higher concurrency ensures instant response times
- Can handle multiple simultaneous user conversations

### Football Worker (`-c 2`)
- **2 concurrent processes** for football data tasks
- Lower concurrency is sufficient for background tasks
- Prevents overwhelming external APIs with requests

### Adjusting Concurrency

Based on your server resources:

```bash
# Small server (1-2 CPU cores, 2-4GB RAM)
celery -A whatsappcrm_backend worker -Q celery -c 2
celery -A whatsappcrm_backend worker -Q football_data -c 1

# Medium server (4 CPU cores, 8GB RAM)
celery -A whatsappcrm_backend worker -Q celery -c 4
celery -A whatsappcrm_backend worker -Q football_data -c 2

# Large server (8+ CPU cores, 16GB+ RAM)
celery -A whatsappcrm_backend worker -Q celery -c 8
celery -A whatsappcrm_backend worker -Q football_data -c 4
```

## Monitoring Workers

### Check Active Workers
```bash
celery -A whatsappcrm_backend inspect active
```

### Check Registered Tasks
```bash
celery -A whatsappcrm_backend inspect registered
```

### Check Queue Status
```bash
celery -A whatsappcrm_backend inspect stats
```

### Monitor in Real-Time (Flower)

Install Flower for web-based monitoring:

```bash
pip install flower

# Start Flower
celery -A whatsappcrm_backend flower --port=5555
```

Then access at `http://localhost:5555`

## Troubleshooting

### Tasks Not Being Picked Up

**Symptom**: Tasks queued but not processing

**Check**:
1. Verify workers are running: `systemctl status celery-*`
2. Check worker logs: `tail -f /var/log/celery/*.log`
3. Verify queue routing: `celery -A whatsappcrm_backend inspect active_queues`

**Solution**:
```bash
# Restart workers
sudo systemctl restart celery-worker.service
sudo systemctl restart celery-football-worker.service
```

### Slow Message Processing

**Symptom**: Messages still taking > 1 second

**Check**:
1. Redis connection: `redis-cli ping`
2. Worker concurrency: `ps aux | grep celery`
3. Database connections: Check PostgreSQL connections

**Solution**:
```bash
# Increase main worker concurrency
sudo systemctl stop celery-worker.service
# Edit service file to increase -c value
sudo systemctl daemon-reload
sudo systemctl start celery-worker.service
```

### Football Tasks Stuck

**Symptom**: Football data not updating

**Check**:
1. Football worker status: `systemctl status celery-football-worker.service`
2. Task queue: `celery -A whatsappcrm_backend inspect stats`
3. API limits: Check football API response times

**Solution**:
```bash
# Restart football worker
sudo systemctl restart celery-football-worker.service

# If tasks are stuck, purge and restart
celery -A whatsappcrm_backend purge -Q football_data
sudo systemctl restart celery-football-worker.service
```

## Best Practices

1. **Separate Workers**: Always run separate workers for `celery` and `football_data` queues
2. **Monitor Resources**: Keep an eye on CPU, memory, and Redis usage
3. **Log Rotation**: Set up log rotation for Celery logs
4. **Graceful Restarts**: Use `TERM` signal for graceful shutdowns
5. **Health Checks**: Monitor worker health and restart if needed

## Environment Variables

Ensure these are set in your `.env` file:

```bash
# Required
CELERY_BROKER_URL=redis://localhost:6379/0
DATABASE_URL=postgresql://user:pass@localhost/whatsappcrm

# Optional (with defaults)
SESSION_IDLE_TIMEOUT_MINUTES=5
CELERY_TASK_TIME_LIMIT_SECONDS=1800
```

## Testing the Setup

### 1. Test Main Worker
Send a WhatsApp message and verify it's processed within 1 second.

### 2. Test Football Worker
Trigger a football data update and verify tasks are picked up:
```bash
# From Django shell
from football_data_app.tasks import run_apifootball_full_update_task
run_apifootball_full_update_task.delay()
```

### 3. Monitor Logs
```bash
# Main worker
tail -f /var/log/celery/celery-worker.log

# Football worker
tail -f /var/log/celery/celery-football-worker.log
```

## Support

For issues or questions:
1. Check logs: `/var/log/celery/*.log`
2. Review documentation: `PERFORMANCE_IMPROVEMENTS.md`
3. Monitor with Flower: http://localhost:5555
4. Check Celery docs: https://docs.celeryproject.org/
