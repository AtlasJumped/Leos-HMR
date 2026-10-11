# contract: watcherd (frozen core)

- **start/stop**: user unit `watcherd.service` (lingering; survives logout); health: `curl -sf http://127.0.0.1:8484/healthz`.
- **owns**: nothing durable. ALL behavior comes from `state/watch-map.json` + `state/events.json` — extend the system by editing THOSE (Claude-editable), never this daemon (deny-listed).
- **interfaces**: SSE `/events`; `POST /signal` + `/reload/<panel>` (X-Aletheon-Token required); `POST /heartbeat` + `GET /heartbeat/last`; `GET /metrics/gpu`, `/session`, `/healthz`.
- **reload mechanism**: `systemctl --user restart watcherd` (rare; config files are live-read).
- **invariants**: binds 127.0.0.1:8484 only; jobs/, staging/, secrets/, .git/ excluded from watching; the PostToolUse hook is an inlet to the SAME debouncer.
- **test**: `touch` a file under glance/ → one SSE event ~2.5s later, not a storm.
