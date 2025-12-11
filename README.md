# WhatsApp CRM

A comprehensive WhatsApp Business CRM solution with automated conversational flows, customer management, and betting/payment integrations. Built with Django REST Framework backend and React (Vite) frontend, containerized with Docker for easy deployment.

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Nginx Proxy Manager                             │
│              (SSL/TLS, Web UI, Auto SSL Renewal)                    │
├────────────────────────────┬────────────────────────────────────────┤
│                            │                                        │
│     ┌──────────────────────▼──────────────────────┐                │
│     │              React Frontend                  │                │
│     │           (Vite + Tailwind CSS)              │                │
│     └──────────────────────┬──────────────────────┘                │
│                            │ API Calls (/crm-api/)                  │
│     ┌──────────────────────▼──────────────────────┐                │
│     │            Django Backend                    │                │
│     │    (REST API + WhatsApp Business API)        │                │
│     └────────┬───────────────────────┬────────────┘                │
│              │                       │                              │
│     ┌────────▼────────┐     ┌───────▼────────┐                     │
│     │   PostgreSQL    │     │     Redis      │                     │
│     │   (Database)    │     │ (Celery Broker)│                     │
│     └─────────────────┘     └───────┬────────┘                     │
│                                     │                              │
│                         ┌───────────▼───────────┐                  │
│                         │   Celery Workers      │                  │
│                         │   + Celery Beat       │                  │
│                         │ (Background Tasks)    │                  │
│                         └───────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```

## 🛠️ Tech Stack

### Backend
- **Framework**: Django 4.x with Django REST Framework
- **Database**: PostgreSQL 15
- **Task Queue**: Celery with Redis broker
- **Scheduler**: Celery Beat with django-celery-beat
- **Authentication**: JWT (djangorestframework-simplejwt) + Djoser
- **Admin UI**: django-jazzmin theme
- **WSGI Server**: Gunicorn
- **ASGI Server**: Daphne (for async support)

### Frontend
- **Framework**: React 19 (Vite)
- **Styling**: Tailwind CSS 4.x
- **UI Components**: Radix UI + shadcn/ui
- **State Management**: React Query (TanStack Query)
- **Forms**: React Hook Form + Zod validation
- **Charts**: Recharts
- **Flow Builder**: ReactFlow
- **Routing**: React Router DOM 7.x

### Infrastructure
- **Containerization**: Docker + Docker Compose
- **Reverse Proxy**: Nginx Proxy Manager (with SSL/TLS support and web UI)
- **Database**: PostgreSQL 15 Alpine
- **Cache/Broker**: Redis 7 Alpine

## 📁 Project Structure

```
whatsappcrm/
├── docker-compose.yml          # Multi-service orchestration
├── .env                        # Environment variables (root level)
├── nginx_proxy/                # Nginx reverse proxy configuration
│   └── nginx.conf
├── whatsappcrm_backend/        # Django backend application
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── manage.py
│   ├── whatsappcrm_backend/    # Django project settings
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── celery.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── conversations/          # WhatsApp messages & contacts
│   ├── customer_data/          # Customer profiles, wallets, bets
│   ├── flows/                  # Conversational flow engine
│   ├── meta_integration/       # Meta/WhatsApp Business API
│   ├── media_manager/          # Media file handling
│   ├── football_data_app/      # Sports/betting data
│   ├── paynow_integration/     # Payment gateway integration
│   ├── referrals/              # Referral system
│   └── stats/                  # Analytics & statistics
└── whatsapp-crm-frontend/      # React frontend application
    ├── Dockerfile
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── components/         # Reusable UI components
        ├── pages/              # Application pages
        ├── services/           # API service layer
        ├── context/            # React context providers
        └── lib/                # Utility functions
