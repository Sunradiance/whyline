# Whyline MCP Server

Expose company memory to Claude, Cursor, Copilot, and any MCP client.

## Tools

| Tool | Description |
|------|-------------|
| `whyline_ask` | Ask a why question — retrieval + LLM answer with receipts |
| `whyline_extract` | Extract and persist a decision from text |
| `whyline_search` | BM25 search over active decisions (no LLM) |

## Run

```bash
npm run setup
npm run mcp
```

## Cursor config

**Project** (recommended): copy `.cursor/mcp.json.example` → `.cursor/mcp.json` and fix the path.

**Global**: `%USERPROFILE%\.cursor\mcp.json` — same JSON.

```json
{
  "mcpServers": {
    "whyline": {
      "command": "C:\\project\\whyline\\scripts\\mcp-cursor.cmd",
      "args": []
    }
  }
}
```

The wrapper loads `.env` from the project root automatically — no API keys in `mcp.json`.  
Uses the same SQLite DB as the web app (`data/whyline.db`).

Restart Cursor → Settings → MCP → enable **whyline**.