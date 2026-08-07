#!/usr/bin/env bash
#
# WhatsApp CRM / BetBlitz — deployment helper.
#
# Interactively builds the root .env (auto-generating secrets), validates your
# input, then optionally builds and starts the Docker stack and runs first-time
# setup (migrations, flow definitions, football leagues, admin user).
#
# Highlights:
#   • Preflight checks, and INSTALLS missing prerequisites (Docker Engine +
#     Compose) on Linux/macOS with your consent, then starts the daemon.
#   • Every value is validated; you are re-prompted until it is valid.
#   • Re-running pre-fills answers from your existing .env (edit-in-place).
#   • Secrets are auto-generated; manual entry is hidden.
#   • Cancel any time with Ctrl-C or by typing "cancel"/"q"; nothing is written
#     until you confirm.
#
# Usage:
#   ./deploy.sh [options]
#     -y, --yes            Non-interactive: accept defaults / existing values,
#                          generate any missing secrets, and proceed.
#         --no-start       Configure .env only; do not touch Docker.
#         --no-install     Do not install anything; only check prerequisites.
#         --regenerate     Force-generate new secrets (ignore existing ones).
#         --env-file PATH  Write to PATH instead of ./.env.
#     -h, --help           Show this help and exit.
#
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'
  YLW=$'\033[33m'; BLU=$'\033[36m'; RST=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; BLU=""; RST=""
fi
say()   { printf '%s\n' "$*"; }
title() { printf '\n%s%s%s\n' "$BOLD$BLU" "$*" "$RST"; }
info()  { printf '%s%s%s\n' "$DIM" "$*" "$RST"; }
ok()    { printf '%s✓ %s%s\n' "$GRN" "$*" "$RST"; }
warn()  { printf '%s! %s%s\n' "$YLW" "$*" "$RST"; }
err()   { printf '%s✗ %s%s\n' "$RED" "$*" "$RST" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ASSUME_YES=0
DO_START=1
REGEN=0
DO_INSTALL=1
DOCKER_SUDO=""
DO_SSL=0
SSL_EMAIL=""
SSL_STAGING=0

abort() { printf '\n%s✗ Cancelled. No changes were made.%s\n' "$RED" "$RST" >&2; exit 130; }
on_err() { local rc=$?; err "Unexpected failure (exit $rc) at line ${1:-?}. Existing files were left as-is (any backup is noted above)."; exit "$rc"; }
trap abort INT TERM
trap 'on_err "$LINENO"' ERR

usage() { sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)        ASSUME_YES=1 ;;
    --no-start)      DO_START=0 ;;
    --no-install)    DO_INSTALL=0 ;;
    --regenerate)    REGEN=1 ;;
    --env-file)      shift; [ $# -gt 0 ] || { err "--env-file needs a path"; exit 2; }; ENV_FILE="$1" ;;
    --env-file=*)    ENV_FILE="${1#*=}" ;;
    -h|--help)       usage ;;
    *)               err "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# Cancel handling for prompts
# ---------------------------------------------------------------------------
_check_cancel() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    cancel|quit|q) abort ;;
  esac
}

