# /blazing/stack — the Aletheon Mission Control system of record

Read this first. The design authority is `../DESIGN.md` (v3.1) in the parent repo; this file
is the operating map for sessions working ON the running machine.

## What this repo is
Every small-text thing that drives the system: gateway config, dashboard shell, Glance config,
persona definitions, routing/event data files, the overhaul-job model, systemd units,
contracts. Binaries (videos/stills/weights) live in ZFS datasets (`/blazing/modes-assets`,
`/blazing/hf`, `/blazing/generated`) and are referenced by path.

## How to change things (mutation paths — use the right channel)
| Target | Channel |
|---|---|
| Shell layout/views | edit `state/layout.json` (SSE reloads the shell) |
| Panel routing / reload actions / TTS rules | edit `state/watch-map.json` / `state/events.json` |
| Dashboard content/theme | edit `glance/glance.yml` / mode's `glance-theme.yml` |
| Persona (whole-system look) | `bin/modectl apply <name>`; new persona = new `modes/<name>/` satisfying the 8-point manifest (`bin/modectl validate`) |
| Background video intensity | `bin/fx full|low|paused|away|back` |
| Gateway routes | edit `caddy/Caddyfile` (watch-map reload rule runs `caddy reload`; overhaul validate runs `caddy validate`) |
| Services | edit `docker-compose.yml` (**bind-mounted file edits do NOT restart containers** — use the per-service reload mechanism in `contracts/<svc>.md`) |
| Pipeline board / candidates | Twenty MCP tools (`.mcp.json`), never files |
| Photos | Immich REST (`x-api-key`), never files; library path invariants in `contracts/immich.md` |
| Sims | `bin/simrun run <template> [params.json]` — registry-enumerated templates only |
| **Major/multi-file changes** | an overhaul job: `bin/overhaulctl new <id>` → spec + staged artifacts → `run` (see `jobs/README.md`) |

## Hard rules for sessions here
- Never edit `bin/`, `systemd/`, `jobs/*/state.json`, `.claude/settings.json`, `.mcp.json`,
  `secrets/` (deny-listed; the enforced copies live root-owned in /usr/local — changes there
  go through Leo running `sudo make install`).
- Never touch the Immich volume stanza or `/mnt/photos` mapping (contract invariant).
- Secrets only via `${VAR}` / env_file references; gitleaks gates every commit.
- All of this assumes a Wayland session; if `XDG_SESSION_TYPE != wayland`, stop and say so.
- No LinkedIn automation of any kind (design boundary).

## Orientation
- `bin/preflight.sh` — run before building anything; writes `state/gpu.json`.
- GPU0 = displays + wallpaper decode; GPU1 = compute (`CUDA_VISIBLE_DEVICES=GPU-<uuid>` from
  `state/gpu.json`). Screens are matched by geometry via `state/screens.json`.
- Health: gateway `127.0.0.1:8080/healthz`, watcherd `/metrics/gpu`, per-service contracts.
- Build phases + gates: DESIGN.md §16. Current phase status: `jobs/` + git log.
