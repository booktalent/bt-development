# BookTalent — VPS Deployment Guide

Yeh app **VPS-native** hai — koi Emergent-only cloud dependency nahi. Jo preview
mein chalta hai wahi VPS pe identically chalega.

---

## Prerequisites

- Ubuntu 22.04+ / Debian 12+ VPS
- Python 3.11+, Node 18+, MongoDB 6+, Nginx, Supervisor
- Domain pointing to VPS IPv4
- Gmail account with App Password (for SMTP)
- Easebuzz merchant account (for payments)

---

## 1. Clone + install

```bash
git clone <your-repo> /app
cd /app/backend
pip install -r requirements.txt

cd /app/frontend
yarn install
yarn build
```

---

## 2. Configure environment

### Backend
```bash
cp /app/backend/.env.example /app/backend/.env
nano /app/backend/.env
```

Fill in **required** values:
- `JWT_SECRET` → `openssl rand -hex 32`
- `ADMIN_PASSWORD` → strong password (change after first login)
- `SMTP_PASSWORD` → Gmail App Password (16 chars, no spaces)
- `EASEBUZZ_KEY` + `EASEBUZZ_SALT` → from Easebuzz dashboard
- `EASEBUZZ_LOCAL_IPV4` → your VPS's whitelisted IPv4
- `FRONTEND_URL` + `BACKEND_PUBLIC_URL` → `https://yourdomain.com`

### Frontend
```bash
echo 'REACT_APP_BACKEND_URL=https://yourdomain.com' > /app/frontend/.env
cd /app/frontend && yarn build
```

---

## 3. Directory setup

```bash
# Video storage
sudo mkdir -p /app/uploads
sudo chown -R $(whoami):$(whoami) /app/uploads
sudo chmod 755 /app/uploads

# Log directories (if not already exist)
sudo mkdir -p /var/log/supervisor
```

---

## 4. Nginx config

`/etc/nginx/sites-available/booktalent`:

```nginx
server {
    listen 80;
    server_name booktalent.in www.booktalent.in;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name booktalent.in www.booktalent.in;

    # SSL (use certbot to auto-issue)
    ssl_certificate /etc/letsencrypt/live/booktalent.in/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/booktalent.in/privkey.pem;

    client_max_body_size 1200M;   # 1GB video uploads

    # Frontend static build
    root /app/frontend/build;
    index index.html;

    # API → FastAPI on 8001
    location /api/ {
        proxy_pass http://127.0.0.1:8001/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Local video storage — direct disk streaming
    location /uploads/ {
        alias /app/uploads/;
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header Access-Control-Allow-Origin "*";
        add_header Accept-Ranges bytes;
    }

    # React SPA — everything else
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

SSL setup:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d booktalent.in -d www.booktalent.in
sudo nginx -t && sudo systemctl reload nginx
```

---

## 5. Supervisor config

`/etc/supervisor/conf.d/booktalent.conf`:

```ini
[program:backend]
command=uvicorn server:app --host 0.0.0.0 --port 8001 --workers 2
directory=/app/backend
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/backend.err.log
stdout_logfile=/var/log/supervisor/backend.out.log
environment=PYTHONUNBUFFERED="1"
user=root
```

Reload:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start backend
```

---

## 6. MongoDB restore (from dump)

```bash
# Download dump from preview
curl -o dump.gz "<preview-dump-url>"

# Restore
mongorestore --archive=dump.gz --gzip --nsInclude='booktalent.*' --drop
```

---

## 7. Health check

```bash
# 1. Backend up?
curl https://booktalent.in/api/

# 2. Storage initialised?
sudo tail -n 20 /var/log/supervisor/backend.err.log | grep "Local object storage"
# Expected: Local object storage ready at /app/uploads

# 3. SMTP working?
sudo tail -n 20 /var/log/supervisor/backend.err.log | grep "Gmail SMTP configured"
# Expected: Gmail SMTP configured host=smtp.gmail.com port=587 user=manager@booktalent.in

# 4. Test video upload from browser → artist dashboard → media upload

# 5. Test payment from booking flow — should redirect to Easebuzz hosted page
```

---

## What runs identically on preview & VPS

| Feature | Preview | VPS | Notes |
|---|---|---|---|
| Auth (JWT + OTP) | ✅ | ✅ | Same code |
| Gmail SMTP emails | ✅ | ✅ | Uses App Password |
| Video upload (up to 1GB) | ✅ | ✅ | Local disk on VPS, was Emergent-only earlier |
| Easebuzz payments | ✅ | ✅ | IPv4 forced + absolute callback URLs |
| Booking reminders | ✅ | ✅ | Runs on FastAPI startup task |
| Rate limiting | ✅ | ✅ | In-memory sliding window |
| AI search / planner | ✅ (better) | ✅ (rule-based fallback) | Needs `EMERGENT_LLM_KEY` for AI mode; otherwise falls back to deterministic rules — no crash |
| DB dump download | ✅ | 🔒 (off by default) | Set `DUMP_DOWNLOAD_TOKEN` env when needed, unset otherwise |

---

## Troubleshooting

### Video upload fails
```bash
# Is the storage dir writable?
sudo -u <backend-user> touch /app/uploads/test && sudo rm /app/uploads/test
# Nginx serves it?
echo hi > /app/uploads/test.txt && curl https://booktalent.in/uploads/test.txt && rm /app/uploads/test.txt
```

### Emails not sending
```bash
# Test SMTP directly
python3 -c "
import smtplib, ssl
with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as s:
    s.starttls(context=ssl.create_default_context())
    s.login('manager@booktalent.in', 'YOUR_APP_PASSWORD')
    print('OK')
"
```
Fails? → Contabo firewall blocking port 587, or wrong App Password.

### Easebuzz "Invalid value for surl"
Usually `BACKEND_PUBLIC_URL` not set or set to a relative URL. Should be
`https://booktalent.in` (no trailing slash).

### Easebuzz "Request Invalid for the merchant"
Egress IP mismatch. Confirm VPS's public IPv4 (`curl ifconfig.me`) matches
what Easebuzz whitelisted, and `EASEBUZZ_LOCAL_IPV4` is set to it.

---

## Backup strategy

```bash
# Daily 3 AM: DB + uploads to backup dir
sudo crontab -e
```
Add:
```
0 3 * * * mongodump --db=booktalent --archive=/backups/db-$(date +\%Y\%m\%d).archive.gz --gzip
0 3 * * * rsync -a --delete /app/uploads/ /backups/uploads/
0 4 * * 0 find /backups -name 'db-*.archive.gz' -mtime +30 -delete
```

Weekly offsite copy (rclone → S3/GDrive) recommended.