# ---------------------------------------------------------------------------
# Validators. Each prints an error to stderr and returns non-zero when invalid.
# ---------------------------------------------------------------------------
v_any()   { return 0; }
v_int()   { [[ "$1" =~ ^[0-9]+$ ]] || { err "  must be a whole number"; return 1; }; }
v_port()  { v_int "$1" && [ "$1" -ge 1 ] && [ "$1" -le 65535 ] || { err "  must be a port 1-65535"; return 1; }; }
v_age()   { v_int "$1" && [ "$1" -ge 18 ] && [ "$1" -le 100 ] || { err "  must be an age 18-100"; return 1; }; }
v_bool()  { case "$1" in True|False) return 0;; *) err "  must be True or False"; return 1;; esac; }
v_url()   { [[ "$1" =~ ^https?://[^[:space:]]+$ ]] || { err "  must be a URL starting with http:// or https://"; return 1; }; }
v_hosts() { [[ "$1" =~ ^[A-Za-z0-9._:*,-]+$ ]] || { err "  only letters, digits and . _ - : * , allowed (no spaces)"; return 1; }; }
v_origins() { [[ "$1" =~ ^https?://[^[:space:],]+(,https?://[^[:space:],]+)*$ ]] || { err "  comma-separated http(s) origins, no spaces"; return 1; }; }
v_domain() { [ -z "$1" ] || [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || { err "  invalid domain (no scheme, no path)"; return 1; }; }
# A value safe to write unquoted in .env (no whitespace, #, quotes, backslash, $).
v_safe()  { [ -z "$1" ] || [[ ! "$1" =~ [[:space:]\#\"\'\\\$\`] ]] || { err "  contains characters that aren't allowed here"; return 1; }; }
v_ident() { [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { err "  must start with a letter/underscore, then letters/digits/underscore"; return 1; }; }
v_email() { [ -z "$1" ] || [[ "$1" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || { err "  must be a valid email address, or blank"; return 1; }; }

# ---------------------------------------------------------------------------
# Secret generation (URL/shell-safe; passwords are alnum for use inside URLs).
# ---------------------------------------------------------------------------
gen_secret() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n'
  else
    LC_ALL=C tr -dc 'A-Za-z0-9_-' </dev/urandom | head -c 64; echo
  fi
}
gen_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 48; echo
  fi
}

# ---------------------------------------------------------------------------
# Answer store + existing-.env defaults
# ---------------------------------------------------------------------------
declare -A ANSWERS
declare -A EXISTING

load_existing() {
  [ -f "$ENV_FILE" ] || return 0
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue;; esac
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"; val="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"; key="${key%"${key##*[![:space:]]}"}"
    # strip one layer of surrounding quotes
    [[ "$val" == \"*\" || "$val" == \'*\' ]] && val="${val:1:${#val}-2}"
    EXISTING["$key"]="$val"
  done < "$ENV_FILE"
}

# Default for a var: existing value (unless --regenerate for secrets) else fallback.
_default_for() { local var="$1" fb="${2:-}"; if [ -n "${EXISTING[$var]:-}" ]; then printf '%s' "${EXISTING[$var]}"; else printf '%s' "$fb"; fi; }

# ---------------------------------------------------------------------------
# Prompts (validated, with re-prompt). Honour --yes (use default silently).
#   ask VAR "Prompt" "default" [validator]
# ---------------------------------------------------------------------------
ask() {
  local var="$1" prompt="$2" default="$3" validator="${4:-v_any}" reply
  default="$(_default_for "$var" "$default")"
  if [ "$ASSUME_YES" = 1 ]; then
    if ! "$validator" "$default" 2>/dev/null; then err "Default for $var ('$default') is invalid; fix with an interactive run."; exit 2; fi
    ANSWERS[$var]="$default"; return 0
  fi
  while true; do
    if [ -n "$default" ]; then
      read -r -p "$(printf '%s%s%s [%s]: ' "$BOLD" "$prompt" "$RST" "$default")" reply || abort
    else
      read -r -p "$(printf '%s%s%s: ' "$BOLD" "$prompt" "$RST")" reply || abort
    fi
    _check_cancel "$reply"
    reply="${reply:-$default}"
    if "$validator" "$reply"; then ANSWERS[$var]="$reply"; return 0; fi
  done
}

# ask_secret VAR "Prompt" [validator]  — default is generated; manual entry hidden.
ask_secret() {
  local var="$1" prompt="$2" validator="${3:-v_safe}" gen reply existing
  existing="${EXISTING[$var]:-}"
  if [ -n "$existing" ] && [ "$REGEN" != 1 ]; then gen="$existing"; else gen="$(gen_secret)"; fi
  if [ "$ASSUME_YES" = 1 ]; then ANSWERS[$var]="$gen"; return 0; fi
  local hint="Enter=accept / type value / 'gen' for new"
  [ -n "$existing" ] && [ "$REGEN" != 1 ] && hint="Enter=keep existing / type value / 'gen' for new"
  while true; do
    read -r -s -p "$(printf '%s%s%s [%s]: ' "$BOLD" "$prompt" "$RST" "$hint")" reply || abort
    printf '\n'
    _check_cancel "$reply"
    case "$reply" in
      "")  ANSWERS[$var]="$gen"; info "  → using ${existing:+existing }value (…${gen: -6})"; return 0 ;;
      gen) gen="$(gen_secret)"; info "  → generated (…${gen: -6})" ;;
      *)   if "$validator" "$reply"; then ANSWERS[$var]="$reply"; return 0; fi ;;
    esac
  done
}

# yes/no; honours --yes (returns the default)
confirm() {
  local prompt="$1" default="${2:-y}" reply hint
  [ "$default" = "y" ] && hint="Y/n" || hint="y/N"
  if [ "$ASSUME_YES" = 1 ]; then [ "$default" = "y" ]; return; fi
  read -r -p "$(printf '%s%s%s [%s]: ' "$BOLD" "$prompt" "$RST" "$hint")" reply || abort
  _check_cancel "$reply"
  case "$(printf '%s' "${reply:-$default}" | tr '[:upper:]' '[:lower:]')" in
    y|yes) return 0 ;; *) return 1 ;;
  esac
}

have() { command -v "$1" >/dev/null 2>&1; }
compose() {
  if $DOCKER_SUDO docker compose version >/dev/null 2>&1; then $DOCKER_SUDO docker compose "$@";
  else $DOCKER_SUDO docker-compose "$@"; fi
}
port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1; }

# --- Prerequisite installation ---------------------------------------------
os_family() { case "$(uname -s)" in Linux) echo linux;; Darwin) echo darwin;; *) echo other;; esac; }

# Resolve a way to run privileged commands. Sets SUDO ("" if root, "sudo" if
# available). Returns non-zero if elevation is impossible.
SUDO=""
resolve_sudo() {
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; return 0; fi
  if have sudo; then SUDO="sudo"; return 0; fi
  return 1
}

pkg_mgr() {
  if have apt-get; then echo apt; elif have dnf; then echo dnf; elif have yum; then echo yum
  elif have apk; then echo apk; elif have brew; then echo brew; else echo none; fi
}
pkg_install() {
  case "$(pkg_mgr)" in
    apt)  $SUDO apt-get update -y && DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y "$@" ;;
    dnf)  $SUDO dnf install -y "$@" ;;
    yum)  $SUDO yum install -y "$@" ;;
    apk)  $SUDO apk add --no-cache "$@" ;;
    brew) brew install "$@" ;;
    *)    return 1 ;;
  esac
}

start_docker_daemon() {
  docker info >/dev/null 2>&1 && return 0
  case "$(os_family)" in
    linux)  have systemctl && $SUDO systemctl enable --now docker >/dev/null 2>&1 || $SUDO service docker start >/dev/null 2>&1 || true ;;
    darwin) open -a Docker >/dev/null 2>&1 || true ;;
  esac
  local i
  for i in $(seq 1 "${DOCKER_START_WAIT:-30}"); do docker info >/dev/null 2>&1 && return 0; sleep 2; done
  return 1
}

