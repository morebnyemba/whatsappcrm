# Nginx SSL, HTTP/2, and Media Serving Configuration

This document describes the changes made to configure Nginx with Let's Encrypt SSL certificates, enable HTTP/2, and ensure proper media file serving.

## Changes Summary

### 1. SSL Certificate Configuration
- **Certificate Location**: `/etc/letsencrypt/live/betblitz.co.zw/`
  - Full chain: `fullchain.pem`
  - Private key: `privkey.pem`

### 2. Docker Compose Updates
The `docker-compose.yml` now directly mounts the Let's Encrypt certificates from the host system:

```yaml
volumes:
  - /etc/letsencrypt:/etc/nginx/ssl:ro  # Direct mount from host
```

The `npm_letsencrypt` volume has been removed as it's no longer needed.

### 3. Nginx Configuration Updates
- **HTTP/2 Enabled**: All HTTPS server blocks use `listen 443 ssl http2`
- **Modern SSL/TLS Settings**: 
  - Protocols: TLSv1.2 and TLSv1.3
  - Secure cipher suites
  - OCSP stapling enabled
  - Session caching configured
- **Inline SSL Configuration**: No longer depends on external `options-ssl-nginx.conf` or `ssl-dhparams.pem` files

### 4. Media File Serving
Media files are properly configured to be served from `/media/` with:
- CORS headers for WhatsApp/Meta access
- Proper caching (7 days)
- OPTIONS request handling for CORS preflight

## Deployment Instructions

### Prerequisites
- SSL certificates must be present at `/etc/letsencrypt/live/betblitz.co.zw/` on the host
- Docker and Docker Compose installed
- Certificates should be valid and not expired

### Deploy Steps

1. **Pull the latest changes**:
   ```bash
   cd ~/whatsappcrm
   git pull origin main  # or your branch name
   ```

2. **Stop the current nginx container**:
   ```bash
   docker-compose stop nginx_proxy
   ```

3. **Restart with new configuration**:
   ```bash
   docker-compose up -d nginx_proxy
   ```

4. **Verify the configuration**:
   ```bash
   # Check if container is running
   docker-compose ps nginx_proxy
   
   # Check logs for any errors
   docker-compose logs nginx_proxy
   
   # Verify SSL certificate is loaded
   docker exec whatsappcrm_nginx_proxy ls -la /etc/nginx/ssl/live/betblitz.co.zw/
   ```

5. **Test HTTPS and HTTP/2**:
   ```bash
   # Test SSL certificate
   curl -I https://backend.betblitz.co.zw
   
   # Test HTTP/2 (requires curl with HTTP/2 support)
   curl -I --http2 https://backend.betblitz.co.zw
   
   # Test media file access
   curl -I https://backend.betblitz.co.zw/media/
   ```

6. **Verify HTTP to HTTPS redirect**:
   ```bash
   curl -I http://backend.betblitz.co.zw
   # Should return 301 redirect to https://
   ```

## Troubleshooting

### SSL Certificate Not Found
If you see errors about missing certificates:
```bash
# Verify certificates exist on host
ls -la /etc/letsencrypt/live/betblitz.co.zw/

# Ensure permissions allow Docker to read them
sudo chmod 755 /etc/letsencrypt/live/
sudo chmod 755 /etc/letsencrypt/archive/
```

### HTTP/2 Not Working
HTTP/2 requires HTTPS. Verify:
1. SSL certificates are properly loaded
2. Nginx version supports HTTP/2 (nginx:alpine image does)
3. Client supports HTTP/2

### Media Files Not Accessible
Check:
1. Media files are uploaded to the backend container
2. The `media_volume` is properly shared between backend and nginx_proxy
3. File permissions allow nginx to read them

```bash
# Check media volume
docker exec whatsappcrm_nginx_proxy ls -la /srv/www/media/

# Check backend media directory
docker exec whatsappcrm_backend_app ls -la /app/mediafiles/
```

## Certificate Renewal

Let's Encrypt certificates are automatically renewed by Certbot. The nginx configuration supports the ACME challenge at `/.well-known/acme-challenge/` for certificate renewal.

**No action needed** - Certbot will handle renewals automatically, and the mounted volume ensures nginx always uses the latest certificates.

To manually test renewal:
```bash
sudo certbot renew --dry-run
```

## Security Features

- **TLS 1.2 and 1.3**: Modern secure protocols only
- **Strong Ciphers**: Forward secrecy enabled
- **OCSP Stapling**: Improved certificate validation
- **HSTS Ready**: Can be enabled by adding header
- **CORS for Media**: Allows WhatsApp/Meta to access media files securely

## Supported Domains

The configuration supports:
- `backend.betblitz.co.zw` - API backend
- `dashboard.betblitz.co.zw` - Frontend dashboard
- `betblitz.co.zw` - Main domain (backwards compatibility)
- `www.betblitz.co.zw` - WWW variant

All domains redirect HTTP to HTTPS automatically.

## Additional Notes

- The configuration uses the same certificate for all domains (SAN certificate)
- Media files have CORS headers to allow external access (e.g., from WhatsApp)
- Static files are cached for 7 days
- Maximum upload size is set to 100MB (`client_max_body_size`)
