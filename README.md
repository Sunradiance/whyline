# Whyline — Company Memory Engine

<div align="center">

### Your company forgot why it decided everything.

The Slack thread from March nobody can find.  
The pricing rule nobody can explain.  
The vendor you rejected — for reasons that left with Sarah.

**Every quarter, someone asks *"wait, why do we do it this way?"***  
**Every quarter, you pay six people for two weeks to re-discover what you already decided.**

That's not a documentation problem. That's **institutional amnesia**.

---

**Whyline is the why layer that actually ships.**

Server-side SQLite your whole team shares — not one browser tab's memory.  
BM25 retrieval — not your entire corpus rammed into every prompt.  
Receipts on every answer — Slack permalinks, doc links, Jira keys.

Ask: *"Why don't we support annual billing in Germany?"*  
Get the trail. Not keyword soup. **The actual reasoning.**

Capture from **Slack** (📌 or `/whyline`), **email** (`decisions@`), **meeting transcripts**, **Notion/Confluence/GDocs**, **GitHub PRs**, **Teams**, **Linear**, **Jira** — or just talk to it through **MCP** in Cursor.

Clone it. Plug your API key. Running in 60 seconds.  
**Free. Local. Yours.**

[Ask why](#quick-start) · [Capture](#features) · [MCP + Cursor](#mcp--cursor)

</div>

---

## What changed in v2

We stopped pretending IndexedDB was "company memory." v2 is boring infrastructure that works:

| Layer | What it does |
|-------|----------------|
| **SQLite** (`data/whyline.db`) | Shared decision store — survives browser clears, works for the whole team |
| **BM25 retrieval** | Top-k decisions per question — scales past a few hundred entries |
| **Provenance** | Every decision links back — Slack, email, doc URL, Jira key |
| **Thread-level capture** | Full Slack threads, not per-message garbage |
| **MCP** | `whyline_ask` / `whyline_extract` / `whyline_search` — Cursor becomes a client |

`.env` is never served. Default bind: `127.0.0.1`. Webhook secrets required, not optional.

---

## Quick start

```bash
git clone https://github.com/Sunradiance/whyline.git
cd whyline
cp .env.example .env
# Edit .env — add LLM_API_KEY
npm run setup
npm run dev
```

Open **http://127.0.0.1:8793**

`npm run dev` uses Flask's built-in server — fine for local use. For a shared team deployment, use a production WSGI server (atomic capture claims make multi-worker safe):

```bash
pip install gunicorn
gunicorn -w 4 -b 127.0.0.1:8793 'app:create_app()' --chdir backend
```

On Windows: `pip install waitress` then `waitress-serve --listen=127.0.0.1:8793 --call app:create_app` from `backend/`.

### Minimum `.env`

```env
LLM_API_KEY=gsk_...
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL_NAME=qwen/qwen3-32b
WHYLINE_HOST=127.0.0.1
```

---

## MCP + Cursor

Whyline is an MCP server. Every AI assistant in your IDE can query institutional memory — and write to it.

**Tools:** `whyline_ask` · `whyline_extract` · `whyline_search`

### One-time setup

```bash
npm run setup   # if you haven't already
```

Copy `.cursor/mcp.json.example` → `.cursor/mcp.json` (or use the included project config) and adjust the path.

Restart Cursor → **Settings → MCP** → enable **whyline**.

Now ask in chat: *"Whyline: why did we reject Acme CDN?"* — it hits your local SQLite corpus with receipts.

Details: [`integrations/mcp/README.md`](integrations/mcp/README.md)

---

## Features

- **Ask Why** — retrieval-backed answers with validated `decisionIds` + clickable receipts
- **Decision registry** — search, filter, supersede lifecycle
- **Capture** — transcripts, email, docs (Notion/Confluence/GDocs), Slack/Teams threads
- **Slack** — `/whyline` slash command + 📌 reaction → full thread capture
- **decisions@** — CC email alias → extract + persist ([setup](integrations/email/README.md))
- **Jira / GitHub / Linear / Teams / Salesforce** — webhook ingest with provenance
- **Memory Brief** — export for leadership

Demo seed data: DACH billing, Acme CDN, Teams feature kill.

---

## Integrations (live)

| Source | Endpoint | Auth |
|--------|----------|------|
| **Email** `decisions@` | `POST /api/integrations/email/ingest` | `X-Whyline-Secret` |
| **Slack** `/whyline` + 📌 | `/api/integrations/slack/commands` + `/events` | Slack signature |
| **Meeting transcript** | `POST /api/integrations/transcript/ingest` | session / API key |
| **Notion / Confluence / GDocs** | `POST /api/integrations/doc/ingest` | session / API key |
| **GitHub / GitLab** | `POST /api/integrations/github/webhook` | `X-Hub-Signature-256` |
| **MS Teams** | `POST /api/integrations/teams/ingest` | `X-Whyline-Secret` |
| **Linear** | `POST /api/integrations/linear/webhook` | `X-Whyline-Secret` |
| **Jira** | `POST /api/integrations/atlassian/jira` | `X-Whyline-Secret` |
| **Salesforce** | `POST /api/integrations/salesforce/webhook` | `X-Whyline-Secret` |
| **MCP** | `npm run mcp` | local stdio |

Docs: [`integrations/email`](integrations/email/README.md) · [`integrations/slack`](integrations/slack/README.md) · [`integrations/mcp`](integrations/mcp/README.md) · [`integrations/github`](integrations/github/README.md)

---

## Tests

```bash
npm run test
```

77 tests · CI on push to `main`

---

## Stack family

| App | Port | Layer |
|-----|------|-------|
| [Stratum](https://github.com/Sunradiance/stratum) | 8791 | Strategic assumptions |
| [Keepline](https://github.com/Sunradiance/keepline) | 8792 | Committed burn |
| **Whyline** | 8793 | Institutional decisions |

Three layers. One founder who got tired of re-litigating the same decisions.

---

## Support (voluntary)

MIT licensed. No paywall. Ever.

If you like this project, please support us with **SOL** on Solana:

```
B4ZFerkb7DctTLabgzh3F8aGhJF7EVDxcnLz6e2zqZwb
```

Running locally? Set `SOL_DONATION_ADDRESS` in `.env` (or use **◎ Support with SOL** in the app once configured). Voluntary tips only — Solana chain, SOL token.

---

<div align="center">

**Whyline** — decisions remembered.  
*The why layer your company never had — now with receipts.*

</div>