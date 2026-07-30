#!/usr/bin/env bash
#
# WhatsApp CRM / BetBlitz — interactive deployment helper.
#
# Walks you through creating the root .env (auto-generating secrets), then
# optionally builds and starts the Docker stack and runs first-time setup
# (migrations, flow definitions, football leagues, admin user).
#
# Nothing is written until you confirm at the end, so you can cancel at any
# time: press Ctrl-C, or type "cancel" (or "q") at any prompt.
#
# Usage:  ./deploy.sh
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'
  YLW=$'\033[33m'; BLU=$'\033[36m'; RST=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; BLU=""; RST=""
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

say()     { printf '%s\n' "$*"; }
title()   { printf '\n%s%s%s\n' "$BOLD$BLU" "$*" "$RST"; }
info()    { printf '%s%s%s\n' "$DIM" "$*" "$RST"; }
ok()      { printf '%s✓ %s%s\n' "$GRN" "$*" "$RST"; }
warn()    { printf '%s! %s%s\n' "$YLW" "$*" "$RST"; }
err()     { printf '%s✗ %s%s\n' "$RED" "$*" "$RST" >&2; }

abort() {
  printf '\n%s✗ Cancelled. No changes were made.%s\n' "$RED" "$RST" >&2
  exit 130
}
trap abort INT TERM

# Treat "cancel"/"q"/"quit" typed at any prompt as an abort.
_check_cancel() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    cancel|quit|q) abort ;;
  esac
}

# ---------------------------------------------------------------------------
# Prompt helpers.  Answers are collected into the ANSWERS array and only
# written out after a final confirmation.
# ---------------------------------------------------------------------------
declare -A ANSWERS

# ask VAR "Prompt" "default"   -> free text with a default (Enter accepts it)
ask() {
  local var="$1" prompt="$2" default="${3:-}" reply
  if [ -n "$default" ]; then
    read -r -p "$(printf '%s%s%s [%s]: ' "$BOLD" "$prompt" "$RST" "$default")" reply || abort
  else
    read -r -p "$(printf '%s%s%s: ' "$BOLD" "$prompt" "$RST")" reply || abort
  fi
  _check_cancel "$reply"
  ANSWERS[$var]="${reply:-$default}"
}

# ask_secret VAR "Prompt"      -> default is a freshly generated secret; the
#                                 user may accept it, type their own, or type
#                                 "gen" to regenerate.
ask_secret() {
  local var="$1" prompt="$2" gen reply
  gen="$(gen_secret)"
  while true; do
    read -r -p "$(printf '%s%s%s [auto-generated, Enter to accept / type value / "gen" for a new one]: ' "$BOLD" "$prompt" "$RST")" reply || abort
    _check_cancel "$reply"
    case "$reply" in
      "")    ANSWERS[$var]="$gen"; info "  → using generated value (…${gen: -6})"; break ;;
      gen)   gen="$(gen_secret)"; info "  → regenerated (…${gen: -6})"; ;;
      *)     ANSWERS[$var]="$reply"; break ;;
    esac
  done
}

# yes/no; returns 0 for yes
confirm() {
  local prompt="$1" default="${2:-y}" reply hint
  [ "$default" = "y" ] && hint="Y/n" || hint="y/N"
  read -r -p "$(printf '%s%s%s [%s]: ' "$BOLD" "$prompt" "$RST" "$hint")" reply || abort
  _check_cancel "$reply"
  reply="${reply:-$default}"
  case "$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')" in
    y|yes) return 0 ;;
    *)     return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Secret generation.  Prefers python's secrets module, falls back to openssl.
# Produces a URL/shell-safe token (A-Za-z0-9 plus _-.), so it is safe to write
# unquoted in .env and to embed in a redis:// URL.
# ---------------------------------------------------------------------------
gen_secret() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n'
  else
    # Last resort: /dev/urandom
    LC_ALL=C tr -dc 'A-Za-z0-9_-' </dev/urandom | head -c 64; echo
  fi
}

