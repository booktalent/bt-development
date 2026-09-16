# BookTalent — VPS Deployment Guide

Complete step-by-step guide to host BookTalent on your own VPS (Ubuntu 22.04 LTS assumed).
Estimated time: **60–90 minutes** end-to-end.

---

## 🖥️ 0. Prerequisites

Before you start, make sure you have:

- [ ] A **VPS** (DigitalOcean / Hetzner / AWS EC2 / Contabo) — **minimum 2 GB RAM, 2 CPU, 40 GB SSD**. 4 GB RAM recommended.
- [ ] Ubuntu 22.04 LTS installed (this guide is written for it; Debian 12 works the same).
- [ ] A **domain name** pointed to your VPS IP (both `booktalent.yourdomain.com` and `www.booktalent.yourdomain.com` — A records).
- [ ] SSH access as a sudo user (never work as `root` directly).
- [ ] The repository pushed to GitHub via Emergent's **"Save to GitHub"** button.

Throughout this guide replace `booktalent.example.com` with **your actual domain** (Ctrl+H in your editor when editing configs).

---

## 🔧 1. System packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3.11 python3.11-venv python3-pip \
    nginx redis-server \
    build-essential libpq-dev git curl ufw \
    certbot python3-certbot-nginx \
    logrotate
```

### Install Node.js 20 + Yarn (for the React build)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install --global yarn
node -v && yarn -v      # should print v20.x and 1.22.x
```

### Install MongoDB 7

```bash
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
    sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] \
    https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
    sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update && sudo apt install -y mongodb-org
sudo systemctl enable --now mongod
mongosh --eval "db.runCommand({ping:1})"   # should print { ok: 1 }
```

---

## 🔥 2. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
sudo ufw status
```

Only ports 22 (SSH), 80, 443 are exposed. MongoDB, Redis, and the backend all bind to `127.0.0.1` — never accessible externally.

---

## 👤 3. Create a dedicated app user

```bash
sudo adduser --system --group --home /opt/booktalent booktalent
sudo mkdir -p /opt/booktalent /var/log/booktalent
sudo chown -R booktalent:booktalent /opt/booktalent /var/log/booktalent
```

---

## 📥 4. Pull the code

```bash
# Replace with your actual repo URL from Emergent → Save to GitHub
sudo -u booktalent git clone https://github.com/YOUR-USERNAME/booktalent.git /opt/booktalent
cd /opt/booktalent
```

Confirm the tree looks like:

```
/opt/booktalent/
├── backend/
├── frontend/
├── deploy/           ← this guide + configs live here
└── memory/
```

---

## 🐍 5. Backend setup

```bash
cd /opt/booktalent/backend

# Create the Python venv as the booktalent user
sudo -u booktalent python3.11 -m venv .venv

# Install pip deps
sudo -u booktalent ./.venv/bin/pip install --upgrade pip
sudo -u booktalent ./.venv/bin/pip install -r requirements.txt

# OPTIONAL: install emergentintegrations for AI Semantic Search.
# Only needed if you have EMERGENT_LLM_KEY. Skipping is safe — the AI-search
# endpoint auto-falls-back to a regex keyword search with zero errors.
sudo -u booktalent ./.venv/bin/pip install -r requirements-emergent.txt \
    --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ || \
    echo "  (skipped — no EMERGENT_LLM_KEY, or private index unreachable)"
```

### Create the backend `.env`

```bash
sudo cp /opt/booktalent/deploy/backend.env.production.example \
        /opt/booktalent/backend/.env
sudo chown booktalent:booktalent /opt/booktalent/backend/.env
sudo chmod 600 /opt/booktalent/backend/.env

# Generate a strong JWT secret
echo "JWT_SECRET=$(openssl rand -hex 48)" | sudo tee -a /opt/booktalent/backend/.env

# Now edit and fill in the rest (Razorpay, Resend, Emergent LLM key, etc.)
sudo -u booktalent nano /opt/booktalent/backend/.env
```

> 💡 Leave third-party keys **blank** to keep the app in mock mode — SMS/email/payments will log to the systemd journal instead of failing. You can add real keys later without redeploying.

### Seed the admin user (first-run)

```bash
cd /opt/booktalent/backend
sudo -u booktalent ./.venv/bin/python -c "
import asyncio
from server import ensure_seed_admin
asyncio.run(ensure_seed_admin())
"
```

Default admin: `admin@booktalent.com / Admin@123` — **change the password immediately** via the Admin panel.

---

## ⚛️ 6. Frontend setup

```bash
cd /opt/booktalent/frontend