install_docker() {
  local fam; fam="$(os_family)"
  if [ "$fam" = "darwin" ]; then
    if have brew; then
      info "Installing Docker Desktop via Homebrew (this can take a while)…"
      brew install --cask docker || return 1
      open -a Docker >/dev/null 2>&1 || true
      return 0
    fi
    err "On macOS, install Docker Desktop from https://www.docker.com/products/docker-desktop then re-run."
    return 1
  fi
  if [ "$fam" != "linux" ]; then err "Automatic Docker install is only supported on Linux and macOS."; return 1; fi
  if ! resolve_sudo; then err "Installing Docker needs root privileges. Re-run as root, or install 'sudo'."; return 1; fi

  have curl || pkg_install curl ca-certificates >/dev/null 2>&1 || true
  if have curl; then
    info "Installing Docker Engine via the official get.docker.com script…"
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh && $SUDO sh /tmp/get-docker.sh || return 1
    rm -f /tmp/get-docker.sh
  else
    info "Installing Docker via the distro package manager…"
    pkg_install docker.io docker-compose-plugin 2>/dev/null || pkg_install docker docker-compose 2>/dev/null || pkg_install docker || return 1
  fi

  start_docker_daemon || true
  # Let the current user run docker without sudo in future sessions.
  if [ "$(id -u)" -ne 0 ] && have usermod; then $SUDO usermod -aG docker "${USER:-$(id -un)}" >/dev/null 2>&1 || true; fi
  return 0
}

ensure_compose() {
  $DOCKER_SUDO docker compose version >/dev/null 2>&1 && return 0
  have docker-compose && return 0
  info "Installing the docker compose plugin…"
  resolve_sudo || true
  pkg_install docker-compose-plugin 2>/dev/null || pkg_install docker-compose 2>/dev/null || true
  $DOCKER_SUDO docker compose version >/dev/null 2>&1 || have docker-compose
}