```

## 🚀 Backend Apps/Modules

| App | Description |
|-----|-------------|
| **conversations** | Manages WhatsApp contacts and message history |
| **customer_data** | Customer profiles, wallets, transactions, and betting tickets |
| **flows** | Visual flow builder for automated conversations |
| **meta_integration** | WhatsApp Business API webhook handling and message sending |
| **media_manager** | Media file upload and management |
| **football_data_app** | Sports data, fixtures, odds, and betting markets |
| **paynow_integration** | Paynow payment gateway for deposits/withdrawals |
| **referrals** | Customer referral tracking system |
| **stats** | Analytics and reporting dashboard data |

## 💻 Frontend Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Overview with analytics charts |
| **Conversation** | Real-time WhatsApp conversation view |
| **ContactsPage** | Customer contact management |
| **FlowsPage** | List and manage conversational flows |
| **FlowEditorPage** | Visual drag-and-drop flow builder |
| **BotBuilder** | Chatbot configuration |
| **MediaLibraryPage** | Media asset management |
| **ApiSettings** | Meta/WhatsApp API configuration |
| **SavedData** | Customer data and saved information |

## 🐳 Docker Services

| Service | Image | Purpose |
|---------|-------|---------|
| **db** | postgres:15-alpine | PostgreSQL database |
| **redis** | redis:7-alpine | Celery broker & cache |
| **backend** | Custom (Django) | REST API server |
| **frontend** | Custom (React/Nginx) | Static frontend serving |
| **celery_worker** | Custom (Django) | Background task processing |
| **celery_beat** | Custom (Django) | Scheduled task runner |
| **nginx_proxy_manager** | jc21/nginx-proxy-manager | Reverse proxy with SSL & web UI |

## 🔧 Getting Started

### Prerequisites
- Docker & Docker Compose
- Git

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd whatsappcrm
   ```

2. **Create environment file**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start all services**
   ```bash
   docker-compose up -d
   ```

4. **Run database migrations**
   ```bash
   docker-compose exec backend python manage.py migrate
   ```

5. **Create superuser**
   ```bash
   docker-compose exec backend python manage.py createsuperuser
   ```

6. **Initialize Football Leagues** (Required for betting features)
   ```bash
   docker-compose exec backend python manage.py football_league_setup
   ```
   
   This command fetches available football leagues from APIFootball.com and populates the database. 
   Without this step, scheduled tasks will report "0 active leagues" and no betting data will be available.
   
   **Note**: Ensure your APIFootball API key is configured in `.env` or Django admin before running this command.

7. **Configure Nginx Proxy Manager**
   - Access NPM Admin UI: http://localhost:81
   - Default credentials: admin@example.com / changeme
   - **Important**: Change default credentials on first login!

8. **Set up Proxy Hosts in NPM**
   
   Create the following proxy hosts in NPM UI:
   
   **Main Application (Frontend + API)**
   - Domain: yourdomain.com, www.yourdomain.com
   - Scheme: http
   - Forward Hostname/IP: frontend
   - Forward Port: 80
   - Enable "Websockets Support"
   - SSL: Request a new SSL certificate via Let's Encrypt
   
   **Backend API (Optional - if direct access needed)**
   - Add custom locations in "Advanced" tab:
     ```nginx
     location /crm-api/ {
         proxy_pass http://backend:8000;
         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
         proxy_set_header X-Forwarded-Proto $scheme;
         proxy_set_header Host $http_host;
     }
     
     location /admin/ {
         proxy_pass http://backend:8000;
         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
         proxy_set_header X-Forwarded-Proto $scheme;
         proxy_set_header Host $http_host;
     }
     
     location /static/ {
         alias /srv/www/static/;
     }
     
     location /media/ {
         alias /srv/www/media/;
     }
     ```

8. **Access the application**
   - Frontend: http://localhost (or https://yourdomain.com)
   - Admin Panel: http://localhost/admin
   - API: http://localhost/crm-api/
   - NPM Admin UI: http://localhost:81
   
   ⚠️ **Security Warning**: Port 81 provides administrative access to NPM. In production, restrict access using:
   - Firewall rules to allow only trusted IPs
   - NPM's built-in Access Lists feature
   - VPN or SSH tunnel for remote access

9. **Verify Football Data Setup** (Optional)
   
   Check that leagues are initialized and scheduled tasks are running:
   ```bash
   # Check that leagues were created
   docker-compose exec backend python manage.py shell -c "from football_data_app.models import League; print(f'Active leagues: {League.objects.filter(active=True).count()}')"
   
   # View Celery worker logs to monitor scheduled tasks
   docker-compose logs -f celery_worker_football
   ```
   
   You should see log messages indicating leagues are being processed, not "Found 0 active leagues".

## ⚙️ Environment Variables

Create a `.env` file in the root directory with the following variables:

```env
# Database Configuration
DB_NAME=whatsapp_crm_dev
DB_USER=crm_user
DB_PASSWORD=your_secure_password
DB_HOST=db
DB_PORT=5432

# Redis Configuration
REDIS_PASSWORD=your_redis_password
CELERY_BROKER_URL=redis://:your_redis_password@redis:6379/0

# Django Settings
SECRET_KEY=your_django_secret_key
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Meta/WhatsApp API (configured via admin panel)
# These are typically stored in the database via MetaAppConfig model

# Celery Configuration
CELERY_WORKER_POOL_TYPE=gevent
CELERY_WORKER_CONCURRENCY=100

# Optional
DJANGO_PORT_LOCAL=8000
```