# Create the frontend .env with your production API URL
sudo cp /opt/booktalent/deploy/frontend.env.production.example \
        /opt/booktalent/frontend/.env
sudo -u booktalent nano /opt/booktalent/frontend/.env
# Set REACT_APP_BACKEND_URL=https://booktalent.yourdomain.com

# Install deps + build static bundle
sudo -u booktalent yarn install --frozen-lockfile
sudo -u booktalent yarn build
```

You should now have `/opt/booktalent/frontend/build/` — Nginx will serve this as static files.

---

## 🔀 7. Systemd service for the backend

```bash
sudo cp /opt/booktalent/deploy/systemd/booktalent-backend.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now booktalent-backend

# Verify
sudo systemctl status booktalent-backend
curl http://127.0.0.1:8001/api/healthz   # {"ok": true, ...}
```

Logs:

```bash
sudo journalctl -u booktalent-backend -f
```

---

## 🌐 8. Nginx reverse proxy

### Update the Nginx config with your domain

```bash
sudo cp /opt/booktalent/deploy/nginx.conf /etc/nginx/sites-available/booktalent
sudo sed -i 's/booktalent.example.com/booktalent.yourdomain.com/g' \
    /etc/nginx/sites-available/booktalent
sudo ln -s /etc/nginx/sites-available/booktalent /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default    # remove the welcome page

sudo nginx -t
sudo systemctl reload nginx
```

### Get the SSL certificate (Let's Encrypt)

```bash
sudo certbot --nginx \
    -d booktalent.yourdomain.com \
    -d www.booktalent.yourdomain.com \
    --agree-tos --email ops@yourdomain.com --redirect --non-interactive

# Test auto-renewal
sudo certbot renew --dry-run
```

Now open `https://booktalent.yourdomain.com` in a browser — you should see the BookTalent homepage.

---

## 🗓️ 9. Backups + cron

```bash
sudo cp /opt/booktalent/deploy/cron/booktalent.cron /etc/cron.d/booktalent
sudo chmod 644 /etc/cron.d/booktalent

sudo cp /opt/booktalent/deploy/logrotate/booktalent /etc/logrotate.d/
sudo chmod 644 /etc/logrotate.d/booktalent

sudo chmod +x /opt/booktalent/deploy/scripts/*.sh

# Test the backup script manually
sudo /opt/booktalent/deploy/scripts/backup_mongo.sh
ls -lh /var/backups/booktalent/mongo/
```

Daily backups now run at 03:15 IST and are pruned after 14 days.

For off-site backups, uncomment the `aws s3 cp` line at the bottom of `backup_mongo.sh` after configuring `aws-cli`.

---

## 🚀 10. Future deploys (one-liner)

Once everything is set up, every future update is just:

```bash
sudo /opt/booktalent/deploy/scripts/deploy.sh
```

This pulls the latest code, reinstalls deps if any changed, rebuilds the React bundle, and restarts the backend + reloads Nginx — with zero downtime for READs.

---

## ✅ 11. Smoke test

```bash
# 1. Backend health
curl -s https://booktalent.yourdomain.com/api/healthz | python3 -m json.tool

# 2. Frontend loads
curl -sI https://booktalent.yourdomain.com/ | head -1     # HTTP/2 200

# 3. Login works
curl -s -X POST https://booktalent.yourdomain.com/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@booktalent.com","password":"Admin@123"}' | python3 -m json.tool
```

Then open the site in a browser and:

- [ ] Log in as admin, change the password
- [ ] Create a new customer account
- [ ] Book an artist end-to-end
- [ ] Test real-time chat between two browser sessions

---

## 🔧 Troubleshooting

