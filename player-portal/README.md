# BetBlitz Player Portal

A lean, mobile-first web app for **players** — served at `app.<domain>`, separate
from the admin CRM (`admin.<domain>`). It's a **read-only** view of the player's
matches, bets, wallet and profile; all actions (placing bets, deposits,
withdrawals, limits) happen in WhatsApp.

## Login
Players have no web password — they log in with a **WhatsApp one-time code**:
1. Enter WhatsApp number → backend sends a 6-digit code (`/crm-api/auth/player/request-otp/`).
2. Enter the code → receive JWT tokens (`/crm-api/auth/player/verify-otp/`).

All data comes from the player-scoped `/crm-api/football/*` endpoints.

## Develop
```bash
cp .env.example .env      # set VITE_API_BASE_URL to your backend
npm install
npm run dev               # http://localhost:5174
```

## Build (production)
```bash
VITE_API_BASE_URL=https://api.<domain> npm run build
```
Serve the static `dist/` at `app.<domain>` (via your reverse proxy / CDN).

## Stack
React 18 + React Router + Axios + Vite. Plain CSS (no build-time UI framework)
for a small, dependency-light bundle.
