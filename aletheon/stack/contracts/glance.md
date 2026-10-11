# contract: glance

- **start/stop**: compose service `glance`; health: `curl -sf http://127.0.0.1:8085/`.
- **owns**: nothing durable (config is ours, in git).
- **interfaces**: iframed DIRECTLY at `http://127.0.0.1:8085/` — deliberately OFF the gateway
  origin (it renders third-party feed content; same-origin with /claude + /token was a
  reviewed XSS-to-terminal path). Its widgets fetch from inside a bridge-mode container:
  only `localhost:8080` (glance itself, e.g. `/assets/state/mode.json`) is reachable —
  never host-loopback services. GPU telemetry belongs to the shell's status strip.
- **reload mechanism**: server-side fsnotify on glance.yml and `$include`s (automatic, ~500ms debounce). The BROWSER refresh is watcherd's job — its glance rule carries extra_delay 1.0s so the reparse lands first. Never browser-reload faster than that.
- **invariants**: `base-url: /glance` matches the Caddy route; theme include path `themes/active.yml` is what modectl swaps.
- **restore**: git revert + nothing else (stateless).
