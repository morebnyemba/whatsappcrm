# Docker Quick Start Guide

This is a quick reference for starting the WhatsApp CRM application fresh after encountering issues.

## 🚀 Fresh Start (App Not Starting)

If your app is not starting or you're encountering migration/database errors, follow these steps:

### Option 1: Complete Reset (Recommended for Fresh Start)

```bash
# 1. Stop and remove all containers and volumes
docker compose down -v

# 2. Start everything fresh
docker compose up -d

# 3. Wait for services to initialize (30-60 seconds)
sleep 30

# 4. Check logs to see if migrations ran successfully
docker compose logs -f backend

# 5. Once backend is ready, create a superuser
docker compose exec backend python manage.py createsuperuser

# 6. Initialize football leagues (if using betting features)
docker compose exec backend python manage.py football_league_setup
```

### Option 2: Reset Using Script

```bash
# Use the automated reset script
./reset_migrations.sh
```

This script will:
- Detect your environment (Docker or local)
- Guide you through the reset process
- Clear database and regenerate migrations
- Prompt you to create a superuser

## 🔍 Troubleshooting Commands

### Check Service Status

```bash
# View all running services
docker compose ps

# Check if database is ready
docker compose exec db pg_isready -U crm_user

# View logs for specific service
docker compose logs -f backend
docker compose logs -f db
docker compose logs -f redis
```

### View Recent Errors

```bash
# Last 100 lines of backend logs
docker compose logs --tail=100 backend

# Follow logs in real-time
docker compose logs -f backend
```

### Restart Services

```bash
# Restart all services
docker compose restart

# Restart specific service
docker compose restart backend
```

### Database Operations

```bash
# Access database shell
docker compose exec db psql -U crm_user -d whatsapp_crm_dev

# Run migrations
docker compose exec backend python manage.py migrate

# Create new migrations
docker compose exec backend python manage.py makemigrations

# Show migration status
docker compose exec backend python manage.py showmigrations
```

### Clear Specific Volumes

```bash
# Stop services first
docker compose down

# Remove specific volumes
docker volume rm whatsappcrm_postgres_data
docker volume rm whatsappcrm_redis_data

# Start services (fresh database)
docker compose up -d
```

## 🛑 Common Issues and Solutions

### Issue: "App is not starting"

**Symptoms:**
- Backend container keeps restarting
- Error messages in logs about migrations or database

**Solution:**
```bash
# Check the logs first
docker compose logs backend

# If migration errors, try complete reset
docker compose down -v
docker compose up -d
```

### Issue: "Migration conflicts"

**Symptoms:**
- Error messages about conflicting migrations
- Messages about "multiple leaf nodes in migration graph"

**Solution:**
```bash
# Use the reset script
./reset_migrations.sh

# Or manually
docker compose down -v
docker compose up -d
```

### Issue: "Database connection refused"

**Symptoms:**
- Error: "could not connect to server"
- Backend can't connect to PostgreSQL

**Solution:**
```bash
# Check if database is running
docker compose ps db

# Check database health
docker compose exec db pg_isready -U crm_user

# If not ready, restart database
docker compose restart db
sleep 10
docker compose restart backend
```

### Issue: "Redis connection failed"

**Symptoms:**
- Celery workers failing to start
- Error: "Error connecting to Redis"

**Solution:**
```bash
# Check Redis is running
docker compose ps redis

# Test Redis connection
# Option 1: Replace YOUR_PASSWORD with actual password from your .env file
docker compose exec redis redis-cli -a YOUR_PASSWORD ping

# Option 2: Automatically read password from .env (Linux/Mac only)
docker compose exec redis redis-cli -a $(grep REDIS_PASSWORD .env | cut -d '=' -f2) ping

# Should return "PONG"

# If issues, restart Redis
docker compose restart redis
docker compose restart celery_io_worker celery_cpu_worker
```

### Issue: "Permission denied" errors

**Symptoms:**
- Cannot write to files or directories
- Permission errors in logs

**Solution:**
```bash
# Fix permissions on local files
sudo chown -R $USER:$USER whatsappcrm_backend/

# Restart services
docker compose restart
```

## 📋 Essential Commands Reference

| Action | Command |
|--------|---------|
| **Start all services** | `docker compose up -d` |
| **Stop all services** | `docker compose down` |
| **Stop and remove volumes** | `docker compose down -v` |
| **View all logs** | `docker compose logs -f` |
| **View backend logs** | `docker compose logs -f backend` |
| **Check service status** | `docker compose ps` |
| **Restart all services** | `docker compose restart` |
| **Rebuild and restart** | `docker compose up -d --build` |
| **Run migrations** | `docker compose exec backend python manage.py migrate` |
| **Create migrations** | `docker compose exec backend python manage.py makemigrations` |
| **Create superuser** | `docker compose exec backend python manage.py createsuperuser` |
| **Django shell** | `docker compose exec backend python manage.py shell` |
| **Database shell** | `docker compose exec db psql -U crm_user -d whatsapp_crm_dev` |
| **Redis CLI** | `docker compose exec redis redis-cli -a YOUR_PASSWORD` |

## 🔄 Complete Rebuild

If nothing else works, try a complete rebuild:

```bash
# 1. Stop everything and remove all volumes and images
docker compose down -v --rmi all

# 2. Remove any orphaned volumes
docker volume prune -f

# 3. Clean Docker system (optional)
docker system prune -f

# 4. Start fresh with rebuild
docker compose up -d --build

# 5. Wait for initialization
sleep 60

# 6. Check logs
docker compose logs -f backend

# 7. Create superuser once ready
docker compose exec backend python manage.py createsuperuser
```

## 📚 Additional Resources

- **Detailed Database Reset Guide**: [DATABASE_RESET_COMMANDS.md](DATABASE_RESET_COMMANDS.md)
- **Migration Reset Guide**: [MIGRATION_RESET_GUIDE.md](MIGRATION_RESET_GUIDE.md)
- **Full README**: [README.md](README.md)

## 💡 Tips

1. **Always check logs first**: `docker compose logs -f backend`
2. **Backup before resetting**: `./backup_database.sh`
3. **Wait for services**: Give services 30-60 seconds to initialize after starting
4. **Check .env file**: Ensure all required variables are set
5. **Use docker compose not docker-compose**: The new V2 syntax uses a space

## ⚠️ Important Notes

- **Data Loss Warning**: `docker compose down -v` will DELETE ALL DATA
- **Always Backup First**: Run `./backup_database.sh` before major changes
- **Environment File**: Make sure `.env` file exists and has correct values
- **Docker Compose V2**: Use `docker compose` (space) not `docker-compose` (hyphen)
- **Logs are Your Friend**: Always check logs when troubleshooting issues

## 🆘 Still Having Issues?

1. Check `.env` file has all required variables
2. Verify Docker and Docker Compose are installed: `docker compose version`
3. Check disk space: `df -h`
4. View full logs: `docker compose logs > full_logs.txt`
5. Review error messages carefully - they often point to the exact issue