# Alnum-only secret (safe inside URLs without escaping) for passwords.
gen_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 48; echo
  fi
}

# ---------------------------------------------------------------------------
# Docker compose command detection
# ---------------------------------------------------------------------------
compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

# ===========================================================================
# 0. Intro
# ===========================================================================
clear 2>/dev/null || true
title "WhatsApp CRM / BetBlitz — Deployment Setup"
info "This will help you create the .env file and (optionally) start the stack."
info "Secrets are auto-generated. Press Ctrl-C or type 'cancel' at any prompt to abort."
say ""

if [ -f "$ENV_FILE" ]; then
  warn "An existing .env was found at $ENV_FILE"
  if ! confirm "Continue and (after confirmation) back it up and replace it?" "n"; then
    abort
  fi
fi

# ===========================================================================
# 1. Environment mode & public address
# ===========================================================================
title "1) Environment"
MODE="production"
if confirm "Is this a PRODUCTION deployment? (No = development)" "y"; then
  MODE="production"; ANSWERS[DJANGO_DEBUG]="False"
else
  MODE="development"; ANSWERS[DJANGO_DEBUG]="True"
fi
info "Mode: $MODE (DJANGO_DEBUG=${ANSWERS[DJANGO_DEBUG]})"

if [ "$MODE" = "production" ]; then
  ask DOMAIN "Public domain (e.g. betblitz.co.zw, no scheme)" ""
  DOMAIN="${ANSWERS[DOMAIN]}"
  if [ -n "$DOMAIN" ]; then
    ANSWERS[SITE_URL]="https://$DOMAIN"
    ANSWERS[DJANGO_ALLOWED_HOSTS]="$DOMAIN,www.$DOMAIN"
    ANSWERS[CSRF_TRUSTED_ORIGINS]="https://$DOMAIN,https://www.$DOMAIN"
    ANSWERS[CORS_ALLOWED_ORIGINS]="https://$DOMAIN,https://www.$DOMAIN"
  fi
fi
# Fill any gaps / dev defaults, letting the user adjust.
ask SITE_URL "Site URL (absolute, used for media links)" "${ANSWERS[SITE_URL]:-http://localhost:8000}"
ask DJANGO_ALLOWED_HOSTS "Allowed hosts (comma-separated)" "${ANSWERS[DJANGO_ALLOWED_HOSTS]:-localhost,127.0.0.1}"
ask CSRF_TRUSTED_ORIGINS "CSRF trusted origins" "${ANSWERS[CSRF_TRUSTED_ORIGINS]:-http://localhost:5173,http://127.0.0.1:5173}"
ask CORS_ALLOWED_ORIGINS "CORS allowed origins" "${ANSWERS[CORS_ALLOWED_ORIGINS]:-http://localhost:5173,http://127.0.0.1:5173}"
ANSWERS[CORS_ALLOW_CREDENTIALS]="True"

# ===========================================================================
# 2. Django secret
# ===========================================================================
title "2) Django secret key"
ask_secret DJANGO_SECRET_KEY "DJANGO_SECRET_KEY"

# ===========================================================================
# 3. Database
# ===========================================================================
title "3) PostgreSQL database"
ANSWERS[DB_ENGINE]="django.db.backends.postgresql"
ask DB_NAME "Database name" "whatsapp_crm"
ask DB_USER "Database user" "crm_user"
ask_secret DB_PASSWORD_INPUT "DB password"
# Prefer an alnum password if the generated urlsafe token slipped in special chars.
if printf '%s' "${ANSWERS[DB_PASSWORD_INPUT]}" | grep -q '[^A-Za-z0-9]'; then
  ANSWERS[DB_PASSWORD]="$(gen_password)"
  info "  → normalised DB password to URL-safe characters"
else
  ANSWERS[DB_PASSWORD]="${ANSWERS[DB_PASSWORD_INPUT]}"
