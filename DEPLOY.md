# Deploying WhatsApp CRM / BetBlitz

This guide walks you through a first-time deployment using the interactive
`deploy.sh` helper, which builds your `.env`, installs Docker if needed, starts
the stack, and runs first-time setup.

- **Quick path:** [1. Prerequisites](#1-prerequisites) → [2. Run the deploy script](#2-run-the-deploy-script) → [4. Post-deploy configuration](#4-post-deploy-configuration).
- Everything below assumes you are in the repository root.

---

## 1. Prerequisites

- A **Linux** (Ubuntu/Debian/RHEL/Alpine) or **macOS** host.
- A user with **`sudo`** (or run as `root`) — needed only if Docker must be installed.
- **Outbound internet** access (to pull images and, optionally, install Docker).
- Free TCP ports **8000** (backend), **5432** (Postgres), **6379** (Redis). The
  script warns if any are already in use.
- **You do _not_ need to install Docker yourself** — `deploy.sh` will offer to
  install Docker Engine + Compose for you. (Bring your own Docker with
  `--no-install` if you prefer.)

You **will** need, to make the bot fully functional (can be added after deploy):

- A **Meta WhatsApp** app: access token, phone-number ID, and a webhook verify token.
- An **API-Football v3** key (https://www.api-football.com/) for match/odds data.
- Optional: **Paynow** credentials (deposits/withdrawals), a **Gemini** API key
  (assistant phrasing), and an approved **settlement template** name.

---

## 2. Run the deploy script

```bash
git clone https://github.com/morebnyemba/whatsappcrm.git
cd whatsappcrm
./deploy.sh
```

The script is **safe to cancel** at any time (press `Ctrl-C`, or type `cancel`
at any prompt) — nothing is written until you confirm.

It walks through, in order:

1. **Environment** — production vs development, and your public domain (from
   which it derives `ALLOWED_HOSTS`, CSRF/CORS origins and `SITE_URL`).
2. **Django secret** — auto-generated (accept, type your own, or type `gen`).
3. **Database**, **Redis/Celery** — passwords auto-generated; the Celery broker
   URL is wired to the Redis password for you.
4. **Sessions/tokens**, **Football API keys**, **WhatsApp app secret**,
   **AI / notifications / responsible-gambling** settings.
5. **Review** (secrets masked) → confirm → writes `.env` (permissions `600`,
   backing up any existing one).
6. **Preflight + Docker** — installs Docker/Compose if missing and starts the
   daemon, then offers to `docker compose up -d --build`.
7. **First-time setup** — migrations, WhatsApp flow definitions, football
   leagues, and a Django admin superuser (each step is confirmed).

Every value is validated and re-prompted until valid.

### Flags

| Flag | Purpose |
|------|---------|
| `-y`, `--yes` | Non-interactive: accept defaults / existing values, generate missing secrets, proceed. |
| `--no-start` | Only write `.env`; don't touch Docker. |
| `--no-install` | Never install anything; only check prerequisites. |
| `--regenerate` | Force new secrets (default is to keep existing ones on re-run). |
| `--env-file PATH` | Write to `PATH` instead of `./.env`. |
| `-h`, `--help` | Show help. |

**Re-running** `deploy.sh` pre-fills every answer from your existing `.env` and
**keeps your existing secrets** (no churn) — handy for changing one value.
Use `--regenerate` when you deliberately want to rotate them.

Environment overrides: `DOCKER_START_WAIT` (daemon-ready attempts, default 30).

---

## 3. What gets started

`docker compose` brings up:

| Service | Role |
|---------|------|
| `db` | PostgreSQL 15 |
| `redis` | Redis 7 (password-protected) — Celery broker/result backend |
| `backend` | Django app (Gunicorn/Daphne) on port 8000 |
| `celery_io_worker` | Celery worker, `celery` queue (general I/O, gevent) |
| `celery_football_io_worker` | Celery worker, `football_io` queue (API-Football odds/events/scores/settlement, gevent) |
| `celery_cpu_worker` | Celery worker, `cpu_heavy` queue (fixture outcome predictions only — genuinely CPU-bound) |
| `celery_beat` | Celery beat scheduler (django-celery-beat) |
| `frontend` | Admin CRM (React/Vite) — served at `admin.<domain>` |
| `player_portal` | Player portal (React/Vite) — served at `app.<domain>` |
| `nginx_proxy` | Reverse proxy / TLS / media — routes the three subdomains |

Manage it:

```bash
docker compose ps          # status
docker compose logs -f backend
docker compose restart backend
docker compose down         # stop (add -v to also drop volumes/data)
```

---

## 3b. Domains & surfaces

There are **two separate web frontends** and one API, on three subdomains:

| Subdomain | Serves | Who |
|-----------|--------|-----|
| `app.<domain>` | **Player portal** (their matches, tickets, wallet, profile) | Players |
| `admin.<domain>` | **Admin CRM** (flows, contacts, conversations, media, settings) | Staff |
| `api.<domain>` | Django backend (`/crm-api/…`) | both frontends |

- The backend enforces this split: CRM/admin endpoints require **staff** (`is_staff`);
  the betting endpoints (`/crm-api/football/…`) are **player-scoped** to the
  requesting user. A player token cannot read CRM data.
- **Admin login** (`admin.<domain>`): staff username + password (create with
  `createsuperuser`).
- **Player login** (`app.<domain>`): **WhatsApp one-time code** — players have no
  password. The portal calls:
  - `POST /crm-api/auth/player/request-otp/` `{ "phone": "2637…" }` → code sent on WhatsApp.
  - `POST /crm-api/auth/player/verify-otp/` `{ "phone": "2637…", "code": "123456" }` → JWT.

`deploy.sh` (production mode) derives `ALLOWED_HOSTS` (`api.<domain>`),
`CORS_ALLOWED_ORIGINS` (`app.`/`admin.`), `CSRF_TRUSTED_ORIGINS` and `SITE_URL`
(`https://api.<domain>`) from the base domain you enter.

**The stack serves everything itself — no manual frontend build.** Both portals
are built inside the Docker stack (`player-portal` and `whatsapp-crm-frontend`
services) with their API base baked in from `SITE_URL` (`https://api.<domain>`),
and the bundled `nginx_proxy` terminates TLS and routes each subdomain:

- `app.<domain>` → player portal container
- `admin.<domain>` → admin CRM container
- `api.<domain>` → Django backend (`/crm-api/…`, `/static/`, `/media/`, Meta webhook & Flow endpoint)
- apex + `www` → redirect to `app.<domain>`

`deploy.sh` renders `nginx_proxy/nginx.conf` from `nginx_proxy/nginx.conf.template`
for your domain automatically.

**DNS:** create **A records** pointing all names at the host — `api.`, `app.`,
`admin.` (required), plus the apex and `www` (optional). See the DNS table in
the README/quickstart.

### TLS / SSL (Let's Encrypt, automated)

When you run `deploy.sh` in production with a domain, it offers to obtain
Let's Encrypt certificates:

1. Renders the Nginx config and drops a **temporary self-signed cert** so Nginx
   can start on `:443`.
2. Brings up the stack, then runs **certbot** (webroot, in a one-shot
   `certbot/certbot` container) to issue **one SAN certificate** covering
   `api.`, `app.`, `admin.`, apex and `www`.
3. Reloads Nginx and installs a **daily auto-renewal** cron
   (`/etc/cron.d/betblits-certbot-renew`) that renews and reloads Nginx.

Prerequisites at issuance time: the three subdomains must already resolve to the
host, and ports **80** and **443** must be open. Use the **STAGING** option first
(the script asks) to verify DNS without burning Let's Encrypt rate limits, then
re-run with `--regenerate` for the real certificate. If certbot fails, the stack
keeps serving with the temporary cert; fix DNS/ports and re-run `./deploy.sh`.

To re-run just the SSL step later, run `./deploy.sh` again — it detects an
existing valid certificate and skips issuance unless you pass `--regenerate`.

## 4. Post-deploy configuration

These are done once in the **Django admin** (`/admin/`, log in with the
superuser you created):

1. **WhatsApp (MetaAppConfig)** — add your Meta **access token**, **phone-number
   ID**, **verify token**, and mark it active. Then point the Meta webhook at:

   ```
   https://api.<domain>/crm-api/meta/webhook/
   ```

   (Use the same verify token you set in MetaAppConfig.) The webhook signature is
   verified with `WHATSAPP_APP_SECRET` from `.env`.

2. **Paynow** (optional) — add integration ID/key in the admin if you accept
   real-money deposits/withdrawals. IPN endpoint:
   `https://api.<domain>/crm-api/customer-data/paynow/ipn/`.

3. **Schedule the football tasks** — under **Periodic Tasks** (django-celery-beat)
   create schedules for:

   | Task | Suggested cadence |
   |------|-------------------|
   | `football_data_app.run_apifootball_full_update` (or `run_api_football_v3_full_update_task`) | every 10–15 min |
   | `football_data_app.run_score_and_settlement_task` (or `..._v3_task`) | every 5 min |
   | `football_data_app.generate_fixture_predictions` | hourly |

   > Odds are fetched in **bulk per league-day** (not per fixture), so these are
   > quota-friendly; the built-in staleness gate avoids redundant refreshes.

4. **Load leagues** (if you skipped it in the script):

   ```bash
   docker compose exec backend python manage.py football_league_setup_v3
   ```

5. **Publish the WhatsApp UI Flows** (login, register, and the native **betting**
   Flow) to Meta. Requires a MetaAppConfig with a `flow_private_key_pem` set:

   ```bash
   docker compose exec backend python manage.py load_flow_definitions   # loads flow JSON into the DB
   docker compose exec backend python manage.py sync_whatsapp_flows      # creates/updates/publishes them on Meta
   ```

   Once the `bet_whatsapp` Flow is published, players can open the native
   browse-and-bet Flow by sending **`bet form`** (or `place bet`) on WhatsApp;
   if it isn't published yet, that falls back to the conversational betting flow
   (`bet`). The Flow's data-exchange endpoint is
   `…/crm-api/meta/flow-endpoint/<phone_number_id>/`.

---

## 5. Common management commands

Run inside the backend container (`docker compose exec backend python manage.py …`):

```bash
migrate                        # apply DB migrations
load_flow_definitions          # (re)load WhatsApp conversational flows
football_league_setup_v3       # fetch leagues from API-Football v3
createsuperuser                # add an admin user
update_affiliate_percentages   # one-off: bump an existing Agent Program's commission % off its old 5% default (see below)
```

---

## 5b. Agent / Affiliate Program

Configured in Django admin under **Referrals → Agent Program Settings** (a
singleton). All three percentages default to **25%** for a fresh deploy:

| Setting | Applies when | Effect |
|---|---|---|
| `bonus_percentage_each` | A referred user's first completed deposit | Both the referred user **and** the referring agent (if `is_agent=True`) are credited this % of the deposit. |
| `agent_commission_percentage` | A referred user's bet ticket is **lost** | The agent's wallet is credited this % of the stake. |
| `agent_win_deduction_percentage` | A referred user's bet ticket is **won** | The agent's wallet is debited this % of the winnings — unconditionally, so it can go negative. |

Only **admin-designated agents** (`ReferralProfile.is_agent=True`) earn/owe
any of these — a plain referral link with no agent flag gets the referred
user their own deposit bonus only. All three flows are recorded (`AgentEarning`,
`AgentDeduction`, `AgentDepositBonus`) and visible per-agent in admin
(`Total Earnings` / `Total Deductions` / `Net Earnings`) and via the agent's
own WhatsApp "My Earnings" screen.

**Upgrading an existing deployment:** `agent_commission_percentage` used to
default to 5%. Since this repo's migrations aren't committed (regenerated
fresh per deploy — see `.gitignore`), a schema `makemigrations` won't touch
already-stored data. After deploying, run:

```bash
docker compose exec backend python manage.py update_affiliate_percentages
```

It bumps `agent_commission_percentage` to 25% only if it's still sitting at
the old 5% default (leaves a deliberately-customised value alone); pass
`--force` to set it to 25% regardless.

---

## 6. Responsible gambling & compliance

Betting is gated at placement and deposit:

- **Age**: a user must have a date of birth on file and be ≥ `RG_MIN_AGE`
  (default 18) before their first bet — enforced fail-closed.
- **KYC**: set `RG_REQUIRE_KYC=True` to require verification before betting
  (mark users verified in the admin under *Responsible Gambling Controls*).
- **Self-exclusion / limits**: users manage these in WhatsApp via
  *bet → 🛡️ Safer gambling*; staff can set them in the admin.

---

## 7. Security notes

- `.env` is git-ignored and written with `600` permissions. **Never commit it.**
- **Rotate any secret that is ever exposed** (Django key, DB/Redis passwords,
  WhatsApp app secret, API keys). `deploy.sh --regenerate` rotates the
  auto-generated ones; provider keys are rotated in each provider's console.
- In production, keep `DJANGO_DEBUG=False` and restrict `ALLOWED_HOSTS`.
- Consider closing the public `5432`/`6379` port mappings in `docker-compose.yml`
  once everything talks over the internal Docker network.

---

## 8. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Docker daemon is not reachable` | Start Docker (`sudo systemctl start docker`) and re-run, or re-run after logging out/in so your `docker` group membership applies. |
| `port … already in use` | Stop whatever holds 8000/5432/6379, or change the mapping in `docker-compose.yml`. |
| Backend not ready / migrations fail | `docker compose logs backend`; ensure `db` and `redis` are healthy (`docker compose ps`). |
| No matches/odds in WhatsApp | Confirm `API_FOOTBALL_V3_KEY` is set, run `football_league_setup_v3`, and schedule the football tasks (section 4). |
| Settlement notice not delivered | Plain-text notices only send within WhatsApp's 24h window; set `BET_SETTLEMENT_TEMPLATE_NAME` to an approved template for later delivery. |

For a config-only run (no Docker) use `./deploy.sh --no-start`, then start the
stack yourself with `docker compose up -d --build`.
