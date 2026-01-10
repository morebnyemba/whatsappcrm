# Quick Reference: PDF Media Serving Fix

**Date:** 2026-01-10  
**Status:** ✅ COMPLETE  
**Issue:** PDFs generated but not accessible in browser/WhatsApp

## TL;DR - What Was Fixed

1. **Added SITE_URL to .env** → PDFs now get correct production URLs
2. **Replaced Nginx Proxy Manager with standard nginx** → CORS headers now applied
3. **Result:** PDFs accessible in browser and to WhatsApp/Meta

## Quick Deployment

```bash
# 1. Pull changes
git pull origin <branch>

# 2. Verify .env has SITE_URL
grep SITE_URL .env

# 3. Stop old NPM, start new nginx
docker compose stop nginx_proxy_manager
docker compose rm -f nginx_proxy_manager
docker compose up -d nginx_proxy

# 4. Restart backend
docker compose restart backend

# 5. Test
curl -I https://backend.betblitz.co.zw/media/test.pdf
```

## Quick Test

```bash
# Test PDF generation and access
# 1. Generate PDF through app
# 2. Check logs for URL:
docker compose logs backend | grep "pdf_url"
# Should show: https://backend.betblitz.co.zw/media/fixtures_pdfs/...

# 3. Access in browser - should work!
# 4. Check CORS:
curl -I https://backend.betblitz.co.zw/media/fixtures_pdfs/test.pdf | grep "Access-Control"
# Should show: Access-Control-Allow-Origin: *
```

## What Changed

| File | Change |
|------|--------|
| `.env` | Added `SITE_URL='https://backend.betblitz.co.zw'` |
| `docker-compose.yml` | Replaced `nginx_proxy_manager` with `nginx_proxy` |
| `nginx_proxy/nginx.conf` | Added proper http block structure |

## Rollback (if needed)

```bash
git checkout HEAD~3 .env docker-compose.yml nginx_proxy/nginx.conf
docker compose up -d nginx_proxy_manager
docker compose restart backend
```

## Full Documentation

See `PDF_MEDIA_SERVING_FIX_COMPLETE.md` for:
- Detailed root cause analysis
- Complete deployment guide
- Troubleshooting section
- Testing checklist

## Support

**Logs:**
```bash
docker compose logs nginx_proxy --tail=50
docker compose logs backend | grep PDF
```

**Test Config:**
```bash
docker compose exec nginx_proxy nginx -t
```

**Common Issues:**
- 404 on PDFs → Check volume mount: `docker compose exec nginx_proxy ls /srv/www/media/fixtures_pdfs/`
- No CORS → Check config loaded: `docker compose exec nginx_proxy nginx -T | grep Access-Control`
- Wrong URL → Check .env and restart backend: `grep SITE_URL .env && docker compose restart backend`