# Ensure docker + compose + a running daemon, installing if permitted. Returns
# non-zero (caller falls back to config-only) if the stack can't be made ready.
ensure_docker_stack() {
  if ! have docker; then
    if [ "$DO_INSTALL" = 1 ] && { [ "$ASSUME_YES" = 1 ] || confirm "Docker is not installed. Install it now (needs root/sudo)?" "y"; }; then
      install_docker || { warn "Docker installation failed."; return 1; }
      have docker || { warn "Docker still not found after install."; return 1; }
      ok "Docker installed."
    else
      warn "Docker not found; will configure .env only. Install Docker, then: docker compose up -d --build"
      return 1
    fi
  else
    ok "docker present"
  fi

  # Determine whether we need sudo to talk to the daemon this session (e.g. the
  # group change from a fresh install hasn't taken effect yet).
  if ! docker info >/dev/null 2>&1; then
    start_docker_daemon || true
  fi
  if ! docker info >/dev/null 2>&1 && resolve_sudo && [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
    DOCKER_SUDO="$SUDO"
    warn "Using sudo for docker in this session (log out/in to use docker without sudo)."
  fi
  if ! $DOCKER_SUDO docker info >/dev/null 2>&1; then
    err "Docker daemon is not reachable. Start Docker and re-run."
    return 1
  fi
  ok "docker daemon running"

  if ! ensure_compose; then err "docker compose is unavailable and could not be installed."; return 1; fi
  ok "docker compose available"

  local p
  for p in "${DJANGO_PORT_LOCAL:-8000}" 5432 6379; do
    port_in_use "$p" && warn "port $p is already in use — the stack may fail to bind it"
  done
  return 0
}

# ---------------------------------------------------------------------------
# Nginx config + Let's Encrypt SSL (production, when a domain is set)
# ---------------------------------------------------------------------------
# Render nginx_proxy/nginx.conf from the template for the chosen base domain,
# wiring api./app./admin. + apex to the backend and the two frontends.
render_nginx_conf() {
  local tpl="$SCRIPT_DIR/nginx_proxy/nginx.conf.template"
  local out="$SCRIPT_DIR/nginx_proxy/nginx.conf"
  if [ ! -f "$tpl" ]; then warn "nginx template missing ($tpl); leaving nginx.conf unchanged."; return 0; fi
  sed "s/__DOMAIN__/$DOMAIN/g" "$tpl" > "$out"
  ok "Rendered nginx_proxy/nginx.conf for $DOMAIN (api./app./admin./apex)."
}

ensure_openssl() { have openssl || { info "Installing openssl…"; resolve_sudo || true; pkg_install openssl >/dev/null 2>&1 || true; }; have openssl; }

# True if a real (Let's Encrypt / staging) cert already exists for the domain.
ssl_have_real_cert() {
  local live="/etc/letsencrypt/live/$DOMAIN/fullchain.pem" issuer
  $SUDO test -s "$live" 2>/dev/null || return 1
  issuer="$($SUDO openssl x509 -in "$live" -noout -issuer 2>/dev/null || true)"
  case "$issuer" in *"Let's Encrypt"*|*"(STAGING)"*|*"Fake LE"*|*"R3"*|*"E1"*|*"R10"*|*"R11"*) return 0;; *) return 1;; esac
}

# Create a short-lived self-signed cert so Nginx can start on :443 before the
# real certificate is issued (webroot issuance then needs Nginx serving :80).
ssl_bootstrap_dummy() {
  local live="/etc/letsencrypt/live/$DOMAIN"
  $SUDO mkdir -p "$live" /var/www/letsencrypt || return 1
  if $SUDO test -s "$live/fullchain.pem" 2>/dev/null; then return 0; fi
  ensure_openssl || { warn "openssl unavailable; cannot bootstrap SSL."; return 1; }
  info "Creating a temporary self-signed certificate so Nginx can start…"
  $SUDO openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "$live/privkey.pem" -out "$live/fullchain.pem" \
    -subj "/CN=$DOMAIN" >/dev/null 2>&1 || { warn "Could not create bootstrap certificate."; return 1; }
}

# Obtain the real certificate (webroot) and reload Nginx.
ssl_issue() {
  local email_flag staging_flag
  if [ -n "$SSL_EMAIL" ]; then email_flag=(--email "$SSL_EMAIL"); else email_flag=(--register-unsafely-without-email); fi
  if [ "$SSL_STAGING" = 1 ]; then staging_flag=(--staging); else staging_flag=(); fi
  # Clear the bootstrap lineage so certbot writes a fresh, real one.
  $SUDO rm -rf "/etc/letsencrypt/live/$DOMAIN" "/etc/letsencrypt/archive/$DOMAIN" "/etc/letsencrypt/renewal/$DOMAIN.conf" 2>/dev/null || true
  info "Requesting a Let's Encrypt certificate for api./app./admin./$DOMAIN (and www)…"
  if $DOCKER_SUDO docker run --rm \
        -v /etc/letsencrypt:/etc/letsencrypt \
        -v /var/www/letsencrypt:/var/www/letsencrypt \
        certbot/certbot certonly --webroot -w /var/www/letsencrypt \
        --cert-name "$DOMAIN" \
        -d "api.$DOMAIN" -d "app.$DOMAIN" -d "admin.$DOMAIN" -d "$DOMAIN" -d "www.$DOMAIN" \
        "${email_flag[@]}" --agree-tos --no-eff-email --non-interactive "${staging_flag[@]}"; then
    ok "Certificate obtained."
    ( cd "$SCRIPT_DIR" && compose exec -T nginx_proxy nginx -s reload ) >/dev/null 2>&1 \
      || ( cd "$SCRIPT_DIR" && compose restart nginx_proxy ) >/dev/null 2>&1 || true
    ok "Nginx reloaded with the new certificate."
    return 0
  fi
  warn "Certbot failed — Nginx keeps serving the temporary self-signed certificate."
  warn "Check that api./app./admin.$DOMAIN resolve to THIS host and ports 80/443 are open, then re-run ./deploy.sh."
  return 1
}

