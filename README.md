# Zimbra Email Automation

FastAPI boilerplate for connecting to a Zimbra server with **admin credentials**, enumerating mailboxes, and pulling messages for automation workflows.

## How it works

Zimbra exposes a SOAP API. This project uses the standard admin + mail flow:

1. **Admin auth** — `AuthRequest` against `/service/admin/soap` (port `7071`)
2. **List accounts** — `GetAllAccountsRequest`
3. **Impersonate mailbox** — `DelegateAuthRequest` to get a user-scoped token
4. **Search messages** — paginated `SearchRequest` on `/service/soap`
5. **Fetch one message** — `GetMsgRequest` when you need full body content

```
Admin credentials
       │
       ▼
┌──────────────────┐     GetAllAccounts      ┌─────────────┐
│  Admin SOAP API  │ ──────────────────────► │  Accounts   │
│  :7071           │                         └──────┬──────┘
└────────┬─────────┘                                │
         │ DelegateAuth (per account)                │
         ▼                                           ▼
┌──────────────────┐     Search + GetMsg     ┌─────────────┐
│  Mail SOAP API   │ ◄────────────────────── │  Messages   │
│  :443            │                         └─────────────┘
└──────────────────┘
```

## Quick start

### Backend (FastAPI)

```bash
cd ~/dev/zimbra-email-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Zimbra host, admin credentials, and DATABASE_URL
docker compose up -d postgres
uvicorn app.main:app --reload
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for Swagger UI.

### Frontend (Angular inbox UI)

```bash
cd frontend
npm install
npm start
```

Open [http://localhost:4200](http://localhost:4200). The dev server proxies `/api` to FastAPI on port 8000.

**Inbox workflow:** choose a mailbox from the dropdown → browse all that user's emails → click a message to view full details, automation metadata, and related messages by subject.

## API endpoints (Swagger)

All routes are under `/api/v1` and documented at `/docs`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/system/health` | API + Zimbra health |
| `GET` | `/api/v1/system/test-connection` | Test admin login |
| `GET` | `/api/v1/users` | **List all mail users** |
| `GET` | `/api/v1/users/{email}` | Get one user |
| `GET` | `/api/v1/users/{email}/inbox` | **View user inbox** (paginated) |
| `GET` | `/api/v1/users/{email}/messages` | Search messages |
| `GET` | `/api/v1/users/{email}/messages/{id}` | Get full message |
| `GET` | `/api/v1/users/{email}/folders` | List mailbox folders |
| `POST` | `/api/v1/sync` | Bulk sync all users |
| `POST` | `/api/v1/sync/users/{email}` | Sync one user |
| `GET` | `/api/v1/local/users/{email}/messages` | Cached messages from PostgreSQL |
| `GET` | `/api/v1/local/users/{email}/messages/{id}` | Cached message detail |
| `GET` | `/api/v1/local/users/{email}/messages/{id}/metadata` | Automation metadata |
| `GET` | `/api/v1/local/users/{email}/stats` | Local sync statistics |
| `GET` | `/api/v1/local/users/{email}/analysis-runs` | Automation run history |
| `POST` | `/api/v1/automation/users/{email}/messages/{id}/run` | Run automation on one message |
| `GET` | `/api/v1/agent/training` | Get global agent training text |
| `PUT` | `/api/v1/agent/training` | Save global agent training text |

Encode `@` as `%40` in email paths (e.g. `mayank.gautam%40mail.gkhair.com`).

### Examples

List users:

```bash
curl http://localhost:8000/api/v1/users
```

View inbox:

```bash
curl "http://localhost:8000/api/v1/users/mayank.gautam%40mail.gkhair.com/inbox?limit=20"
```

Copy `.env.example` to `.env` and set:

| Variable | Description |
|---|---|
| `ZIMBRA_HOST` | Zimbra hostname (no scheme) |
| `ZIMBRA_ADMIN_PORT` | Admin SOAP port (default `7071`) |
| `ZIMBRA_MAIL_PORT` | Mail SOAP port (default `443`) |
| `ZIMBRA_ADMIN_USER` | Admin email, e.g. `admin@example.com` |
| `ZIMBRA_ADMIN_PASSWORD` | Admin password |
| `ZIMBRA_VERIFY_SSL` | Set `true` in production |
| `ZIMBRA_DOMAIN_FILTER` | Optional domain name to limit account listing |
| `ZIMBRA_SEARCH_QUERY` | Default search, e.g. `in:anywhere` or `in:inbox` |
| `DATABASE_URL` | PostgreSQL connection string (default: `postgresql://zimbra:zimbra_dev@localhost:5432/zimbra_automation`) |

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health |
| `GET` | `/emails/accounts` | List all mail accounts |
| `POST` | `/emails/sync` | Pull messages from all (or one) mailbox |
| `GET` | `/emails/accounts/{email}` | Pull messages for one account |
| `GET` | `/emails/accounts/{email}/messages/{id}` | Fetch a single message |

### Examples

List accounts:

```bash
curl http://localhost:8000/emails/accounts
```

Sync all mailboxes (start with a limit while testing):

```bash
curl -X POST "http://localhost:8000/emails/sync?max_accounts=1&query=in:inbox"
```

Sync one mailbox:

```bash
curl -X POST "http://localhost:8000/emails/sync?account=user@example.com"
```

## CLI export (no server)

```bash
python scripts/export_emails.py --max-accounts 1 --output data/export.json
```

## Project layout

```
app/
  main.py                 # FastAPI entrypoint
  config.py               # Environment settings
  api/routes/             # HTTP routes (users, mailboxes, sync, agent, local)
  db/email_repository.py  # PostgreSQL persistence
  models/schemas.py       # Pydantic response models
  services/
    email_sync.py         # Orchestration layer
    scheduled_pipeline.py # Poll + sync + AI pipeline
    zimbra/               # SOAP clients
frontend/                 # Angular inbox UI (Bootstrap)
docker-compose.yml        # Local PostgreSQL
scripts/
  export_emails.py        # Standalone JSON export
```

## Notes

- **Admin rights required**: `DelegateAuth` needs a global/domain admin account.
- **Large tenants**: Use `max_accounts`, `ZIMBRA_DOMAIN_FILTER`, or narrower `query` values while developing.
- **Self-signed certs**: `ZIMBRA_VERIFY_SSL=false` is fine for lab setups; enable verification in production.
- **Carbonio/Zimbra versions**: SOAP namespaces are stable across Zimbra 8.x/9.x and Carbonio; adjust ports if your install differs.

## Next steps for automation

- Persist exports to Postgres/S3 instead of returning JSON inline
- Add webhooks or a task queue (Celery/ARQ) for scheduled sync
- Filter by date with queries like `after:2025/01/01 in:inbox`
- Parse MIME bodies from `GetMsg` for attachment extraction
