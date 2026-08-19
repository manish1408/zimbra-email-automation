# Zimbra Mail Explorer (Angular)

Bootstrap-themed inbox UI for browsing Zimbra mailboxes via the FastAPI backend.

## Development

```bash
npm install
npm start
```

Runs at [http://localhost:4200](http://localhost:4200) with API proxy to `http://localhost:8000`.

To use the production API at [http://176.123.3.2](http://176.123.3.2/) instead of a local backend:

```bash
npm run start:remote
```

## Production build

```bash
npm run build
```

Output: `dist/frontend/`. Serve static files and ensure `/api` routes to the FastAPI backend, or set `apiBaseUrl` in `src/environments/environment.ts`.

## Pages

| Route | Description |
|---|---|
| `/inbox` | User picker — choose a mailbox |
| `/inbox/:userEmail` | 3-pane inbox for that user |
| `/agent` | Agent training (global instructions for automation) |
| `/settings` | Connection test, bulk sync, DB stats |