# Install a daily renewal (webroot) that reloads Nginx after each renewal.
ssl_install_renewal() {
  if [ ! -d /etc/cron.d ]; then
    warn "No /etc/cron.d on this host — set up 'certbot renew' yourself for auto-renewal."
    return 0
  fi
  local cron="/etc/cron.d/betblits-certbot-renew"
  $SUDO tee "$cron" >/dev/null <<CRON
# Auto-renew Let's Encrypt certificates for $DOMAIN and reload Nginx.
# Managed by deploy.sh — safe to edit the schedule.
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 3 * * * root docker run --rm -v /etc/letsencrypt:/etc/letsencrypt -v /var/www/letsencrypt:/var/www/letsencrypt certbot/certbot renew --webroot -w /var/www/letsencrypt --quiet && docker exec whatsappcrm_nginx_proxy nginx -s reload >/dev/null 2>&1
CRON
  $SUDO chmod 644 "$cron" 2>/dev/null || true
  ok "Installed auto-renewal (daily) → $cron"
}

# ===========================================================================
# Preflight
# ===========================================================================
preflight() {
  title "Preflight checks"
  local fatal=0

  if [ "${BASH_VERSINFO:-0}" -lt 4 ]; then
    err "Bash 4+ is required (found ${BASH_VERSION:-unknown}). On macOS: brew install bash, then run with that bash."
    exit 1
  fi
  ok "Bash ${BASH_VERSION%%(*}"

  local f
  for f in docker-compose.yml whatsappcrm_backend/manage.py .env.example; do
    if [ -e "$SCRIPT_DIR/$f" ]; then ok "found $f"; else err "missing $f — run this from the repository root"; fatal=1; fi
  done

  [ "$fatal" = 0 ] || { err "Preflight failed. Resolve the issues above and re-run."; exit 1; }

  # Docker/compose: install & start if permitted, else fall back to config-only.
  if [ "$DO_START" = 1 ]; then
    if ! ensure_docker_stack; then
      DO_START=0
      warn "Continuing in configuration-only mode (no containers will be started)."
    fi
  fi
}

# ===========================================================================
# Main
# ===========================================================================
clear 2>/dev/null || true
title "WhatsApp CRM / BetBlitz — Deployment Setup"
info "Secrets are auto-generated. Cancel any time with Ctrl-C or by typing 'cancel'."
[ "$ASSUME_YES" = 1 ] && info "Running non-interactively (--yes): accepting defaults / existing values."

preflight
load_existing
[ -n "${EXISTING[*]:-}" ] && info "Loaded ${#EXISTING[@]} value(s) from your existing .env as defaults."

# --- 1. Environment & address -----------------------------------------------
title "1) Environment"
if confirm "Is this a PRODUCTION deployment? (No = development)" "y"; then
  ANSWERS[DJANGO_DEBUG]="False"; MODE="production"
else
  ANSWERS[DJANGO_DEBUG]="True";  MODE="development"
fi
info "Mode: $MODE"

DOMAIN=""
if [ "$MODE" = "production" ]; then
  info "Subdomain layout: app.<domain> = player portal, admin.<domain> = admin CRM, api.<domain> = backend."
  # Prefill the base domain on re-run: recover it from a saved SITE_URL
  # (https://api.<domain>) or ALLOWED_HOSTS (api.<domain>,<domain>).
  dom_default=""
  if [ -n "${EXISTING[SITE_URL]:-}" ]; then
    dom_default="$(printf '%s' "${EXISTING[SITE_URL]}" | sed -E 's#^https?://##; s#/.*$##; s#^api\.##')"
  elif [ -n "${EXISTING[DJANGO_ALLOWED_HOSTS]:-}" ]; then
    dom_default="$(printf '%s' "${EXISTING[DJANGO_ALLOWED_HOSTS]}" | sed -E 's#^api\.##; s#,.*$##')"
  fi
  case "$dom_default" in localhost*|127.0.0.1*|""|*yourdomain*|example.com|example.org|*ngrok*) dom_default="";; esac
  ask DOMAIN "Base domain (e.g. betblits.com, no scheme)" "$dom_default" v_domain
  DOMAIN="${ANSWERS[DOMAIN]}"; unset 'ANSWERS[DOMAIN]'
