# Deployment Guide

Production server for this project runs on Ubuntu at **176.123.3.2**.

| Service | URL |
|---|---|
| Inbox UI | http://176.123.3.2/ |
| API (via nginx) | http://176.123.3.2/api/v1/ |
| Swagger docs | http://176.123.3.2/docs |
| API direct | http://176.123.3.2:8000/docs |

---

## Server layout

| Item | Location |
|---|---|
| App directory | `/opt/zimbra-email-automation` |
| Environment file | `/opt/zimbra-email-automation/.env` |
| Python venv | `/opt/zimbra-email-automation/.venv` |
| Frontend build | `/opt/zimbra-email-automation/frontend/dist/frontend/browser` |
| PostgreSQL | Docker container `zimbra-automation-db` (port 5432) |
| Nginx config | `/etc/nginx/sites-available/zimbra-automation` |

### Systemd services

| Service | Description |
|---|---|
| `zimbra-api` | FastAPI backend (uvicorn on port 8000) |
| `zimbra-mail-poller` | Background inbox poller + automation |
| `nginx` | Serves frontend, proxies `/api/` to backend |

---

## Prerequisites (local machine)

Install `sshpass` if you deploy with password auth (macOS):

```bash
brew install hudochenkov/sshpass/sshpass
```

Set these variables in your shell for convenience:

```bash
export DEPLOY_HOST=176.123.3.2
export DEPLOY_USER=root
export APP_DIR=/opt/zimbra-email-automation
export PROJECT_DIR=~/dev/zimbra-email-automation   # adjust to your local path
```

Prefer SSH key auth over passwords when possible:

```bash
ssh-copy-id root@176.123.3.2
# After keys work, drop sshpass from the commands below and use plain ssh/rsync/scp
```

---

## Quick redeploy (most common)

Run from your **local machine** after making code changes.

### 1. Sync backend + config

```bash
cd "$PROJECT_DIR"

rsync -avz --delete \
  --exclude '.venv' --exclude 'venv' --exclude 'node_modules' --exclude '.git' \
  --exclude 'data' --exclude 'logs' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'frontend/dist' --exclude '.DS_Store' \
  -e "ssh -o StrictHostKeyChecking=no" \
  ./ ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/

scp -o StrictHostKeyChecking=no .env ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/.env
```

With password auth, prefix rsync/scp with `sshpass -p 'YOUR_PASSWORD'` or use `-e "sshpass -p '...' ssh ..."`.

### 2. Rebuild frontend locally and sync

The server has Node 18; Angular 20 requires Node 20+. **Always build the frontend on your local machine.**

```bash
cd "$PROJECT_DIR/frontend"
npm run build

rsync -avz \
  -e "ssh -o StrictHostKeyChecking=no" \
  dist/ ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/frontend/dist/
```

### 3. Install Python deps (only when `requirements.txt` changed)

```bash
ssh ${DEPLOY_USER}@${DEPLOY_HOST} \
  "${APP_DIR}/.venv/bin/pip install -r ${APP_DIR}/requirements.txt"
```

### 4. Restart services

```bash
ssh ${DEPLOY_USER}@${DEPLOY_HOST} \
  "systemctl restart zimbra-api zimbra-mail-poller nginx"
```

### 5. Verify

```bash
curl http://${DEPLOY_HOST}/api/v1/system/health
curl -o /dev/null -w "Frontend: HTTP %{http_code}\n" http://${DEPLOY_HOST}/
```

Expected health response:

```json
{"status":"ok","zimbra_host":"mail.gkhair.com","zimbra_connected":true}
```

---

## One-liner redeploy script

Copy-paste this after setting `PROJECT_DIR`, `DEPLOY_HOST`, and `DEPLOY_USER`:

```bash
cd "$PROJECT_DIR" && \
rsync -avz --delete \
  --exclude '.venv' --exclude 'node_modules' --exclude '.git' \
  --exclude 'data' --exclude 'logs' --exclude '__pycache__' \
  --exclude 'frontend/dist' --exclude '.DS_Store' \
  -e "ssh -o StrictHostKeyChecking=no" \
  ./ ${DEPLOY_USER}@${DEPLOY_HOST}:/opt/zimbra-email-automation/ && \
scp -o StrictHostKeyChecking=no .env ${DEPLOY_USER}@${DEPLOY_HOST}:/opt/zimbra-email-automation/.env && \
cd frontend && npm run build && \
rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
  dist/ ${DEPLOY_USER}@${DEPLOY_HOST}:/opt/zimbra-email-automation/frontend/dist/ && \
ssh ${DEPLOY_USER}@${DEPLOY_HOST} "systemctl restart zimbra-api zimbra-mail-poller nginx" && \
curl -s http://${DEPLOY_HOST}/api/v1/system/health
```

