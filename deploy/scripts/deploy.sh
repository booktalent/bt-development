#!/usr/bin/env bash
# BookTalent — one-shot deploy script
# Usage:  sudo ./deploy.sh
# --------------------------------------------------------------------
# Pulls latest code, installs deps, rebuilds frontend, restarts backend.
# Idempotent — safe to re-run on every push.
# --------------------------------------------------------------------
set -euo pipefail

APP_DIR="/opt/booktalent"
APP_USER="booktalent"

echo "▶ Pulling latest from git…"
cd "$APP_DIR"
sudo -u "$APP_USER" git pull --rebase

echo "▶ Backend — installing Python deps…"
cd "$APP_DIR/backend"
sudo -u "$APP_USER" ./.venv/bin/pip install --upgrade -r requirements.txt

# OPTIONAL: install emergentintegrations for AI Semantic Search.
# If EMERGENT_LLM_KEY is set in .env, we install; otherwise skip cleanly.
if grep -q '^EMERGENT_LLM_KEY=..' "$APP_DIR/backend/.env" 2>/dev/null; then
    echo "▶ Installing optional AI Search deps (emergentintegrations)…"
    sudo -u "$APP_USER" ./.venv/bin/pip install --upgrade \
        -r requirements-emergent.txt \
        --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ || \
        echo "  (skipped — private index unreachable; AI search will use regex fallback)"
else
    echo "▶ No EMERGENT_LLM_KEY set — skipping AI Search deps (regex fallback in effect)."
fi

echo "▶ Frontend — installing + building React bundle…"
cd "$APP_DIR/frontend"
sudo -u "$APP_USER" yarn install --frozen-lockfile
sudo -u "$APP_USER" yarn build

echo "▶ Restarting backend (systemd)…"
sudo systemctl restart booktalent-backend
sleep 2
sudo systemctl status booktalent-backend --no-pager

echo "▶ Reloading Nginx…"
sudo nginx -t && sudo systemctl reload nginx

echo "✓ Deploy complete."
echo "  Backend:  https://$(hostname -f)/api/healthz"
echo "  Frontend: https://$(hostname -f)/"
