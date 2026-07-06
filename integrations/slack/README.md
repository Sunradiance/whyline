# Whyline × Slack

Capture full Slack **threads** into server-side SQLite — not per-message noise.

## How capture works

1. React with **📌** (`pushpin`) on any message in a decision thread
2. Whyline fetches the **entire thread** via `conversations.replies`
3. LLM extracts one decision → persists to SQLite with Slack permalink

Alternatively: **@Whyline** in a thread triggers the same flow.

Re-ingesting the same thread is deduped by `slack:{channel}:{thread_ts}`.

## 1. Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → From manifest
2. Paste `app_manifest.json` from this folder (update `request_url` to your public URL or use ngrok for local dev)
3. Install app to workspace
4. Invite the bot to channels where decisions happen

## 2. Configure `.env`

```env
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
```

Both are **required** for the events endpoint — unsigned requests are rejected.

## 3. Events URL

```
https://YOUR_HOST/api/integrations/slack/events
```

Local dev with ngrok:

```bash
ngrok http 8793
# Use https://xxxx.ngrok.io/api/integrations/slack/events
```

## 4. Slash command `/whyline`

```
/whyline We decided monthly-only in DACH until legal clears VAT
/whyline https://yourteam.slack.com/archives/C123/p1234567890123456
```

Request URL: `/api/integrations/slack/commands`

## 5. Bot events (manifest)

- `reaction_added` — react 📌 on a thread
- `app_mention` — @Whyline in a thread

## 5. Manual capture (no Events API)

**API** (requires session or `X-Whyline-Key`):

```bash
curl -X POST http://127.0.0.1:8793/api/integrations/slack/capture \
  -H "Content-Type: application/json" \
  -H "X-Whyline-Key: YOUR_KEY" \
  -d '{"channel":"C123","thread_ts":"1234567890.123456"}'
```

**UI:** Capture → Slack thread JSON (paste `conversations.replies` output).

## Scopes required

`channels:history`, `groups:history`, `channels:read`, `groups:read`, `reactions:read`