fi
if [ -n "$DOMAIN" ]; then
  # Backend is served at api.<domain>; the two frontends (app./admin.) call it.
  d_site="https://api.$DOMAIN"
  d_hosts="api.$DOMAIN,$DOMAIN"
  d_csrf="https://app.$DOMAIN,https://admin.$DOMAIN,https://api.$DOMAIN"
  d_cors="https://app.$DOMAIN,https://admin.$DOMAIN"
  # These four are fully derived from the domain. Drop any stale .env values so
  # the prompt defaults track the domain just entered (not an old placeholder).
  unset 'EXISTING[SITE_URL]' 'EXISTING[DJANGO_ALLOWED_HOSTS]' \
        'EXISTING[CSRF_TRUSTED_ORIGINS]' 'EXISTING[CORS_ALLOWED_ORIGINS]'
else
  d_site="http://localhost:8000"; d_hosts="localhost,127.0.0.1"
  d_csrf="http://localhost:5173,http://127.0.0.1:5173"; d_cors="http://localhost:5173,http://127.0.0.1:5173"
fi
ask SITE_URL "Site URL (absolute, used for media links)" "$d_site" v_url
ask DJANGO_ALLOWED_HOSTS "Allowed hosts (comma-separated)" "$d_hosts" v_hosts
ask CSRF_TRUSTED_ORIGINS "CSRF trusted origins" "$d_csrf" v_origins
ask CORS_ALLOWED_ORIGINS "CORS allowed origins" "$d_cors" v_origins
ANSWERS[CORS_ALLOW_CREDENTIALS]="True"

# --- 2. Django secret -------------------------------------------------------
title "2) Django secret key"
ask_secret DJANGO_SECRET_KEY "DJANGO_SECRET_KEY"

# --- 3. Database ------------------------------------------------------------
title "3) PostgreSQL database"
ANSWERS[DB_ENGINE]="django.db.backends.postgresql"
ask DB_NAME "Database name" "whatsapp_crm" v_ident
ask DB_USER "Database user" "crm_user" v_ident
ask_secret DB_PASSWORD "DB password (kept URL-safe)" v_safe
if printf '%s' "${ANSWERS[DB_PASSWORD]}" | grep -q '[^A-Za-z0-9]'; then
  ANSWERS[DB_PASSWORD]="$(gen_password)"; info "  → normalised DB password to URL-safe characters"
fi
ask DB_HOST "Database host ('db' for the docker stack)" "db" v_hosts
ask DB_PORT "Database port" "5432" v_port

# --- 4. Redis / Celery ------------------------------------------------------
title "4) Redis & Celery"
ask_secret REDIS_PASSWORD "Redis password (kept URL-safe)" v_safe
if printf '%s' "${ANSWERS[REDIS_PASSWORD]}" | grep -q '[^A-Za-z0-9]'; then
  ANSWERS[REDIS_PASSWORD]="$(gen_password)"; info "  → normalised Redis password to URL-safe characters"
fi
ANSWERS[CELERY_BROKER_URL]="redis://:${ANSWERS[REDIS_PASSWORD]}@redis:6379/0"
ask CELERY_WORKER_CONCURRENCY "Celery IO worker concurrency" "20" v_int

# --- 5. Sessions / tokens ---------------------------------------------------
title "5) Sessions & tokens"
ask JWT_ACCESS_TOKEN_LIFETIME_MINUTES "JWT access token lifetime (minutes)" "60" v_int
ask JWT_REFRESH_TOKEN_LIFETIME_DAYS "JWT refresh token lifetime (days)" "7" v_int
ask SESSION_IDLE_TIMEOUT_MINUTES "WhatsApp flow session idle timeout (minutes)" "5" v_int
ask CONVERSATION_EXPIRY_DAYS "Conversation retention (days)" "60" v_int

# --- 6. Football data -------------------------------------------------------
title "6) Football data (API-Football v3 recommended)"
info "Key: https://www.api-football.com/  — leave blank to configure later."
ask API_FOOTBALL_V3_KEY "API_FOOTBALL_V3_KEY" "" v_safe
ask API_FOOTBALL_V3_CURRENT_SEASON "Current season year" "2024" v_int
ask API_FOOTBALL_MAX_REQUESTS_PER_MINUTE "Max API requests/minute" "300" v_int
if confirm "Configure legacy/backup providers (apifootball.com, The Odds API)?" "n"; then
  ask API_FOOTBALL_KEY "API_FOOTBALL_KEY (apifootball.com)" "" v_safe
  ask FOOTBALL_DATA_API_KEY "FOOTBALL_DATA_API_KEY" "" v_safe
  ask THE_ODDS_API_KEY "THE_ODDS_API_KEY" "" v_safe
else
  ANSWERS[API_FOOTBALL_KEY]="$(_default_for API_FOOTBALL_KEY '')"
  ANSWERS[FOOTBALL_DATA_API_KEY]="$(_default_for FOOTBALL_DATA_API_KEY '')"
  ANSWERS[THE_ODDS_API_KEY]="$(_default_for THE_ODDS_API_KEY '')"
fi

