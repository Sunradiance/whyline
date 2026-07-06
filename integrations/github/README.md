# Whyline × GitHub / GitLab

Capture decisions from PR discussions, issue comments, and ADRs.

## GitHub webhook

1. Repo → **Settings** → **Webhooks** → Add webhook
2. URL: `https://YOUR_HOST/api/integrations/github/webhook`
3. Secret: same as `GITHUB_WEBHOOK_SECRET` in `.env`
4. Events: **Issue comments**, **Pull request reviews**, **Pull request review comments**

```env
GITHUB_WEBHOOK_SECRET=your-github-webhook-secret
```

## GitLab

POST to `/api/integrations/gitlab/webhook` with header `X-Gitlab-Token: <GITHUB_WEBHOOK_SECRET>` (or set a dedicated secret later).

Persists with repo/issue/PR URL as provenance. Deduped per comment ID.