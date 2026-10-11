# contract: caddy (the gateway)

- **start/stop**: compose service `caddy` (network_mode: host — required, see Caddyfile header); health: `curl -sf http://127.0.0.1:8080/healthz` (proxied) + admin `curl -sf http://127.0.0.1:2019/config/`.
- **owns**: routing only; no data.
- **interfaces**: every panel URL under `http://127.0.0.1:8080`; admin API on `127.0.0.1:2019`.
- **reload mechanism**: `docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile` (wired in state/watch-map.json). `caddy validate` gates every overhaul activation.
- **invariants**: site addresses bind `127.0.0.1` ONLY. After any change: `ss -tlnp` shows no non-loopback listener except sshd/tailscale; a curl from another LAN host must fail.
- **restore**: git revert of the Caddyfile + reload.