# --- 7. WhatsApp / Meta -----------------------------------------------------
title "7) WhatsApp / Meta"
info "The Meta access token & phone-number ID are configured in the Django admin"
info "(MetaAppConfig) after deploy. Only the webhook app secret lives in .env."
ask WHATSAPP_APP_SECRET "WHATSAPP_APP_SECRET (webhook signature verification)" "" v_safe

# --- 8. AI / notifications / RG ---------------------------------------------
title "8) AI, notifications & responsible gambling"
ask GEMINI_API_KEY "GEMINI_API_KEY (optional; assistant works without it)" "" v_safe
ask GEMINI_MODEL "Gemini model" "gemini-1.5-flash" v_safe
ask BET_SETTLEMENT_TEMPLATE_NAME "Settlement WhatsApp template name (blank = plain text)" "" v_safe
ask BET_SETTLEMENT_TEMPLATE_LANG "Settlement template language" "en_US" v_safe
ask RG_MIN_AGE "Minimum betting age" "18" v_age
if confirm "Require KYC verification before a first bet?" "n"; then
  ANSWERS[RG_REQUIRE_KYC]="True"
else
  ANSWERS[RG_REQUIRE_KYC]="False"
fi

# --- 9. Review & write ------------------------------------------------------
title "9) Review"
_mask() { case "$1" in *SECRET*|*PASSWORD*|*_KEY|*BROKER_URL) [ -n "$2" ] && printf '******(…%s)' "${2: -4}" || printf '(empty)';; *) printf '%s' "${2:-(empty)}";; esac; }
ENV_KEYS=(DJANGO_SECRET_KEY DJANGO_DEBUG DJANGO_ALLOWED_HOSTS CSRF_TRUSTED_ORIGINS SITE_URL
  CORS_ALLOWED_ORIGINS CORS_ALLOW_CREDENTIALS DB_ENGINE DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT
  REDIS_PASSWORD CELERY_BROKER_URL CELERY_WORKER_CONCURRENCY
  JWT_ACCESS_TOKEN_LIFETIME_MINUTES JWT_REFRESH_TOKEN_LIFETIME_DAYS SESSION_IDLE_TIMEOUT_MINUTES CONVERSATION_EXPIRY_DAYS
  API_FOOTBALL_V3_KEY API_FOOTBALL_V3_CURRENT_SEASON API_FOOTBALL_MAX_REQUESTS_PER_MINUTE
  API_FOOTBALL_KEY FOOTBALL_DATA_API_KEY THE_ODDS_API_KEY WHATSAPP_APP_SECRET
  GEMINI_API_KEY GEMINI_MODEL BET_SETTLEMENT_TEMPLATE_NAME BET_SETTLEMENT_TEMPLATE_LANG RG_MIN_AGE RG_REQUIRE_KYC)
info "The following will be written to $ENV_FILE (secrets masked):"
for k in "${ENV_KEYS[@]}"; do printf '  %-34s = %s\n' "$k" "$(_mask "$k" "${ANSWERS[$k]:-}")"; done
say ""
confirm "Write this configuration now?" "y" || abort

write_env() {
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '# Generated by deploy.sh on %s\n# Do NOT commit this file. Rotate any secret that leaks.\n\n' "$ts"
  local k
  for k in "${ENV_KEYS[@]}"; do printf '%s=%s\n' "$k" "${ANSWERS[$k]:-}"; done
}

if [ -f "$ENV_FILE" ]; then
  backup="$ENV_FILE.bak.$(date -u +%Y%m%d%H%M%S)"
  cp "$ENV_FILE" "$backup"; ok "Backed up existing .env → $(basename "$backup")"
fi
umask 077
tmp_env="$(mktemp "${ENV_FILE}.XXXXXX")"
write_env > "$tmp_env"
mv "$tmp_env" "$ENV_FILE"
chmod 600 "$ENV_FILE"
ok "Wrote $ENV_FILE (permissions 600)"

# Render the Nginx config for the domain (production) regardless of whether we
# start now, so the committed default always matches the chosen domain.
if [ "$MODE" = "production" ] && [ -n "$DOMAIN" ]; then
  render_nginx_conf
fi

# --- 10. Start the stack ----------------------------------------------------
if [ "$DO_START" != 1 ]; then
  say ""; ok "Configuration complete. Start it with:  cd $SCRIPT_DIR && docker compose up -d --build"
  exit 0
fi

title "10) Start the stack"
if ! confirm "Build and start the Docker stack now (docker compose up -d --build)?" "y"; then
  say ""; ok "Configuration complete. Start it later with:  cd $SCRIPT_DIR && docker compose up -d --build"
  exit 0
fi