fi
unset 'ANSWERS[DB_PASSWORD_INPUT]'
ask DB_HOST "Database host (use 'db' for the docker stack)" "db"
ask DB_PORT "Database port" "5432"

# ===========================================================================
# 4. Redis / Celery
# ===========================================================================
title "4) Redis & Celery"
RPW="$(gen_password)"
read -r -p "$(printf '%sRedis password%s [auto-generated, Enter to accept / type value]: ' "$BOLD" "$RST")" _rpw || abort
_check_cancel "${_rpw:-}"
[ -n "${_rpw:-}" ] && RPW="$_rpw"
ANSWERS[REDIS_PASSWORD]="$RPW"
info "  → redis password (…${RPW: -6})"
ANSWERS[CELERY_BROKER_URL]="redis://:${RPW}@redis:6379/0"
ask CELERY_WORKER_CONCURRENCY "Celery IO worker concurrency" "20"

# ===========================================================================
# 5. Sessions / tokens
# ===========================================================================
title "5) Sessions & tokens"
ask JWT_ACCESS_TOKEN_LIFETIME_MINUTES "JWT access token lifetime (minutes)" "60"
ask JWT_REFRESH_TOKEN_LIFETIME_DAYS "JWT refresh token lifetime (days)" "7"
ask SESSION_IDLE_TIMEOUT_MINUTES "WhatsApp flow session idle timeout (minutes)" "5"
ask CONVERSATION_EXPIRY_DAYS "Conversation retention (days)" "60"

# ===========================================================================
# 6. Football data provider
# ===========================================================================
title "6) Football data (API-Football v3 recommended)"
info "Get a key at https://www.api-football.com/. Leave blank to configure later."
ask API_FOOTBALL_V3_KEY "API_FOOTBALL_V3_KEY" ""
ask API_FOOTBALL_V3_CURRENT_SEASON "Current season year" "2024"
ask API_FOOTBALL_MAX_REQUESTS_PER_MINUTE "Max API requests/minute" "300"
if confirm "Configure legacy/backup providers (apifootball.com, The Odds API)?" "n"; then
  ask API_FOOTBALL_KEY "API_FOOTBALL_KEY (apifootball.com)" ""
  ask FOOTBALL_DATA_API_KEY "FOOTBALL_DATA_API_KEY" ""
  ask THE_ODDS_API_KEY "THE_ODDS_API_KEY" ""
else
  ANSWERS[API_FOOTBALL_KEY]=""; ANSWERS[FOOTBALL_DATA_API_KEY]=""; ANSWERS[THE_ODDS_API_KEY]=""
fi

# ===========================================================================
# 7. WhatsApp / Meta
# ===========================================================================
title "7) WhatsApp / Meta"
info "The Meta access token & phone-number ID are configured in the Django admin"
info "after deploy (MetaAppConfig). Only the webhook app secret lives in .env."
ask WHATSAPP_APP_SECRET "WHATSAPP_APP_SECRET (webhook signature verification)" ""

# ===========================================================================
# 8. AI, notifications & responsible gambling
# ===========================================================================
title "8) AI, notifications & responsible gambling"
ask GEMINI_API_KEY "GEMINI_API_KEY (optional; assistant works without it)" ""
ask GEMINI_MODEL "Gemini model" "gemini-1.5-flash"
ask BET_SETTLEMENT_TEMPLATE_NAME "Settlement WhatsApp template name (blank = plain text)" ""
ask BET_SETTLEMENT_TEMPLATE_LANG "Settlement template language" "en_US"
ask RG_MIN_AGE "Minimum betting age" "18"
if confirm "Require KYC verification before a first bet?" "n"; then
  ANSWERS[RG_REQUIRE_KYC]="True"
else
  ANSWERS[RG_REQUIRE_KYC]="False"
fi

