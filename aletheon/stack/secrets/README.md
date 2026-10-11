# secrets/ — NEVER in git (.gitignore'd; gitleaks pre-commit is the backstop)

Provisioned by `setup/bootstrap.sh`:
- `watcherd-token` — bearer token for watcherd's mutating endpoints (custom header → CORS preflight)
- `ttyd.env` — `TTYD_CREDENTIAL=leo:<random>` for the terminal panel
- `caddy.env` — `TTYD_BASIC_B64=<base64 of the same>` injected by the gateway
- `compose.env` — DB passwords + app secrets; use `docker compose --env-file secrets/compose.env`

Add later, by hand: `TWENTY_API_KEY` (export in shell profile for .mcp.json), Immich API key,
Google OAuth client JSON (n8n holds the refresh token in ITS encrypted DB, key above).