---

## Backend-only redeploy

When you changed only Python code (no frontend, no new pip packages):

```bash
cd "$PROJECT_DIR"

rsync -avz --delete \
  --exclude '.venv' --exclude 'node_modules' --exclude '.git' \
  --exclude 'data' --exclude 'logs' --exclude '__pycache__' \
  --exclude 'frontend' --exclude '.DS_Store' \
  -e "ssh -o StrictHostKeyChecking=no" \
  ./app ./scripts ./config requirements.txt docker-compose.yml \
  ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/

scp -o StrictHostKeyChecking=no .env ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/.env

ssh ${DEPLOY_USER}@${DEPLOY_HOST} "systemctl restart zimbra-api zimbra-mail-poller"
```

---

## Frontend-only redeploy

When you changed only Angular code:

```bash
cd "$PROJECT_DIR/frontend"
npm run build

rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
  dist/ ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/frontend/dist/

ssh ${DEPLOY_USER}@${DEPLOY_HOST} "systemctl reload nginx"
```

---

## Mail poller control

The mail poller runs as systemd service `zimbra-mail-poller` on the server. By default it polls **all active Zimbra mailboxes** each cycle (same sync + automation pipeline as before, but for every account). Control it from your **local machine** without SSH-ing manually.

### Setup (once)

```bash
cp deploy.env.example deploy.env
# Edit deploy.env — set DEPLOY_HOST, DEPLOY_USER, and optionally DEPLOY_PASSWORD
# Prefer SSH keys: ssh-copy-id root@176.123.3.2 and leave DEPLOY_PASSWORD empty
```

### Commands (local)

```bash
./scripts/remote-mail-poller.sh start      # start the poller
./scripts/remote-mail-poller.sh stop       # stop the poller
./scripts/remote-mail-poller.sh restart    # restart after config/code changes
./scripts/remote-mail-poller.sh status     # show systemd status
./scripts/remote-mail-poller.sh logs       # last 50 log lines
./scripts/remote-mail-poller.sh logs -f    # follow live logs (Ctrl+C to exit)
./scripts/remote-mail-poller.sh enable     # auto-start on server boot
./scripts/remote-mail-poller.sh disable    # do not auto-start on boot
```

### Commands (on the server)

If you are already SSH'd into the server:

```bash
cd /opt/zimbra-email-automation
./scripts/mail-poller-service.sh start
./scripts/mail-poller-service.sh stop
./scripts/mail-poller-service.sh status
./scripts/mail-poller-service.sh logs -f
```

Or use systemd directly:

```bash
systemctl start zimbra-mail-poller
systemctl stop zimbra-mail-poller
systemctl status zimbra-mail-poller
journalctl -u zimbra-mail-poller -f
```

---

## Service management (on the server)

SSH in:

```bash
ssh root@176.123.3.2
```

### Status

```bash
systemctl status zimbra-api zimbra-mail-poller nginx
docker ps
```

### Start / stop / restart

```bash
systemctl restart zimbra-api
systemctl restart zimbra-mail-poller
systemctl restart nginx

# Stop everything
systemctl stop zimbra-mail-poller zimbra-api
```

### Logs

```bash
# Follow API logs
journalctl -u zimbra-api -f

# Follow mail poller logs
journalctl -u zimbra-mail-poller -f

# Last 50 lines
journalctl -u zimbra-api -n 50 --no-pager
journalctl -u zimbra-mail-poller -n 50 --no-pager

# Nginx access/error logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### PostgreSQL

```bash
cd /opt/zimbra-email-automation

# Start/stop database
docker compose up -d postgres
docker compose stop postgres

# Check database is ready
docker compose exec postgres pg_isready -U zimbra -d zimbra_automation

# Connect to psql
docker compose exec postgres psql -U zimbra -d zimbra_automation
```

---

## Environment variables

Production config lives in `/opt/zimbra-email-automation/.env`. Key settings:

| Variable | Purpose |
|---|---|
| `ZIMBRA_HOST` | Zimbra mail server hostname |
| `ZIMBRA_ADMIN_USER` / `ZIMBRA_ADMIN_PASSWORD` | Admin credentials |
| `ZIMBRA_DOMAIN_FILTER` | Optional domain filter for account discovery (e.g. `mail.gkhair.com`) |
| `DATABASE_URL` | PostgreSQL connection (default: `postgresql://zimbra:zimbra_dev@localhost:5432/zimbra_automation`) |
| `SYNC_POLL_ALL_MAILBOXES` | `true` (default) = poll all active mailboxes; `false` = single-mailbox mode |
| `SYNC_TARGET_EMAIL` | Mailbox to poll when `SYNC_POLL_ALL_MAILBOXES=false` (debugging / legacy single-mailbox mode) |
| `SYNC_POLL_INTERVAL_SECONDS` | Poll interval (default 60) |
| `AUTOMATION_DRY_RUN` | `false` = live Zimbra moves/forwards |
| `LLM_PROVIDER` / `VASTAI_*` | LLM agent configuration |