## 🔧 Nginx Proxy Manager Configuration

Nginx Proxy Manager (NPM) provides a user-friendly web interface for managing reverse proxy configurations with built-in SSL certificate management.

### Initial Setup

1. **Access Admin UI**: Navigate to `http://your-server:81`
2. **Default Login Credentials**:
   - Email: `admin@example.com`
   - Password: `changeme`
3. **⚠️ CRITICAL SECURITY STEPS**:
   - Change default credentials immediately after first login
   - Restrict port 81 access using firewall rules or Access Lists
   - Consider using SSH tunnel for remote access: `ssh -L 8081:localhost:81 user@server`

### Creating Proxy Hosts

#### Main Application Proxy Host

1. Go to **Hosts** → **Proxy Hosts** → **Add Proxy Host**
2. **Details Tab**:
   - Domain Names: `yourdomain.com`, `www.yourdomain.com`
   - Scheme: `http`
   - Forward Hostname/IP: `frontend`
   - Forward Port: `80`
   - ✅ Cache Assets
   - ✅ Block Common Exploits
   - ✅ Websockets Support

3. **SSL Tab**:
   - ✅ Request a new SSL Certificate
   - ✅ Force SSL
   - ✅ HTTP/2 Support
   - Email: your-email@example.com
   - ✅ I Agree to the Let's Encrypt Terms of Service

4. **Advanced Tab** (Custom Nginx Configuration):
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

### SSL Certificate Management

- **Automatic Renewal**: NPM automatically renews Let's Encrypt certificates
- **Custom Certificates**: You can upload your own certificates via the SSL Certificates section
- **View Certificates**: Check certificate status and expiry dates in the SSL Certificates menu

### Benefits of NPM

- ✅ **User-Friendly Interface**: No need to edit nginx config files manually
- ✅ **Automatic SSL**: Built-in Let's Encrypt integration with auto-renewal
- ✅ **Access Lists**: Create IP whitelists/blacklists for added security
- ✅ **Custom Locations**: Add custom nginx configurations per proxy host
- ✅ **Streams**: Support for TCP/UDP stream forwarding
- ✅ **404 Hosts**: Custom 404 error pages

## 🔒 Security Features

- JWT-based authentication
- CORS protection with django-cors-headers
- SSL/TLS termination at Nginx Proxy Manager
- Redis password authentication
- PostgreSQL password authentication
- Environment variable-based secrets management
- NPM Access Lists for IP-based restrictions

## 📚 API Endpoints

The API is served under `/crm-api/` prefix:

- `/crm-api/auth/` - Authentication endpoints (Djoser)
- `/crm-api/conversations/` - Message and contact management
- `/crm-api/flows/` - Flow builder CRUD operations
- `/crm-api/customer-data/` - Customer profiles and wallets
- `/crm-api/media/` - Media file management
- `/crm-api/webhook/` - Meta webhook receiver

## 🧪 Development

### Backend Development
```bash
cd whatsappcrm_backend
pip install -r requirements.txt
python manage.py runserver
```

### Frontend Development
```bash
cd whatsapp-crm-frontend
npm install
npm run dev
```

### Running Tests
```bash
# Backend tests
docker-compose exec backend python manage.py test

# Frontend linting
cd whatsapp-crm-frontend && npm run lint
```

## 📦 Production Deployment

1. Update `.env` with production values
2. Run `docker-compose up -d --build`
3. Access Nginx Proxy Manager UI at http://your-server-ip:81
4. Change default admin credentials immediately
5. Configure proxy hosts for your domain(s) in NPM
6. Enable SSL certificates via Let's Encrypt (built into NPM)
7. SSL certificates are automatically renewed by NPM

**Note**: With Nginx Proxy Manager, you no longer need to manually configure SSL certificates or nginx configuration files. Everything is managed through the web UI.

### Static Files

The backend automatically collects and serves static files using WhiteNoise. When the backend container starts:
1. Database migrations are applied
2. Static files are collected with `collectstatic` (creating the manifest file)
3. Gunicorn starts with WhiteNoise middleware serving compressed static files

**Important**: Static files should NOT be committed to git. They are generated at container startup and stored in a Docker volume. The `.gitignore` file excludes the `staticfiles/` directory.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is proprietary software. All rights reserved.

## 📞 Support

For support and inquiries, please contact the development team.
