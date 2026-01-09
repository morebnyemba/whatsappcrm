# PDF Accessibility Fix

## Date: 2026-01-09

## Issue Report
User reported: "the issue is that generated pdf's are not accessible in browser or to other servers meaning they are not being correctly served"

## Root Cause Analysis

### The Problem
Generated PDF files were not accessible via browser or to external servers (like WhatsApp/Meta) because of a **path mismatch** between three components:

1. **Django Settings (`settings.py`)**:
   - `MEDIA_ROOT = BASE_DIR / 'media'`
   - Resolves to: `/app/media`

2. **Docker Volume Mount (`docker-compose.yml`)**:
   - Backend: `media_volume:/app/mediafiles`
   - Volume mounted at: `/app/mediafiles`

3. **Nginx Configuration (`nginx.conf`)**:
   - Nginx: `media_volume:/srv/www/media/:ro`
   - Serves files from: `/srv/www/media/`

### What Was Happening
```
Django PDF Generation (utils.py)
  ↓
Writes to: /app/media/fixtures_pdfs/fixtures_*.pdf
  ↓
Location: Container filesystem (NOT in shared volume)
  ↓
Nginx looks in: /srv/www/media/ (mapped to media_volume)
  ↓
Result: File not found (404)
```

### Why It Failed
- Django was writing PDFs to `/app/media` (container filesystem)
- Docker volume `media_volume` was mounted at `/app/mediafiles` (different path!)
- Nginx was serving from the volume at `/srv/www/media/`
- Since PDFs weren't in the volume, Nginx couldn't access them

## Solution

### Change Made
Fixed the `MEDIA_ROOT` path in `settings.py` to match the docker volume mount:

```python
# Before (WRONG - doesn't match volume mount)
MEDIA_ROOT = BASE_DIR / 'media'

# After (CORRECT - matches volume mount)
MEDIA_ROOT = BASE_DIR / 'mediafiles'
```

### How It Works Now
```
Django PDF Generation (utils.py)
  ↓
Writes to: /app/mediafiles/fixtures_pdfs/fixtures_*.pdf
  ↓
Location: In media_volume (shared between containers)
  ↓
Nginx serves from: /srv/www/media/ (same media_volume)
  ↓
Result: File accessible via HTTPS URL ✓
```

## File Changed

**`whatsappcrm_backend/whatsappcrm_backend/settings.py`** (line 140):
```python
MEDIA_ROOT = BASE_DIR / 'mediafiles'  # Changed from 'media' to match docker volume mount
```

## Verification

### Docker Volume Configuration (docker-compose.yml)
```yaml
backend:
  volumes:
    - media_volume:/app/mediafiles      # Backend writes here

nginx_proxy_manager:
  volumes:
    - media_volume:/srv/www/media/:ro   # Nginx serves from here

volumes:
  media_volume:  # Shared between both containers
```

### Nginx Configuration (nginx.conf)
```nginx
location /media/ {
    alias /srv/www/media/;  # Serves files from media_volume
    
    # CORS headers for WhatsApp/Meta access
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
    # ... (other headers)
}
```

### PDF Generation (utils.py)
```python
media_root = settings.MEDIA_ROOT  # Now correctly points to /app/mediafiles
pdf_dir = os.path.join(media_root, 'fixtures_pdfs')
os.makedirs(pdf_dir, exist_ok=True)
# PDF written to: /app/mediafiles/fixtures_pdfs/fixtures_*.pdf ✓
```

## Impact

### Before Fix
- ❌ PDFs generated but not accessible
- ❌ Browser returns 404 for PDF URLs
- ❌ WhatsApp/Meta can't fetch PDF documents
- ❌ Users can't download fixtures

### After Fix
- ✅ PDFs written to shared volume
- ✅ Accessible via browser at `https://backend.betblitz.co.zw/media/fixtures_pdfs/*.pdf`
- ✅ WhatsApp/Meta can access and download PDFs
- ✅ CORS headers properly set for external access
- ✅ No changes needed to docker-compose.yml or nginx.conf

## Testing Recommendations

1. **Generate a PDF**:
   - Trigger a flow that generates a fixtures PDF
   - Check logs for: `PDF generated successfully: /app/mediafiles/fixtures_pdfs/fixtures_*.pdf`

2. **Verify File Exists in Volume**:
   ```bash
   docker exec whatsappcrm_backend_app ls -la /app/mediafiles/fixtures_pdfs/
   ```

3. **Access via Browser**:
   - Get PDF URL from logs (e.g., `https://backend.betblitz.co.zw/media/fixtures_pdfs/fixtures_20260109_123456.pdf`)
   - Open in browser - should download/display PDF

4. **Verify Nginx Access**:
   ```bash
   docker exec whatsappcrm_nginx_proxy_manager ls -la /srv/www/media/fixtures_pdfs/
   ```
   Should show the same PDF files

5. **Test WhatsApp Integration**:
   - Send a message that triggers PDF generation
   - Verify WhatsApp receives and can display the PDF document

## Related Documentation

- Docker volume configuration: `docker-compose.yml`
- Nginx configuration: `nginx_proxy/nginx.conf`
- Django settings: `whatsappcrm_backend/whatsappcrm_backend/settings.py`
- PDF generation: `whatsappcrm_backend/football_data_app/utils.py` (line 814)
- PDF flow action: `whatsappcrm_backend/flows/services.py` (line 1193)

## Deployment Notes

- **Safe to deploy**: Single configuration change
- **No migrations required**: Only changes Django settings
- **No docker rebuild required**: Settings are read at runtime
- **Restart required**: Django must restart to load new settings
- **No data loss**: Existing files remain in volume

### Deployment Steps
1. Pull the updated code
2. Restart backend container: `docker-compose restart backend`
3. Verify PDFs are accessible
4. (Optional) Clean up old PDFs from `/app/media` if any exist

## Commit

- Commit Hash: 70a58c4
- Message: "Fix PDF accessibility issue by correcting MEDIA_ROOT path to match docker volume mount"
- Branch: copilot/fix-betting-flow-bug-yet-again