# For a production domain, ask about Let's Encrypt certificates so Nginx can
# serve HTTPS from first start (the Nginx config was rendered above).
if [ "$MODE" = "production" ] && [ -n "$DOMAIN" ]; then
  if confirm "Obtain Let's Encrypt SSL certificates for $DOMAIN now?" "y"; then
    info "DNS for api.$DOMAIN, app.$DOMAIN and admin.$DOMAIN must already point to THIS host, with ports 80/443 open."
    ask SSL_EMAIL_ANS "  Email for renewal & expiry notices (blank to skip)" "" v_email
    SSL_EMAIL="${ANSWERS[SSL_EMAIL_ANS]:-}"; unset 'ANSWERS[SSL_EMAIL_ANS]'
    if confirm "  Use STAGING (test) certificates first? (avoids rate limits while verifying DNS)" "n"; then SSL_STAGING=1; fi
    if ! resolve_sudo && [ "$(id -u)" -ne 0 ]; then
      warn "SSL setup needs root/sudo to write /etc/letsencrypt; skipping certificate issuance."
    else
      ssl_bootstrap_dummy && DO_SSL=1 || warn "Could not prepare SSL; continuing without HTTPS certificates."
    fi
  fi
fi

info "Building and starting containers…"
if ! ( cd "$SCRIPT_DIR" && compose up -d --build ); then
  err "docker compose failed (see output above). Your .env is saved; fix the issue and run:"
  say "    cd $SCRIPT_DIR && docker compose up -d --build"
  exit 1
fi
ok "Containers started."

info "Waiting for the backend to become ready…"
ready=0
for _ in $(seq 1 40); do
  if ( cd "$SCRIPT_DIR" && compose exec -T backend python manage.py showmigrations >/dev/null 2>&1 ); then ready=1; break; fi
  sleep 3
done
if [ "$ready" = 1 ]; then ok "Backend is responding."; else warn "Backend did not report ready in time; check 'docker compose logs backend'."; fi

# --- 10b. SSL certificates --------------------------------------------------
if [ "$DO_SSL" = 1 ]; then
  title "10b) SSL certificates"
  if ssl_have_real_cert && [ "$REGEN" != 1 ]; then
    ok "A valid certificate already exists for $DOMAIN — skipping issuance (use --regenerate to force)."
    ( cd "$SCRIPT_DIR" && compose exec -T nginx_proxy nginx -s reload ) >/dev/null 2>&1 || true
  else
    if ssl_issue; then ssl_install_renewal; fi
  fi
fi

run_mgmt() { ( cd "$SCRIPT_DIR" && compose exec -T backend python manage.py "$@" ); }

title "11) First-time setup"
if confirm "Apply database migrations (makemigrations + migrate)?" "y"; then
  run_mgmt makemigrations >/dev/null 2>&1 || warn "makemigrations: nothing to make or non-fatal issue."
  if run_mgmt migrate; then ok "Migrations applied."; else warn "migrate failed — check 'docker compose logs backend'."; fi
fi
if confirm "Load WhatsApp conversational flow definitions?" "y"; then
  run_mgmt load_flow_definitions && ok "Flow definitions loaded." || warn "load_flow_definitions failed."
fi
if [ -n "${ANSWERS[API_FOOTBALL_V3_KEY]}" ] && confirm "Fetch football leagues from API-Football v3 now?" "y"; then
  run_mgmt football_league_setup_v3 && ok "Leagues initialised." || warn "League setup failed; check the API key."
fi
if confirm "Create a Django admin superuser now?" "y"; then
  ( cd "$SCRIPT_DIR" && compose exec backend python manage.py createsuperuser ) || warn "Superuser creation skipped/failed."
fi

# --- Done -------------------------------------------------------------------
title "Done 🎉"
ok "BetBlitz is deployed."
say ""
if [ -n "$DOMAIN" ]; then
  info "Your surfaces:"
  say "  • Player portal:  https://app.$DOMAIN"
  say "  • Admin CRM:      https://admin.$DOMAIN"
  say "  • Backend/API:    https://api.$DOMAIN"
  if [ "$DO_SSL" = 1 ]; then say "  • TLS: Let's Encrypt (auto-renews daily via /etc/cron.d/betblits-certbot-renew)."; fi
  say ""
fi
info "Next steps:"
say "  • Django admin → add a MetaAppConfig (WhatsApp access token, phone-number ID, verify token)."
say "  • Point the Meta webhook at  ${ANSWERS[SITE_URL]}/crm-api/meta/webhook/"
say "  • Set the Flow endpoint URI to  ${ANSWERS[SITE_URL]}/crm-api/meta/flow-endpoint/<phone_number_id>/"
say "  • If you use Paynow, add its credentials in the admin."
say "  • Schedule the football update & score/settlement tasks (django-celery-beat, in the admin)."
say ""
info "Manage the stack:  cd $SCRIPT_DIR && docker compose ps | logs -f | down"
