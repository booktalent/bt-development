# BookTalent — AlmaLinux 10 Deployment Guide (for beginners)

This guide takes you from a **blank AlmaLinux 10 VPS** to a **live BookTalent website with all your existing data** — step by step. No prior Linux experience needed. Every command is copy-paste ready.

**Time to complete:** ~90 minutes if you go slow.

---

## 📋 What you'll do (big picture)

1. **On the Emergent side (your current dev environment)** — export the code to GitHub + dump the MongoDB database to a file
2. **On your new AlmaLinux 10 VPS** — install everything, pull the code, restore the database, start services, get SSL
3. **Smoke test** — log in and confirm everything works

---

## 📦 PART A — Export from Emergent

### A1. Push the code to GitHub

1. In the Emergent chat interface, look for the **"Save to GitHub"** button (top-right of the chat input area)
2. Click it → connect your GitHub account (first time only)
3. Choose a repository name (e.g. `booktalent`)
4. Set it to **Private** (recommended — your `.env` templates go with it)
5. Click **Save/Push**

You now have `https://github.com/YOUR-USERNAME/booktalent`. Copy that URL.

### A2. Export the MongoDB database

You need your current data (users, bookings, artists, coupons, chat messages) too. The Emergent agent will do this for you — just ask in chat:

> "Please run mongodump and give me a downloadable link"

The agent will run this and hand you a tarball URL:

```bash
# What the agent runs for you inside the Emergent pod:
cd /tmp
mongodump --uri="$MONGO_URL" --db=booktalent --out=/tmp/booktalent-dump --gzip
tar -czf /tmp/booktalent-dump.tar.gz -C /tmp booktalent-dump
```

