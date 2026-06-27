# LangGraph Email Automation Demo

Client demo combining **LangGraph Builder** (visual architecture) with the **FastAPI agent** (live Zimbra execution).

## Prerequisites

- Python 3.11+ with project dependencies installed
- Node.js 18+ and Yarn (for LangGraph Builder)
- Valid `.env` with Zimbra admin credentials and `OPENAI_API_KEY`

```bash
cd ~/dev/zimbra-email-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with Zimbra + OpenAI credentials
```

## Quick start (both surfaces)

```bash
./scripts/run-demo.sh
```

This starts:

| Service | URL | Purpose |
|---------|-----|---------|
| LangGraph Builder | http://localhost:3000 | Visual graph canvas for architecture walkthrough |
| FastAPI + demo UI | http://localhost:8000/demo | Live agent execution against Zimbra |
| Swagger API docs | http://localhost:8000/docs | API reference for integrators |

## 10-minute client presentation script

| Step | What to show | URL |
|------|-------------|-----|
| 1 | Open LangGraph Builder and walk through each node and conditional route | http://localhost:3000 |
| 2 | Open **Generate Code** and show `spec.yml` matches [`app/graphs/spec/email_agent.yml`](../app/graphs/spec/email_agent.yml) | Builder UI |
| 3 | Switch to the live demo, select a mailbox with recent inbox activity | http://localhost:8000/demo |
| 4 | Click **Run agent** and highlight nodes lighting up as SSE events stream | Demo UI |
| 5 | Show classifications, summary, draft reply (suggestions only — no send/archive) | Demo log panel |
| 6 | Open Swagger for API consumers | http://localhost:8000/docs |

## Load the graph in LangGraph Builder canvas

1. Start Builder: `./scripts/start-builder.sh`
2. Open http://localhost:3000
3. Click **Templates** (top toolbar)
4. Select **Zimbra Email Orchestrator**

You will see the full 15-node graph with 3 conditional routers and a support-agent tool loop.

## Architecture

```
ingest_mailbox → enrich_messages → classify_intent → route_intent
  ├─ urgent_escalation ────────────────┐
  ├─ compliance_review ────────────────┤
  ├─ sales_pipeline ───────────────────┤
  ├─ support_agent ⇄ zimbra_tools → draft_support_reply ─┤
  ├─ newsletter_batch ─────────────────┤
  └─ general_briefing ─────────────────┘
                                       └→ merge_insights → quality_review → route_quality
                                              ├─ refine_output ──┐
                                              └──────────────────┴→ format_executive_report
```

Regenerate stubs after editing the YAML:

```bash
langgraph-gen app/graphs/spec/email_agent.yml \
  -o app/agents/email_agent.py \
  --implementation app/agents/graph_stub_impl.py
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/agent/schema` | Graph nodes/edges for demo UI |
| `POST` | `/api/v1/agent/run` | Synchronous agent run |
| `POST` | `/api/v1/agent/stream` | SSE stream with node events |
| `GET` | `/api/v1/agent/sessions/{thread_id}` | Inspect checkpoint state |

Example:

```bash
curl -X POST http://localhost:8000/api/v1/agent/run \
  -H "Content-Type: application/json" \
  -d '{"user_email":"user@example.com","limit":5,"instruction":"focus on invoices"}'
```

## Demo safety

- Default inbox limit: 10 messages (`AGENT_INBOX_LIMIT`)
- Read-only: no send, delete, or archive actions against Zimbra
- `draft_reply` produces suggestions only
- Pre-flight: `GET /api/v1/system/test-connection` before the client call

## Manual setup (without run script)

**Terminal 1 — LangGraph Builder**

```bash
cd demo/langgraph-builder   # cloned on first run by run-demo.sh
yarn install
yarn dev
```

**Terminal 2 — FastAPI**

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `OPENAI_API_KEY is not configured` | Set key in `.env` and restart uvicorn |
| Zimbra health shows disconnected | Verify admin credentials and `ZIMBRA_HOST` |
| Builder graph doesn't match code | Reconcile canvas with `app/graphs/spec/email_agent.yml` |
| No users in dropdown | Confirm admin can list accounts via `GET /api/v1/users` |
