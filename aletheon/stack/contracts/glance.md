# contract: glance

- **start/stop**: compose service `glance`; health: `curl -sf http://127.0.0.1:8085/glance/`.
- **owns**: nothing durable (config is ours, in git).
- **interfaces**: iframe at `/glance/` via the gateway; widgets pull watcherd metrics + state files.
- **reload mechanism**: server-side fsnotify on glance.yml and `$include`s (automatic, ~500ms debounce). The BROWSER refresh is watcherd's job — its glance rule carries extra_delay 1.0s so the reparse lands first. Never browser-reload faster than that.
- **invariants**: `base-url: /glance` matches the Caddy route; theme include path `themes/active.yml` is what modectl swaps.
- **restore**: git revert + nothing else (stateless).
