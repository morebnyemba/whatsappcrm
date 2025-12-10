# Migration Guide: Custom Nginx to Nginx Proxy Manager

This guide helps you migrate from the custom nginx configuration to Nginx Proxy Manager (NPM).

## Overview

We've replaced the custom nginx container with Nginx Proxy Manager, which provides:
- Web-based UI for configuration (no more manual config file editing)
- Built-in Let's Encrypt SSL certificate management with auto-renewal
- Access control lists for IP-based restrictions
- Better logging and monitoring capabilities

## What Changed

### Before (Custom Nginx)
- Service: `nginx_proxy` using `nginx:1.25-alpine`
- Configuration: Manual editing of `nginx_proxy/nginx.conf`
- SSL: Manual certificate management with certbot
- Port 80 (HTTP), 443 (HTTPS)

### After (Nginx Proxy Manager)
- Service: `nginx_proxy_manager` using `jc21/nginx-proxy-manager:latest`
- Configuration: Web UI at http://server-ip:81
- SSL: Automatic Let's Encrypt integration via UI
- Port 80 (HTTP), 443 (HTTPS), 81 (Admin UI)

## Migration Steps

### 1. Backup Existing Configuration

```bash
# Backup your existing nginx configuration
cp nginx_proxy/nginx.conf nginx_proxy/nginx.conf.backup

# Note down your current SSL certificate paths
ls -la /etc/letsencrypt/live/
```

### 2. Stop Existing Services

```bash
docker-compose down
```

### 3. Update Repository

```bash
git pull origin main  # or your branch name
```

The updated `docker-compose.yml` now includes the `nginx_proxy_manager` service.

### 4. Start Services with NPM

```bash
docker-compose up -d
```

### 5. Access NPM Admin UI

Navigate to: `http://your-server-ip:81`

**Default Login:**
- Email: `admin@example.com`
- Password: `changeme`

**⚠️ CRITICAL:** Change the default password immediately!

### 6. Configure Proxy Host

Create a new Proxy Host in NPM:

#### Details Tab
- **Domain Names:** `betblitz.co.zw`, `www.betblitz.co.zw` (or your domains)
- **Scheme:** `http`
- **Forward Hostname/IP:** `frontend`
- **Forward Port:** `80`
- **Cache Assets:** ✅ Enabled
- **Block Common Exploits:** ✅ Enabled
- **Websockets Support:** ✅ Enabled

#### SSL Tab
- **SSL Certificate:** Request a new SSL Certificate
- **Force SSL:** ✅ Enabled
- **HTTP/2 Support:** ✅ Enabled
- **HSTS Enabled:** ✅ Enabled (optional, recommended)
- **Email Address:** your-email@example.com
- **Terms of Service:** ✅ I Agree

#### Advanced Tab

Add this custom Nginx configuration:

```nginx
# Proxy API requests to Django backend
location /crm-api/ {
    proxy_pass http://backend:8000;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $http_host;
    proxy_redirect off;
    proxy_buffering off;
}

# Proxy Django admin
location /admin/ {
    proxy_pass http://backend:8000;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $http_host;
    proxy_redirect off;
}

# Serve Django static files
location /static/ {
    alias /srv/www/static/;
    expires 7d;
    add_header Cache-Control "public, must-revalidate, proxy-revalidate";
}

# Serve Django media files
location /media/ {
    alias /srv/www/media/;
    expires 7d;
    add_header Cache-Control "public, must-revalidate, proxy-revalidate";
}
```

### 7. Verify Configuration

1. **Test HTTP to HTTPS Redirect:**
   ```bash
   curl -I http://yourdomain.com
   # Should see: HTTP/1.1 301 Moved Permanently or redirect to HTTPS
   ```

2. **Test HTTPS:**
   ```bash
   curl -I https://yourdomain.com
   # Should see: HTTP/2 200
   ```

3. **Test API Endpoint:**
   ```bash
   curl https://yourdomain.com/crm-api/
   ```

4. **Test Static Files:**
   ```bash
   curl -I https://yourdomain.com/static/
   ```

### 8. DNS Configuration

Ensure your DNS records point to your server:
- A Record: `betblitz.co.zw` → `93.127.139.173`
- A Record: `www.betblitz.co.zw` → `93.127.139.173`

### 9. Firewall Rules

Ensure these ports are open:
- Port 80 (HTTP) - Required for Let's Encrypt validation
- Port 443 (HTTPS) - Application traffic
- Port 81 (NPM Admin UI) - **Restrict access via firewall or NPM Access Lists**

**Security Recommendation:** Restrict port 81 access to trusted IPs only:

```bash
# Using ufw (Ubuntu/Debian)
sudo ufw allow from YOUR_IP_ADDRESS to any port 81

# Using iptables
sudo iptables -A INPUT -p tcp --dport 81 -s YOUR_IP_ADDRESS -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 81 -j DROP
```

Or use NPM's built-in Access Lists feature.

## Troubleshooting

### NPM Container Won't Start

```bash
# Check logs
docker logs whatsappcrm_nginx_proxy_manager

# Ensure port 81 is not in use
sudo lsof -i :81

# Restart the container
docker-compose restart nginx_proxy_manager
```

### SSL Certificate Request Failed

1. Ensure ports 80 and 443 are accessible from the internet
2. Verify DNS records are correct and propagated
3. Check NPM logs: Hosts → Proxy Hosts → Your Host → View Logs
4. Ensure email address is valid

### Static/Media Files Not Loading

1. Verify volumes are mounted correctly:
   ```bash
   docker inspect whatsappcrm_nginx_proxy_manager | grep -A 10 Mounts
   ```

2. Check file permissions:
   ```bash
   docker-compose exec backend ls -la /app/staticfiles
   docker-compose exec backend ls -la /app/mediafiles
   ```

3. Verify the Advanced configuration includes the correct paths

### Can't Access Admin UI

1. Check if port 81 is mapped correctly:
   ```bash
   docker ps | grep nginx_proxy_manager
   ```

2. Try accessing via server IP: `http://YOUR_SERVER_IP:81`

3. Check firewall rules:
   ```bash
   sudo ufw status
   ```

## Benefits of NPM

✅ **No More Manual Config Editing:** All changes via web UI
✅ **Automatic SSL Renewal:** Never worry about expired certificates
✅ **Access Lists:** Built-in IP whitelisting/blacklisting
✅ **Better Logging:** View access logs and error logs per proxy host
✅ **Stream Support:** TCP/UDP forwarding for non-HTTP services
✅ **Multiple Certificates:** Manage multiple domains easily
✅ **Custom 404 Pages:** Professional error handling

## Rollback (If Needed)

If you need to rollback to the custom nginx:

```bash
# Stop services
docker-compose down

# Restore old docker-compose.yml from git
git checkout HEAD~1 docker-compose.yml

# Start with old configuration
docker-compose up -d
```

## Additional Resources

- [Nginx Proxy Manager Official Documentation](https://nginxproxymanager.com/guide/)
- [NPM GitHub Repository](https://github.com/NginxProxyManager/nginx-proxy-manager)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)

## Support

For issues or questions:
1. Check NPM logs: `docker logs whatsappcrm_nginx_proxy_manager`
2. Review NPM documentation
3. Contact the development team