Download the resulting `.tar.gz` to your **laptop** (you'll upload it to the VPS in Part C).

---

## 🖥️ PART B — Set up your AlmaLinux 10 VPS

### B0. Log into your VPS

From your laptop terminal (or PuTTY on Windows):

```bash
ssh root@YOUR_VPS_IP
```

> If your provider gave you a non-root user, prefix every command below with `sudo`.

### B1. Create a regular user (don't work as root)

```bash
adduser deploy
passwd deploy
# Enter a strong password twice

usermod -aG wheel deploy         # add to sudo group
```

Now log out (`exit`) and log back in as `deploy`:

```bash
ssh deploy@YOUR_VPS_IP
```

### B2. Update the system

```bash
sudo dnf update -y
sudo dnf install -y epel-release
sudo dnf install -y curl wget git tar nano vim which
```

### B3. Set the timezone (for correct cron & logs)

```bash
sudo timedatectl set-timezone Asia/Kolkata     # or your timezone
date                                            # confirm
```

### B4. Install Python 3.11

```bash
sudo dnf install -y python3.11 python3.11-pip python3.11-devel gcc
python3.11 --version   # Python 3.11.x
```

### B5. Install Node.js 20 + Yarn

```bash
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y nodejs
sudo npm install --global yarn
node -v && yarn -v     # v20.x and 1.22.x
```

### B6. Install MongoDB 7

AlmaLinux 10 uses the RHEL 9 MongoDB packages (fully compatible):

```bash
sudo tee /etc/yum.repos.d/mongodb-org-7.0.repo > /dev/null <<'EOF'
[mongodb-org-7.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/redhat/9/mongodb-org/7.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://pgp.mongodb.com/server-7.0.asc
EOF

sudo dnf install -y mongodb-org
sudo systemctl enable --now mongod
sudo systemctl status mongod --no-pager   # should say "active (running)"
mongosh --eval "db.runCommand({ping:1})"  # { ok: 1 }
```

### B7. Install Redis

```bash
sudo dnf install -y redis
sudo systemctl enable --now redis
redis-cli ping    # PONG
```

### B8. Install Nginx + Certbot (for SSL)

```bash
sudo dnf install -y nginx certbot python3-certbot-nginx
sudo systemctl enable --now nginx
```

### B9. Configure the firewall (firewalld)

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --reload
sudo firewall-cmd --list-services      # confirm: dhcpv6-client http https ssh
```

### B10. Configure SELinux for Nginx reverse-proxy

AlmaLinux has SELinux enabled — Nginx needs permission to talk to the backend:

```bash
sudo setsebool -P httpd_can_network_connect 1
sudo setsebool -P httpd_can_network_relay 1
```

### B11. Create the app user + folders

```bash
sudo useradd --system --home /opt/booktalent --shell /bin/bash booktalent
sudo mkdir -p /opt/booktalent /var/log/booktalent /var/backups/booktalent
sudo chown -R booktalent:booktalent /opt/booktalent /var/log/booktalent /var/backups/booktalent
```

---

## 📥 PART C — Pull the code and restore data

### C1. Clone your GitHub repo

```bash
sudo -u booktalent git clone https://github.com/YOUR-USERNAME/booktalent.git /opt/booktalent
cd /opt/booktalent
ls                                # should see backend/  frontend/  deploy/  memory/
```

### C2. Upload the database dump

From your **laptop terminal** (in a new window, not on the VPS):

```bash
# Replace YOUR_VPS_IP and the tarball path
scp booktalent-dump.tar.gz deploy@YOUR_VPS_IP:/tmp/
```

Back on the **VPS**:

```bash
cd /tmp
tar -xzf booktalent-dump.tar.gz
ls booktalent-dump/               # should see booktalent/ folder with .bson files

# Restore into MongoDB
mongorestore --uri="mongodb://localhost:27017" \
    --db=booktalent \
    --gzip \
    /tmp/booktalent-dump/booktalent

# Verify
mongosh --eval "db.getSiblingDB('booktalent').users.countDocuments()"
# Should print a number > 0 (e.g. 25)
```

### C3. Backend — Python virtualenv + dependencies

```bash
cd /opt/booktalent/backend
sudo -u booktalent python3.11 -m venv .venv
sudo -u booktalent ./.venv/bin/pip install --upgrade pip
sudo -u booktalent ./.venv/bin/pip install -r requirements.txt
```

> ✅ **This will now install cleanly on any VPS.** The `emergentintegrations`
> package has been moved to `requirements-emergent.txt` (optional).

**OPTIONAL — install `emergentintegrations` for AI Semantic Search**

The AI-powered natural-language search (`/api/search/ai`) uses Emergent's
private LLM library. If you skip this, the endpoint automatically falls back
to a fast regex-based keyword search — **zero code changes, zero errors**.

To enable full AI search, install the optional package:

```bash
sudo -u booktalent ./.venv/bin/pip install -r requirements-emergent.txt \
    --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
```

You'll also need `EMERGENT_LLM_KEY` in your `backend/.env` — get it from
https://emergent.sh → Profile → Universal Key.

### C4. Create backend `.env`

```bash
sudo cp /opt/booktalent/deploy/backend.env.production.example \
        /opt/booktalent/backend/.env
sudo chown booktalent:booktalent /opt/booktalent/backend/.env
sudo chmod 600 /opt/booktalent/backend/.env

# Generate a strong JWT secret and add it
JWT=$(openssl rand -hex 48)
echo "" | sudo tee -a /opt/booktalent/backend/.env
echo "# Auto-generated on $(date)" | sudo tee -a /opt/booktalent/backend/.env
# Replace the placeholder in the file
sudo sed -i "s/CHANGE_ME_TO_A_64_CHAR_HEX_STRING/$JWT/" /opt/booktalent/backend/.env

# Now edit and fill in the rest
sudo nano /opt/booktalent/backend/.env
```

**What to fill in** — the file has comments explaining each. Bare minimum to get started:

```
MONGO_URL=mongodb://localhost:27017
DB_NAME=booktalent
REDIS_URL=redis://localhost:6379/0
EMERGENT_LLM_KEY=            # optional — get from https://emergent.sh
RAZORPAY_KEY_ID=             # leave blank for now (mock mode)
RESEND_API_KEY=              # leave blank for now (mock mode)
CORS_ORIGINS=https://YOUR-DOMAIN.com
```

Save (`Ctrl+O`, Enter, `Ctrl+X`).

### C5. Frontend — build the React static bundle

```bash
cd /opt/booktalent/frontend
sudo cp /opt/booktalent/deploy/frontend.env.production.example \
        /opt/booktalent/frontend/.env

sudo nano /opt/booktalent/frontend/.env
# Set REACT_APP_BACKEND_URL=https://YOUR-DOMAIN.com

sudo -u booktalent yarn install --frozen-lockfile
sudo -u booktalent yarn build          # takes ~2 minutes; creates frontend/build/
```

---

## 🔀 PART D — Start the backend + Nginx

### D1. Install the systemd service

```bash
sudo cp /opt/booktalent/deploy/systemd/booktalent-backend.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now booktalent-backend

# Wait 3 seconds then verify
sleep 3
sudo systemctl status booktalent-backend --no-pager
curl http://127.0.0.1:8001/api/healthz    # {"ok": true, ...}
```

If you see `active (running)` and the curl returns JSON, backend is live.

Watch logs live with:

```bash
sudo journalctl -u booktalent-backend -f    # Ctrl+C to exit
```

### D2. Configure Nginx

Replace `YOUR-DOMAIN.com` with your actual domain:

```bash
sudo cp /opt/booktalent/deploy/nginx.conf /etc/nginx/conf.d/booktalent.conf
sudo sed -i 's/booktalent.example.com/YOUR-DOMAIN.com/g' /etc/nginx/conf.d/booktalent.conf

# Remove the default landing page
sudo rm -f /etc/nginx/conf.d/default.conf

# Test the config
sudo nginx -t

# Reload
sudo systemctl reload nginx
```

Point your domain's A record to your VPS IP if you haven't yet. Wait ~5 minutes for DNS to propagate. Verify with:

```bash
dig YOUR-DOMAIN.com +short    # should show your VPS IP
```

### D3. Get a free SSL certificate (Let's Encrypt)

```bash
sudo certbot --nginx \
    -d YOUR-DOMAIN.com \
    -d www.YOUR-DOMAIN.com \
    --agree-tos \
    --email your@email.com \
    --redirect \
    --non-interactive
```

Certbot will edit your Nginx config to add the SSL certificate paths. When done:

```bash
sudo systemctl reload nginx
sudo certbot renew --dry-run       # test auto-renewal works
```

---

## 🗓️ PART E — Backups + automation

```bash
sudo cp /opt/booktalent/deploy/cron/booktalent.cron /etc/cron.d/booktalent
sudo chmod 644 /etc/cron.d/booktalent

sudo cp /opt/booktalent/deploy/logrotate/booktalent /etc/logrotate.d/
sudo chmod 644 /etc/logrotate.d/booktalent

sudo chmod +x /opt/booktalent/deploy/scripts/*.sh

# Test the backup runs
sudo /opt/booktalent/deploy/scripts/backup_mongo.sh
ls -lh /var/backups/booktalent/mongo/
```

Daily automatic backups now run at **03:15 IST**, retained for 14 days.

---

## ✅ PART F — Verify everything works

Open `https://YOUR-DOMAIN.com` in a browser. You should see the BookTalent homepage.

Log in with your existing account (data was restored from the dump). If you don't remember your password, log in as admin (`admin@booktalent.com / Admin@123`) and reset it.

Quick health checks:

```bash
# All services running?
sudo systemctl status mongod redis nginx booktalent-backend

# API works?
curl -sI https://YOUR-DOMAIN.com/api/healthz

# Login works?
curl -s -X POST https://YOUR-DOMAIN.com/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@booktalent.com","password":"Admin@123"}'
```

---

## 🔄 Future updates (after any code change on Emergent)

1. On Emergent, click **"Save to GitHub"** — pushes new code
2. On your VPS, one command:

   ```bash
   sudo /opt/booktalent/deploy/scripts/deploy.sh
   ```

That's it. It pulls the latest, reinstalls dependencies if changed, rebuilds the frontend, and restarts the backend.

---

## 🔧 Common problems & fixes

| Problem | Fix |
|---|---|
| `502 Bad Gateway` | Backend not running → `sudo systemctl status booktalent-backend` |
| `403 Forbidden` from Nginx | SELinux blocking → `sudo setsebool -P httpd_can_network_connect 1` |
| MongoDB won't start | `sudo journalctl -u mongod --since "5 min ago"` |
| Chat WebSocket dead | Nginx config missing WebSocket block — reinstall from `/opt/booktalent/deploy/nginx.conf` |
| Certbot fails DNS check | Wait 15 min for DNS propagation → `dig YOUR-DOMAIN.com +short` |
| `pip install` fails on Python 3.11 | `sudo dnf install python3.11-devel gcc` (build tools missing) |
| `yarn build` runs out of memory | Add swap: `sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 && sudo mkswap /swapfile && sudo swapon /swapfile` |

---

## 🆘 If you get stuck

Copy the exact error message + the command you ran, paste it back to the Emergent chat. I'll diagnose and give you the next command instantly. Don't guess — errors on production servers often look scary but usually have a 1-line fix.

**Golden rule:** never delete files or run `rm -rf` on anything unless I tell you exactly what to delete. It's very hard to recover.

---

You've got this. Take a breath, go slow, and paste any error back to me. 🚀