# ===========================================================================
# 9. Review & write
# ===========================================================================
title "9) Review"
info "The following .env will be written (secrets masked):"
say ""
_mask() { case "$1" in *SECRET*|*PASSWORD*|*_KEY|*BROKER_URL) printf '********'; ;; *) printf '%s' "$2";; esac; }
for k in DJANGO_DEBUG SITE_URL DJANGO_ALLOWED_HOSTS DB_NAME DB_USER DB_HOST DB_PORT \
         DJANGO_SECRET_KEY DB_PASSWORD REDIS_PASSWORD API_FOOTBALL_V3_KEY GEMINI_API_KEY \
         RG_MIN_AGE RG_REQUIRE_KYC; do
  printf '  %-28s = %s\n' "$k" "$(_mask "$k" "${ANSWERS[$k]:-}")"
done
say ""
if ! confirm "Write this configuration to .env now?" "y"; then
  abort
fi

# Build the .env content
write_env() {
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat <<EOF
# Generated by deploy.sh on $ts
# Do NOT commit this file. Rotate any secret that leaks.

# --- Django ---
DJANGO_SECRET_KEY=${ANSWERS[DJANGO_SECRET_KEY]}
DJANGO_DEBUG=${ANSWERS[DJANGO_DEBUG]}
DJANGO_ALLOWED_HOSTS=${ANSWERS[DJANGO_ALLOWED_HOSTS]}
CSRF_TRUSTED_ORIGINS=${ANSWERS[CSRF_TRUSTED_ORIGINS]}
SITE_URL=${ANSWERS[SITE_URL]}

# --- CORS ---
CORS_ALLOWED_ORIGINS=${ANSWERS[CORS_ALLOWED_ORIGINS]}
CORS_ALLOW_CREDENTIALS=${ANSWERS[CORS_ALLOW_CREDENTIALS]}

# --- Database ---
DB_ENGINE=${ANSWERS[DB_ENGINE]}
DB_NAME=${ANSWERS[DB_NAME]}
DB_USER=${ANSWERS[DB_USER]}
DB_PASSWORD=${ANSWERS[DB_PASSWORD]}
DB_HOST=${ANSWERS[DB_HOST]}
DB_PORT=${ANSWERS[DB_PORT]}

# --- Redis / Celery ---
REDIS_PASSWORD=${ANSWERS[REDIS_PASSWORD]}
CELERY_BROKER_URL=${ANSWERS[CELERY_BROKER_URL]}
CELERY_WORKER_CONCURRENCY=${ANSWERS[CELERY_WORKER_CONCURRENCY]}

# --- Auth / sessions ---
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=${ANSWERS[JWT_ACCESS_TOKEN_LIFETIME_MINUTES]}
JWT_REFRESH_TOKEN_LIFETIME_DAYS=${ANSWERS[JWT_REFRESH_TOKEN_LIFETIME_DAYS]}
SESSION_IDLE_TIMEOUT_MINUTES=${ANSWERS[SESSION_IDLE_TIMEOUT_MINUTES]}
CONVERSATION_EXPIRY_DAYS=${ANSWERS[CONVERSATION_EXPIRY_DAYS]}

# --- Football data ---
API_FOOTBALL_V3_KEY=${ANSWERS[API_FOOTBALL_V3_KEY]}
API_FOOTBALL_V3_CURRENT_SEASON=${ANSWERS[API_FOOTBALL_V3_CURRENT_SEASON]}
API_FOOTBALL_MAX_REQUESTS_PER_MINUTE=${ANSWERS[API_FOOTBALL_MAX_REQUESTS_PER_MINUTE]}
API_FOOTBALL_KEY=${ANSWERS[API_FOOTBALL_KEY]}
FOOTBALL_DATA_API_KEY=${ANSWERS[FOOTBALL_DATA_API_KEY]}
THE_ODDS_API_KEY=${ANSWERS[THE_ODDS_API_KEY]}

# --- WhatsApp / Meta ---
WHATSAPP_APP_SECRET=${ANSWERS[WHATSAPP_APP_SECRET]}

# --- AI assistant ---
GEMINI_API_KEY=${ANSWERS[GEMINI_API_KEY]}
GEMINI_MODEL=${ANSWERS[GEMINI_MODEL]}

# --- Bet settlement notifications ---
BET_SETTLEMENT_TEMPLATE_NAME=${ANSWERS[BET_SETTLEMENT_TEMPLATE_NAME]}
BET_SETTLEMENT_TEMPLATE_LANG=${ANSWERS[BET_SETTLEMENT_TEMPLATE_LANG]}

# --- Responsible gambling ---
RG_MIN_AGE=${ANSWERS[RG_MIN_AGE]}
RG_REQUIRE_KYC=${ANSWERS[RG_REQUIRE_KYC]}
EOF
}