| Symptom | Fix |
|---|---|
| `502 Bad Gateway` from Nginx | Backend not running → `sudo systemctl status booktalent-backend` and check the journal |
| `413 Request Entity Too Large` on uploads | Increase `client_max_body_size` in `nginx.conf` |
| Chat WebSocket won't connect | Check the `location ~ ^/api/ws/` block exists and comes before `/api/` |
| `CORS blocked` in browser console | Add your domain to `CORS_ORIGINS` in backend `.env` and restart |
| MongoDB won't start | `sudo systemctl status mongod`, check `/var/log/mongodb/mongod.log` |
| Certbot fails | DNS not propagated yet — `dig booktalent.yourdomain.com +short` should show your VPS IP |
| Backend logs show "Redis connection refused" | Either start Redis (`sudo systemctl enable --now redis-server`) or blank `REDIS_URL` in `.env` |

---

## 📈 Scaling later

When traffic grows past ~1000 concurrent users:

1. Bump `--workers 4` → `--workers 8` in the systemd file (or match `2 × CPU cores`)
2. Move MongoDB to a dedicated node (or MongoDB Atlas)
3. Add a second app node behind Nginx → both must share the same `REDIS_URL` for WebSocket fan-out
4. Move base64-encoded media (KYC docs, review videos, chat uploads) to S3/R2 — currently they live inline in Mongo

---

## 📞 Support

- Emergent LLM key balance → https://emergent.sh → Profile → Universal Key → Add Balance
- Razorpay dashboard → https://dashboard.razorpay.com
- Resend dashboard → https://resend.com/emails
- Certbot renewal issues → `journalctl -u certbot`

Everything else — check the systemd journal:

```bash
sudo journalctl -u booktalent-backend --since "1 hour ago" -f
```

---

## 🆕 Iter 99 additions — Nginx + Backups (production-hardened)

Iter 99 shipped two ready-to-drop-in files under this same folder. Use them instead of hand-writing your own nginx/cron.

### A. Nginx config (`deploy/nginx-booktalent.conf`)

Includes everything the security audit + upload flow requires:

- `client_max_body_size 20M` — required for 4 MB chunked video/doc uploads to pass
- Per-endpoint rate-limit zones (auth: 5 r/s, general: 30 r/s, uploads: 10 r/s)
- WebSocket upgrade path for live chat (`/api/ws/`)
- HSTS + X-Content-Type-Options + Referrer-Policy security headers
- Immutable-cache for React hashed assets

```bash
sudo cp /app/deploy/nginx-booktalent.conf /etc/nginx/sites-available/booktalent.in.conf
sudo ln -s /etc/nginx/sites-available/booktalent.in.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d booktalent.in -d www.booktalent.in
```

### B. Nightly MongoDB backup (`deploy/backup_mongo.sh` + `deploy/booktalent-backup.cron`)

- Runs at **02:30 UTC daily** via `/etc/cron.d/booktalent-backup`
- Dumps `booktalent` DB to `.archive.gz` on a **separate volume** (`/mnt/backups/booktalent`)
- Retention: **14 days** (configurable)
- Integrity self-check with `gunzip -t`
- Slack alert on failure
- Optional rclone offsite copy to S3 / R2 / B2
- Failure paths surface in `/var/log/booktalent-backup.log`

Install:

```bash
# 1. Script + cron
sudo cp /app/deploy/backup_mongo.sh    /usr/local/bin/booktalent-backup
sudo chmod +x                           /usr/local/bin/booktalent-backup
sudo cp /app/deploy/booktalent-backup.cron /etc/cron.d/booktalent-backup

# 2. Overrides (Slack, retention, backup dir)
sudo tee /etc/default/booktalent-backup >/dev/null <<'EOF'
BACKUP_DIR=/mnt/backups/booktalent
RETENTION_DAYS=14
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
# S3_REMOTE=s3-backup:booktalent-backups/    # requires `rclone config` first
EOF

# 3. Verify a manual run
sudo /usr/local/bin/booktalent-backup
ls -lh /mnt/backups/booktalent/
```

Restore in an incident:

```bash
mongorestore \
  --uri="mongodb://localhost:27017" \
  --gzip \
  --archive=/mnt/backups/booktalent/booktalent-<TIMESTAMP>.archive.gz \
  --drop
```

⚠️ **Mount `/mnt/backups` from a SEPARATE disk** (not `/`) so a full-disk incident doesn't take your last backup with it. Any cloud provider block volume works.