After enabling multi-mailbox polling in production:

1. Set `SYNC_POLL_ALL_MAILBOXES=true` in `/opt/zimbra-email-automation/.env` (default).
2. `SYNC_TARGET_EMAIL` can remain but is ignored while polling all mailboxes.
3. Restart the poller: `systemctl restart zimbra-mail-poller`.
4. Verify logs show per-account poll lines: `journalctl -u zimbra-mail-poller -n 100 --no-pager`.

If you have many mailboxes, increase `SYNC_POLL_INTERVAL_SECONDS` if poll cycles start overlapping.

After editing `.env` locally, copy it up and restart:

```bash
scp .env root@176.123.3.2:/opt/zimbra-email-automation/.env
ssh root@176.123.3.2 "systemctl restart zimbra-api zimbra-mail-poller"
```

---

## Full fresh install (new server)

Use this only when setting up from scratch on a blank Ubuntu 24.04 server with Docker, Python 3.12, and nginx.

```bash
# 1. Sync project (from local machine)
rsync -avz --exclude '.venv' --exclude 'node_modules' --exclude '.git' \
  --exclude 'data' --exclude 'logs' --exclude 'frontend/dist' \
  ./ root@NEW_SERVER:/opt/zimbra-email-automation/

scp .env root@NEW_SERVER:/opt/zimbra-email-automation/.env

# 2. On the server
ssh root@NEW_SERVER
cd /opt/zimbra-email-automation

apt-get update && apt-get install -y python3-venv python3-pip nginx

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

docker compose up -d postgres

# 3. Build frontend locally, then rsync dist/ to server (see Quick redeploy)

# 4. Create systemd units (see /etc/systemd/system/zimbra-api.service on current server)
# 5. Configure nginx (see /etc/nginx/sites-available/zimbra-automation on current server)

systemctl daemon-reload
systemctl enable --now zimbra-api zimbra-mail-poller nginx
```

To copy systemd/nginx configs from the running server:

```bash
ssh root@176.123.3.2 "cat /etc/systemd/system/zimbra-api.service"
ssh root@176.123.3.2 "cat /etc/systemd/system/zimbra-mail-poller.service"
ssh root@176.123.3.2 "cat /etc/nginx/sites-available/zimbra-automation"
```

---

## Troubleshooting

### API not responding

```bash
ssh root@176.123.3.2
systemctl status zimbra-api
journalctl -u zimbra-api -n 30 --no-pager
curl http://127.0.0.1:8000/api/v1/system/health
```

Common causes: PostgreSQL container not running, bad `.env`, missing pip packages.

### Mail poller not syncing

Check `SYNC_POLL_ALL_MAILBOXES`, Zimbra connectivity, and per-account errors in logs:

```bash
journalctl -u zimbra-mail-poller -n 50 --no-pager
```

For single-mailbox debugging, set `SYNC_POLL_ALL_MAILBOXES=false` and `SYNC_TARGET_EMAIL` in `.env`, or run locally:

```bash
.venv/bin/python scripts/mail_poller.py --once --account user@example.com
```

Test Zimbra connectivity:

```bash
curl http://127.0.0.1:8000/api/v1/system/test-connection
```

### Frontend shows blank page or 404

- Confirm dist was synced: `ls /opt/zimbra-email-automation/frontend/dist/frontend/browser/`
- Check nginx root path matches the dist location
- Rebuild locally with `npm run build` and re-sync

### Database connection errors

```bash
docker ps                          # container should be running
docker compose logs postgres       # check for startup errors
docker compose up -d postgres      # restart if needed
systemctl restart zimbra-api
```

### Port already in use

```bash
ss -tlnp | grep -E '8000|80|5432'
```

---

## Security notes

- Do **not** commit `.env` to git — it contains Zimbra admin credentials and API tokens.
- Use SSH key authentication instead of password login for routine deploys.
- Consider restricting port 8000 with a firewall (nginx on port 80 is the public entry point).
- Set `ZIMBRA_VERIFY_SSL=true` in production if your Zimbra server has a valid TLS certificate.
