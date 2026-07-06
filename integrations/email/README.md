# Whyline × Email (`decisions@`)

Universal capture — CC or forward any thread to your decisions alias.

## Setup

1. Create `decisions@yourco.com` (or use Mailgun/SendGrid inbound parse)
2. Forward inbound mail to Whyline:

```
POST https://YOUR_HOST/api/integrations/email/ingest
Header: X-Whyline-Secret: <EMAIL_WEBHOOK_SECRET>
```

3. `.env`:

```env
EMAIL_WEBHOOK_SECRET=your-random-secret
```

## Payload (JSON)

```json
{
  "subject": "Re: Annual billing in Germany",
  "body": "We decided monthly-only until legal clears VAT...",
  "from": "cfo@yourco.com",
  "message_id": "<unique@mail>",
  "url": ""
}
```

Mailgun/SendGrid inbound webhooks are auto-normalized (`body-plain`, `stripped-text`, etc.).

## Manual test

```bash
curl -X POST http://127.0.0.1:8793/api/integrations/email/ingest \
  -H "Content-Type: application/json" \
  -H "X-Whyline-Secret: YOUR_SECRET" \
  -d '{"subject":"Pricing decision","body":"We will not offer annual billing in DACH until Q3.","from":"legal@co.com","message_id":"test-1"}'
```

Deduped by `message_id`.