if [ -f "$ENV_FILE" ]; then
  backup="$ENV_FILE.bak.$(date -u +%Y%m%d%H%M%S)"
  cp "$ENV_FILE" "$backup"
  ok "Backed up existing .env → $(basename "$backup")"
fi
umask 077
write_env > "$ENV_FILE"
chmod 600 "$ENV_FILE"
ok "Wrote $ENV_FILE (permissions 600)"

# ===========================================================================
# 10. Optional: build & run the stack
# ===========================================================================
title "10) Start the stack"
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker not found. Install Docker, then run: cd $SCRIPT_DIR && docker compose up -d --build"
  exit 0
fi

if ! confirm "Build and start the Docker stack now (docker compose up -d --build)?" "y"; then
  say ""
  ok "Configuration complete. Start it later with:"
  say "    cd $SCRIPT_DIR && docker compose up -d --build"
  exit 0
fi

info "Building and starting containers…"
if ! ( cd "$SCRIPT_DIR" && compose up -d --build ); then
  err "docker compose failed (see output above). Your .env is saved; fix the issue and run:"
  say "    cd $SCRIPT_DIR && docker compose up -d --build"
  exit 1
fi
ok "Containers started."

# Wait for the backend to be responsive before running management commands.
info "Waiting for the backend container to be ready…"
for _ in $(seq 1 30); do
  if ( cd "$SCRIPT_DIR" && compose exec -T backend python manage.py showmigrations >/dev/null 2>&1 ); then
    break
  fi
  sleep 3
done

run_mgmt() { ( cd "$SCRIPT_DIR" && compose exec -T backend python manage.py "$@" ); }

title "11) First-time setup"
if confirm "Apply database migrations (makemigrations + migrate)?" "y"; then
  run_mgmt makemigrations || warn "makemigrations reported an issue (may be nothing to make)."
  run_mgmt migrate && ok "Migrations applied."
fi

if confirm "Load WhatsApp conversational flow definitions?" "y"; then
  run_mgmt load_flow_definitions && ok "Flow definitions loaded."
fi

if [ -n "${ANSWERS[API_FOOTBALL_V3_KEY]}" ] && confirm "Fetch football leagues from API-Football v3 now?" "y"; then
  run_mgmt football_league_setup_v3 && ok "Leagues initialised." || warn "League setup failed; check the API key."
fi

if confirm "Create a Django admin superuser now?" "y"; then
  ( cd "$SCRIPT_DIR" && compose exec backend python manage.py createsuperuser ) || warn "Superuser creation skipped/failed."
fi

# ===========================================================================
# Done
# ===========================================================================
title "Done 🎉"
ok "BetBlitz is deployed."
say ""
info "Next steps:"
say "  • In the Django admin, add a MetaAppConfig (WhatsApp access token, phone-number ID, verify token)."
say "  • Configure the Meta webhook to point at  ${ANSWERS[SITE_URL]}/crm-api/meta/webhook/"
say "  • If you use Paynow, add its integration credentials in the admin."
say "  • Schedule the football update & score/settlement tasks (django-celery-beat, in the admin)."
say ""
info "Manage the stack with:  cd $SCRIPT_DIR && docker compose ps | logs | down"
