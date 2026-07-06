# Whyline × Atlassian (Jira + Confluence)

Extract decisions from Jira issues and comments.

## Jira Automation Webhook

1. In Jira → **Project settings** → **Automation**
2. Create rule: **When**: Issue updated or Comment added
3. **Then**: Send web request

**URL:**

```
https://YOUR_HOST/api/integrations/atlassian/jira
```

**Headers:**

```
Content-Type: application/json
X-Whyline-Secret: your-secret-from-env
```

**Body (example):**

```json
{
  "issueKey": "{{issue.key}}",
  "summary": "{{issue.summary}}",
  "description": "{{issue.description}}",
  "comment": "{{comment.body}}",
  "author": "{{user.displayName}}",
  "project": "{{project.name}}"
}
```

## Configure `.env`

```env
ATLASSIAN_WEBHOOK_SECRET=your-random-secret-here
```

## Local test

```bash
curl -X POST http://localhost:8793/api/integrations/atlassian/jira \
  -H "Content-Type: application/json" \
  -H "X-Whyline-Secret: your-secret" \
  -d '{"issueKey":"PROD-42","summary":"Kill Teams feature","comment":"CEO agreed — reallocating 2 engineers","author":"Product Lead"}'
```

Persists directly to SQLite with Jira key + URL provenance. Deduped by `jira:{issueKey}`.

## Confluence (manual)

Export page text → Whyline **Capture** → **Extract from text**.

Future: Confluence webhook via same `/jira` endpoint with `source: confluence` field.