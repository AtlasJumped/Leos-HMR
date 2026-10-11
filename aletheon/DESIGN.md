# ALETHEON MISSION CONTROL — Systems Design v3.1

> 2026-10-11. Supersedes `DESKTOP_UPGRADE_PLAN.md` (historical) and v3 (same day).
> **v3.1 = v3 + a 5-lens adversarial design-review pass** (ops/transactional, security envelope,
> failure recovery, simplicity/build-order, requirements fidelity): 40 findings, all triaged;
> accepted fixes are integrated inline. Review verdicts are archived in
> `research/design-review-panel.md`.
>
> Provenance tags: **[VERIFIED]** = confirmed on primary sources by a 66-agent research +
> adversarial-verification pass (digests in `research/`). **[DECIDED]** = Leo's explicit call.
> **[DECISION-NEEDED]** = flagged for Leo, default named. **[PROPOSED]** = design, not yet run
> here. **[TEST]** = validate on the machine before building on it.

---

## 0. One-paragraph summary

A **Mission Control** master page runs fullscreen on the top monitor with a **static Claude
terminal panel at its center**; Claude Code runs on the host and edits plain-text files (and
calls service APIs) that drive every other panel, which hot-reload around it. A **persona/mode
system** re-skins the entire machine in one command — always-on video wallpapers, Plasma
colors/cursor/lock-screen, dashboard theme and motion layer, browser color. **Major changes run
as resumable, checkpointed overhaul jobs** with validation gates and recovery that lives outside
the thing being changed. The dual 5090s split duty: GPU0 drives displays + wallpaper decode,
GPU1 runs sims/ComfyUI/ML. All small-text state lives in one git repo (`/blazing/stack`) that
any Claude session reads to get total context; binaries (videos/stills/weights) live in ZFS
datasets beside it.

---

## 1. Goals and hard boundaries

**Goals (Leo's asks):**
1. Full-screen video wallpaper playing at all times. [DECIDED: always-on loops + an `fx` dial
   Leo controls to lower/pause before heavy GPU use or time away. **fps is a per-mode field
   (30|60)**: hero personas get both variants; `fx full` plays 60, `fx low` plays 30/paused.
   The measured watt-delta between 30 and 60 gets shown to Leo after §14 measurement so the
   default is his informed call, not a pipeline footnote.]
2. One-command persona switch across the whole system; Claude can also *generate a brand-new
   persona from a prompt* — and a generated persona must be a **full citizen: all 8 switch
   points** (§8.2), not a partial re-skin.
3. Mission Control dashboard with a central Claude chat box; typing a command in the dash
   modifies the dash (Claude panel static, everything else live). This must stay true as the
   system grows: **new panels/automations are data files Claude can edit**, never daemon edits
   (§5 watcherd split).
4. Prompt-driven GPU physics sims with live 3D viz, live plots, logs, GPU use visible.
5. A video editing studio (GUI + Claude-scriptable lane). [DECIDED: Resolve Studio purchase]
6. A recruiter control panel (pipeline, follow-ups, calendar/email, Gem-style sequences, notes).
   [DECIDED: LinkedIn Recruiter + Gmail/GCal targets]
7. Cutting-edge visuals: cursor, KWin effects, browser theming — **shipped with the mode system
   (phase 5), not parked at the end** (they are installs, not engineering).
8. Cameras/mic/speaker as system senses, **with a Claude-facing perception interface** (events
   and on-demand snapshots Claude can query), not just an archive. [DECIDED purchases; the
   monitor-facing camera stays CUT — screen capture is strictly better]

**Hard boundaries:**
- **No LinkedIn automation** (bots/scrapers/auto-messaging): UA §8.2 prohibition, active
  enforcement, partner-gated APIs. [VERIFIED] Email/calendar/CRM automation is the legitimate
  Gem-equivalent surface.
- **No internal PC hardware purchases.** [DECIDED]
- **No `--dangerously-skip-permissions`** anywhere; interactive default is `auto` mode. [VERIFIED]
- Login screen (GDM) is outside the mode system; optional deliberate SDDM/PLM switch later (§8.6).
- Apple aerials: private offline use only. [VERIFIED]
- No call recording without consent; work-ATS data stays off this machine.
- **Secrets never enter git**: `secrets/` is gitignored; `.mcp.json`/compose reference
  `${VAR}`/env_file; gitleaks runs as a pre-commit hook from phase 1. The Gmail refresh token
  lives only in n8n's DB, encrypted with a key stored outside the repo. [panel fix]

---

## 2. Architecture overview

```
                    DP-2 (top, 3440x1440@240): MISSION CONTROL KIOSK
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  machine tiles │ world feeds │        CLAUDE          │ me/photos tile   │
 │  (Glance +     │ (Glance)    │  ttyd → tmux → claude  │ (Immich API)     │
 │   GPU/ZFS API) │             │  [STATIC IFRAME via    │ recruiter board  │
 │  sim viewport  │ render-ops  │   Caddy /claude route] │ (Twenty)         │
 │  (rerun)       │ panel       │                        │                  │
 │  ───────── per-persona motion layer (muted video/WebGL bg, fx-governed) ─│
 └──────────────────────────────────────────────────────────────────────────┘
   DP-3 bottom-left: work (video wallpaper)   DP-1 bottom-right: work (video wallpaper)

 HOST (leo user units, lingering)         DOCKER (data-root /blazing/docker, ALL ports 127.0.0.1)
 ─ tmux unit "claude" (claude --continue) ─ caddy   network_mode: host, sites on 127.0.0.1 ONLY
 ─ ttyd 1.7.7 (127.0.0.1:7681, -O)        ─ glance  dashboard content
 ─ watcherd CORE (SSE + heartbeat only;   ─ immich stack (server/ML-cuda/pg/redis)
   behavior loaded from data files)       ─ twenty CRM · n8n  (recruiter phases)
 ─ overhaulctl (CLI, /usr/local root-owned)─ beszel hub (optional, later)
 ─ powerguard  (root half /usr/local/sbin + leo session half)
 ─ modectl / fx / persona-create (repo bin, driver-based wallpaper interface)
 ZFS: blazing/{stack,modes-assets,hf,docker,generated}  scratch/{proxies,simruns}  tank/{photos,frigate,backup}
```

**The self-modification loop** (core demo): Leo types in the Claude panel → Claude (host) edits
files in `/blazing/stack` or calls a panel's API (Twenty MCP, Immich REST) → **watcherd core**
(inotify, debounced 1.5s) consults **data files Claude CAN edit** — `state/watch-map.yml`
(path→panel→reload-action), `state/events.yml` (event→action/TTS rules) — and emits typed SSE;
the shell reloads only the affected iframe (CSS swaps a `<link>`; Glance events are delayed ~1s
so its server-side fsnotify reparse lands first [VERIFIED]). The Claude Code **PostToolUse
hook** feeds the *same debounce queue* via `POST /signal` — it is an early signal into the
debouncer, never a direct SSE emit [panel fix]. `jobs/**` and `staging/**` are excluded from
both watchers. The Claude iframe is never remounted by the reload path (one carve-out: §6
remounts it on WebSocket close). Mutation paths are documented per panel in CLAUDE.md:
file-driven (Glance YAML, shell, modes, Caddyfile) vs API-driven (Twenty MCP, Immich REST, n8n
webhooks) — so "add a column to my pipeline" goes through the right channel.

**Growth rule** [panel fix]: a new panel = an entry in `layout.json` + `watch-map.yml` + (if
needed) a compose service — all Claude-editable. The deny-listed set is deliberately tiny (§4.4)
so "typing a command modifies the dash" stays true in month 12, not just at build time.

---

## 3. Safety floor (build before anything glows)

1. **ZFS datasets + snapshots.** One `zfs create` per dataset (the multi-arg form is invalid).
   For any target path that already exists non-empty (likely `/blazing/docker`, HF cache):
   create the dataset unmounted (`-o mountpoint=none`), mount at a `.migrate` path, move data
   in (Docker stopped for its data-root), then set the real mountpoint. Preflight assert per
   dataset: path absent/empty OR already a dataset — fail loudly otherwise. [panel fix]
   Then `sanoid`: hourly on `rpool/USERDATA` + `blazing/stack` + `blazing/modes-assets`, daily
   on `tank`, auto-pruned.
   **Delegation** so checkpoints work as leo without root-equivalence:
   `zfs allow -u leo snapshot,clone,mount,hold blazing/stack blazing/modes-assets` —
   destroy/rollback are NOT delegated and stay root-only. [TEST on this OpenZFS build; panel fix]
2. **Photos to the mirror.** Move the iCloud library to `tank/photos` BEFORE Immich's first
   scan — Immich identifies external assets by path; moving the library after indexing orphans
   faces/albums/days of ML work. The in-container mount path is frozen forever in
   `contracts/immich.md`; future host moves are compose-edits only. [panel fix]
3. **Repo to private GitHub** with gitleaks pre-commit + `secrets/` gitignored from the very
   first commit. [panel fix]
4. **Agent browser profile**: no saved passwords/autofill/payment methods.
5. **UPS + load-shedding.** [DECIDED: keep the CyberPower 1500] `nut` watches it. powerguard is
   **split by privilege** [panel fix]: a root-owned script at `/usr/local/sbin/powerguard-shed`
   (installed by a root `make install` from the repo — root never executes leo-writable code)
   does `nvidia-smi -pl 150`, container stop, `zpool sync`, shutdown, driven by upsmon/upssched;
   it touches a state flag that a leo user unit watches to run the session half (`fx paused`,
   SIGSTOP sim queue, qdbus). On battery it also signals overhaulctl to pause at the next task
   boundary before any shutdown timer. [TEST the full shed path under load at phase 0.]
6. **Offsite** [DECISION-NEEDED, default yes]: Backblaze B2 via rclone cron for `tank/photos`
   (~$2/mo, encrypted, keys off-machine). Without it, fire/theft/ransomware has no answer.
7. **Docker on ZFS**: `data-root: /blazing/docker`; verify `docker info` storage driver.
   **daemon.json also sets `"ip": "127.0.0.1"`** so every published port defaults to loopback,
   AND every `ports:` entry in our compose files carries an explicit `127.0.0.1:` prefix (stock
   Immich/Twenty/n8n composes are overridden, never copied). Smoke test, run by watcherd after
   every compose change: **no non-loopback listener in `ss -tlnp`** except sshd/tailscale.
   [panel fix — Docker publishes 0.0.0.0 by default and punches through host firewalls]
8. **Docker-socket honesty** [panel fix]: leo in the docker group is root-equivalence by
   documentation; the §4.4 envelope is therefore a guardrail, not a boundary (see §4.4). The
   compensating control that leo genuinely cannot touch: **root-owned syncoid pull-replication**
   of `blazing/stack` + `blazing/modes-assets` snapshots to `tank/backup` on a root timer.
   Optional hardening later: docker-socket-proxy or rootless Docker (verify CUDA CDI first).

---

## 4. The Overhaul Engine (`overhaulctl`) — one prompt, one recoverable operation

> **Major changes run as resumable, testable overhaul jobs, with automatic activation inside an
> established permission envelope and recovery independent of the changed application.**

### 4.1 Job model (coordinator outside the conversation)

A job is a directory: `/blazing/stack/jobs/<id>/` → `spec.json`, `state.json` (runner-owned
progress journal), `plan.md`, `log/`, `artifacts/` (staged outputs). Any session resumes from
`state.json`; the runner is deterministic — **Claude writes the spec and the staged files; the
runner executes and judges.** Before any *manual* `zfs rollback`, the runner copies
`state.json` + failure report to `scratch/` — the record of why must survive the rollback that
answers it. [panel fix]

### 4.2 OVERHAUL_SPEC v1 — flat and fully executable [panel fix: waves deferred to v2]

```json
{
  "id": "brutalist-scifi-001",
  "intent": "one sentence",
  "preserve": ["tank/photos", "immich volumes+env in compose", "tmux session claude",
               "jobs/**", ".claude/settings.json", ".mcp.json", "secrets/**"],
  "checkpoint": { "zfs": ["blazing/stack", "blazing/modes-assets"], "git": true },
  "validate":  ["caddy validate --config staging/Caddyfile",
                "docker compose -f staging/docker-compose.yml config -q",
                "jq -e . staging/state/mode.json", "bin/lint-watchmap staging/state/watch-map.yml"],
  "activate":  { "manifest": [["staging/glance/theme.yml","glance/theme.yml"], ...],
                 "reload":   "derived from watch-map.yml per changed path" },
  "probe":     ["curl -sf http://127.0.0.1:8080/healthz", "bin/probe-applied-config",
                "bin/probe-kiosk-pingback --retries 3 --grace 90",
                "nvidia-smi --query-gpu=memory.used --format=csv,noheader -i 0"],
  "limits":    { "max_attempts": 2, "max_budget_usd": 15 },
  "rollback":  "named routine: see 4.3"
}
```
Every entry is a shell command or a file-pair — nothing is prose the runner can't execute. The
runner is ~200–300 lines with subcommands `checkpoint | validate | activate | probe | rollback |
resume`. Wave/DAG structure returns only when a real job proves two-stage activation is needed.

### 4.3 Lifecycle, activation protocol, and the ONE revert routine

**Checkpoint** = `git commit -A` (gitleaks hook runs) + delegated `zfs snapshot`.
**Activate (journal-first, idempotent)** [panel fix]: the runner records pre-activation HEAD and
`activate:started` in `state.json` **before touching live paths**; then rsync per manifest;
`git commit` (recording the hash immediately); then per-path **reload actions derived from
watch-map.yml** — because `docker compose up -d` does NOT restart containers for bind-mounted
file edits [panel fix]: each service's contract names its mechanism (`caddy reload` |
fsnotify-automatic | `compose restart <svc>` | `up -d --force-recreate <svc>`); then
`modectl apply` if the job touches modes; then SSE. Recovery rule is mechanical: resume with
`activate:started` and no activation commit → `git reset --hard <recorded HEAD>`, re-run the
whole activate step (rsync is idempotent).
**Probe** verifies **applied** config, not just liveness: HTTP sweep + an applied-config check
(Glance page contains the new theme token; Caddy admin config hash; mode read-back) + kiosk
pingback **with 3 retries over 90s** (so a kiosk restart mid-probe reads as late heartbeat, not
failure) + `tmux has-session` — but a tmux-only failure restarts the tmux unit and re-probes
rather than reverting an unrelated activation. [panel fixes]
**Revert** is ONE named routine used by probe-failure and `overhaulctl rollback` alike:
git revert (or reset per the recovery rule) → per-service reload actions → `modectl apply
<previous>` → SSE → **`systemctl --user restart missioncontrol-kiosk`** → re-probe pingback.
File recovery without screen recovery is not recovery. [panel fix]
Bounded attempts (2), then stop with a failure report — never loop declaring success.

### 4.4 Permission envelope — honest version [panel rewrite]

**What is enforced:** overhaulctl, powerguard-shed, chrome-theme, and the syncoid replication
run **root-owned from /usr/local**, promoted from the repo only by a root `make install` Leo
runs — Claude-as-leo cannot modify what root executes. ZFS destroy/rollback are root-only;
snapshot creation is delegated. Headless invocations carry `--max-budget-usd`/`--max-turns`.
Off-dataset snapshot replication exists that leo cannot delete.
**What is a guardrail, not a boundary:** Claude Code deny rules (now explicitly covering
`.claude/settings.json`, `.mcp.json`, `bin/**`, `jobs/*/state.json`, `.git/**`, `secrets/**`)
bind the Edit/Write tools — **they do not bind Bash**, and the panel session's purpose is Bash
as leo. They are speed bumps against accidents. The real risk ceiling is set by §3.8 (docker
group = root-equivalence) and by the root-owned install path. The design says this plainly
rather than claiming an enforcement it doesn't have.
**Recovery independence:** `overhaulctl rollback <id>` works from any TTY/Konsole; tmux
survives kiosk/gateway death; the revert routine restarts the kiosk itself.

### 4.5 Component contracts

`contracts/<component>.md`: start/stop/health, data owned, interfaces, export/restore,
essential-function test, permissions, **and reload mechanism** (consumed by 4.3). The Immich
contract carries the frozen-path invariant (§3.2) and its compose `volumes`/env are
preserve-protected — the runner refuses specs that diff them. [panel fix]

### 4.6 Engine acceptance (lives at phase 8, not phase 1 [panel fix])

One prompt replaces the dashboard layout and two personas, preserves the active chat and all
stored data, survives a mid-build interrupt (resume), and recovers **visibly** from a
deliberately broken candidate: a bad Caddyfile dies in validate; a bad shell page planted past
validate fails pingback → auto-revert → kiosk restart → pingback green. Phase 1 has its own
primitives-only gate (§16).

### 4.7 Corrections to the externally-proposed designs (kept from v3, all panel-confirmed)

`zfs rollback` = manual last resort (most-recent-snapshot-only, unsafe under live mounts);
routine rollback is git + reload actions; migrations rehearse on `zfs clone`. Symlink cutover
doesn't retarget running containers. "Compositor latency <10ms" is not a real assertion —
probes are the §4.3 list. No watchdog-triggered automatic dataset rollback, ever.

---

## 5. Mission Control shell

- **One master page**, one Chrome kiosk window on DP-2. [VERIFIED vs KWin-tiled alternative]
- **Shell = static HTML + CSS grid + vanilla JS + iframes, zero build step.**
  `layout.json` is **versioned with named views** from day one —
  `{"views": {"default": …, "recruiting": …, "simlab": …}}` — with lazy iframe mount/unmount on
  view switch and the Claude panel pinned across views. ~50 lines now vs an every-persona
  migration later; it also caps concurrent renderer memory structurally. `workspace recruiting`
  (§12) switches both KWin windows and the dash view. [panel fix]
- **Per-persona motion layer** [panel fix — maximalism on the most-looked-at screen]: a muted
  `<video>`/WebGL background behind the grid (same NVDEC path, GPU0, `fx`-governed, pauses on
  `fx low`), plus persona-colored layout transitions; `persona-create` generates a shell
  background asset per mode.
- **Gateway**: Caddy **`network_mode: host`** (documented reason: loopback site addresses +
  host-loopback upstreams like ttyd/watcherd are unreachable from a bridge-mode container
  [panel fix]), every site bound `127.0.0.1`. WebSockets and SSE proxied automatically;
  `header_down -X-Frame-Options` only where needed (Beszel via its CSP env). [VERIFIED]
  Immich stays on its own loopback port (subpath unsupported; same-site cookies OK). [VERIFIED]
- **watcherd CORE** (frozen scope, deny-listed): inotify→debouncer→SSE, `POST /signal` (hook
  inlet), `POST /reload/<panel>`, kiosk heartbeat. **All behavior from data files**:
  `watch-map.yml`, `events.yml` (TTS and future automations are SSE *consumers*, not watcherd
  features). Mutating endpoints require a random bearer token in a custom header (forces CORS
  preflight → kills cross-origin POSTs from local browsers); the shell fetches the token from a
  loopback-only Caddy route. Runs as a **lingering user service** (`loginctl enable-linger leo`,
  `WantedBy=default.target`) so it — and in-flight jobs — survive graphical-session restarts
  and logouts. `ExecCondition` asserts `XDG_SESSION_TYPE=wayland` on kiosk/fx units, and
  watcherd exposes session-type as a health field with a red-banner + TTS event on X11 fallback.
  [panel fixes]
- **Keyboard reality**: top-level `keydown` preventDefault for Ctrl+W/T/N/F5; explicit focus
  management with a visible ring; kiosk unit uses **`Restart=always`, `RestartSec=2`,
  `StartLimitIntervalSec=60`, `StartLimitBurst=5`** (Ctrl+W exits 0 — `on-failure` would leave
  the monitor dark [panel fix]). The guard *extension* is deferred: build it only if Ctrl+W
  actually escapes during a week of real use. [panel fix]
- **Kiosk ops**: Chrome ≥140 is native Wayland automatically [VERIFIED]; one KWin rule
  (dedicated `--class=missioncontrol`) forces Screen=DP-2 + Fullscreen [TEST]. 04:30 recycle
  timer skips when the tmux pane is active **or any `jobs/*/state.json` shows status=running**
  [panel fix]. State survives recycles (tmux, Chrome profile, cookies).
- **Screen blanking**: no per-monitor idle blanking on Plasma Wayland [VERIFIED]; auto
  screen-off disabled; `fx away` disables work outputs — with **hysteresis** (10-min absence,
  instant return) and modectl deferring wallpaper writes while expected outputs are down
  (output-count check first, auto re-apply on re-enable). Output-cycling ×50 joins the phase-2
  soak. [panel fix]
- **Plasma version policy**: hold at 6.6.6; 6.7.0/6.7.1 ship a KWin crash on Chromium
  fullscreen toggling (bug 521722) and 6.6.x lacks NVIDIA triple buffering; move at ≥6.7.3 with
  the fix confirmed, re-test the kiosk immediately. [VERIFIED]

## 6. The Claude panel

- `ttyd -W -i 127.0.0.1 -O … tmux new -A -s claude claude`, 1.7.7 binary. [VERIFIED]
- **Served through Caddy at `/claude` with injected `Authorization` (`header_up`)** — not
  direct [panel fix]: an unauthenticated writable ttyd is reachable by any local browser, and
  DNS rebinding defeats `-O` (Origin==Host under rebinding; Caddy's exact-host matching kills
  it). Gateway breakage is recovered by tmux-from-Konsole + the §4.3 revert routine restarting
  the kiosk — the old "serve direct to survive Caddy" rationale was weaker than the exposure.
  No persistent `--remote-debugging-port` (a second unauthenticated loopback channel); CDP only
  transiently if ever needed.
- **Supervised**: tmux runs as its own user unit (`Restart=on-failure`, ExecStart
  `tmux new-session -d -s claude 'claude --continue'`) and ttyd as another; shell JS listens
  for the ttyd WebSocket close and **remounts only the Claude iframe with backoff** — the one
  sanctioned exception to "never remounted". `aggressive-resize on`; attach elsewhere with
  grouped sessions (`tmux new-session -t claude`); `history-limit 50000`. [panel fixes]
- Panel session runs `auto`/`acceptEdits`; dashboard buttons shell out to
  `claude -p --output-format stream-json --resume <pinned> --allowedTools …` with budget caps.
- Stage 2 (optional): Agent SDK chat panel — official example exists
  (`anthropics/claude-agent-sdk-demos` → `simple-chatapp`). [VERIFIED] Phone: Tailscale-bound
  route or Happy; CloudCLI as a separate tab (needs Node 22+). Dead: sugyan/claude-code-webui,
  Crystal, Conductor, sshx. [VERIFIED]

## 7. Video wallpaper layer + fx dial

- **Engine**: Smart Video Wallpaper Reborn v2.16.0 (`luisbocanegra.smart.video.wallpaper.reborn`,
  KDE Store 2139746) — Plasma-6-native, per-screen, lock-screen capable, pause conditions,
  dark/light video pairs. mpvpaper non-viable on KWin; catsout plugin archived. [VERIFIED]
- **Driver interface** [panel fix]: modectl/fx call a thin wallpaper driver —
  `apply(screen, media)`, `set_pause(screen, mode)`, `lock(media)` — with SVWR as driver #1 and
  waywallen as a named fallback (documented degradations: lock-screen video → static,
  dark/light pairs → single). The phase-2 soak plays one reference loop of the exact encode
  spec through the fallback too, before the spec is frozen.
- **Decode**: Qt Multimedia FFmpeg + NVDEC via `QT_FFMPEG_DECODING_HW_DEVICE_TYPES=cuda` set in
  **`~/.config/environment.d/`** (so `kscreenlocker_greet` inherits it). Confirm `dec% > 0` in
  `nvidia-smi dmon`; 0% is a bug, not success. [VERIFIED]
- **Per-screen policy**: DP-1 + DP-3 video, `PauseMode=3` (never) + pause-on-screen-off.
  **DP-2 under the kiosk**: static image behind the kiosk, while the kiosk's own §5 motion
  layer carries the movement. [DECISION-NEEDED: Leo signs off that occluded DP-2 wallpaper is
  static — decoding behind an opaque fullscreen window is pure waste; the alternative honors
  "all monitors" literally at ~+15W for invisible pixels.]
- **Content spec**: 3440×1440-native, **per-mode fps field 30|60** (§1.1), HEVC 10-bit NVENC,
  single closed GOP, 20–40 Mbps.
- **`fx` dial** [DECIDED]: `fx full|low|paused|away` — full plays 60fps variants + shell motion;
  low = 30fps + pause-on-maximized + shell motion off; paused = all video stopped; away = low +
  work outputs disabled (hysteresis per §5). Hooks: powerguard→paused on battery; presence
  sensor→away; sim-runner may set low.
- **Exact switch mechanism** [VERIFIED from plugin source]: per-containment `evaluateScript`
  writing `VideoUrls` JSON, matched by `screenGeometry()` (0,1440=DP-3; 3440,1440=DP-1;
  1699,0=DP-2); lock screen via `kwriteconfig6` on `kscreenlockerrc`. **modectl is
  transactional-ish** [panel fix]: checks qdbus exit code, re-runs if plasmashell restarted
  mid-apply (apply is idempotent), reads back one wallpaper key per screen, and writes
  `state/mode.json` only after all 8 points verify; mode-touching overhaul probes include
  `plasma-plasmashell` active + config read-back.
- **Week-1 soak gate**: 3 ffmpeg test loops; multi-day soak covering lock/unlock, screen-off,
  mode switches, output disable/enable ×50, and `systemctl suspend` (open 5090 UVM-deadlock
  report with hw-decoded video wallpaper). Known NVIDIA/Wayland issues (#290/#292) have named
  mitigations (`QSG_RHI_BACKEND=vulkan`, `QT_DISABLE_HW_TEXTURES_CONVERSION=1`, GStreamer
  backend). **Bulk library generation waits for this gate** (pipeline *build* may parallelize;
  masters may be generated at mezzanine quality so a codec re-encode is cheap). [VERIFIED + panel]

## 8. Persona/mode system

### 8.1 Layout — split text from binaries [panel fix]
```
/blazing/stack/modes/<name>/        # IN GIT → git revert covers persona rollback
  manifest.json                     # the full 8-point persona manifest (schema below)
  mode.conf  shell.css  glance-theme.yml  konsole.profile+colorscheme
  kando-colors.json  panel-colorizer-preset/  browser.hex
/blazing/modes-assets/<name>/       # big binaries, ZFS-snapshotted, referenced by path
  videos/dp1-{30,60}.mp4 dp3-{30,60}.mp4  shellbg.mp4  stills/dp2.png  lock.{mp4,png}
```
**Persona manifest schema**: every switch-point artifact required-or-defaulted; `modectl
validate <name>` lints it; the §16 round-trip gate runs against a **generated** persona, so
hand-written and generated personas are the same grade of citizen. [panel fix]

### 8.2 `modectl apply <name>` — 8 switch points, all live [VERIFIED each]
1. Colors/cursor/style via the individual CLIs — `plasma-apply-colorscheme` (two-name
   alternation quirk), `plasma-apply-cursortheme`, `plasma-apply-desktoptheme`.
   **LookAndFeel packages are CUT** [panel fix]: they duplicate mode.conf + the appliers and
   would make persona-create codegen KDE packages for zero added capability.
2. Wallpaper videos per screen via the driver (§7) + DP-2 static + shell motion layer asset.
3. Lock screen via `kwriteconfig6`.
4. Konsole: D-Bus loop `setProfile` + default in `konsolerc` (profile files from the manifest).
5. Kando: `menuTheme`/`menuThemeColors` in config.json (hot-reloaded).
6. Panel accents: panel-colorizer D-Bus preset.
7. Window decorations: `kwin-applywindowdecoration` (+ KWin reconfigure).
8. Dashboard: `state/mode.json` + Glance theme include → server hot-reload; `mode.js` fetches
   `/assets/state/mode.json` (bind-mounted state dir [VERIFIED mechanism]) → `/api/set-theme`;
   shell.css + motion asset via SSE.

### 8.3 Browser theming [VERIFIED + panel security fix]
Chrome: `BrowserThemeColor` managed policy — live file-watched refresh. The policy dir **stays
root-owned** (a leo-writable managed-policy dir = force-installable extensions = code execution
across every profile); modectl calls `sudo chrome-theme '#rrggbb'` — a root-owned 10-line
helper at `/usr/local/sbin/` with a NOPASSWD sudoers pin that regex-validates its single
argument and writes exactly `{"BrowserThemeColor": …}`. Firefox: per-mode profiles (custom
theme extension cut). Dark/light rides the portal (Chrome ≥114).

### 8.4 Cursors
4 existing maintained themes (Breeze variants, Bibata colorways, Oreo) switched live by
`plasma-apply-cursortheme`; custom animated-SVG authoring deferred (format supports it
[VERIFIED]; days of work for a 32px payoff).

### 8.5 `persona-create "<prompt>"` (runs as an overhaul job)
Generates: stills + loops (30 and 60 variants for hero personas) + shell background on GPU1 →
derives color scheme from imagery → **mechanically derives the remaining manifest artifacts**
(Konsole profile/colorscheme, Kando colors JSON, panel-colorizer preset, lock asset — all small
text files from the same palette) [panel fix] → writes `modes/<name>/` (git) +
`modes-assets/<name>/` (dataset) → validate → `modectl apply`. Rollback = git revert (text) +
asset dir removal; both covered by the §4.3 routine.

### 8.6 Login screen (one-time decision, default: switch to SDDM)
His on-machine plan already chose SDDM but never applied it. SDDM (or Plasma Login Manager,
which uniquely supports video on the login screen) joins theming; GDM stays static forever.
modectl asserts `XDG_SESSION_TYPE=wayland` and unit-level ExecConditions do too (§5).

## 9. Generation pipeline (GPU1)

- **PyTorch stable 2.14.x cu130 — no nightly** (sm_120 stable since 2.7; cu130 default since
  2.11; TECH_STACK.md's nightly note is stale). `torch.cuda.get_device_capability()==(12,0)`.
  [VERIFIED]
- **nvcc**: driver-reported "CUDA 13.0" ≠ toolkit. Install `cuda-nvcc` 13.x **in the conda
  env** + ninja for the SageAttention source build; ComfyUI `--disable-xformers`. [VERIFIED]
- **Weights (~400GB, some gated)**: `hf auth login`, accept FLUX.2-dev (and LTX-2.5 if used)
  licenses first; `HF_HOME=/blazing/hf`. Itemized: Wan2.2 A14B fp8 (both experts), VACE,
  lightx2v Lightning LoRAs, SeedVR2 3B+7B, FLUX.2-dev FP8 (+Mistral TE → RAM offload).
- **Loop pipeline**: FLUX.2 still at 21:9 → Wan 2.2 FLF2V same-frame (mathematically seamless;
  official template) + Lightning 4-step → direct 21:9 latent where tolerated (VACE outpaint
  only when needed) → SeedVR2 (batch≥5) to 3440×1440 → `hevc_nvenc` 10-bit closed-GOP.
  60fps variants via RIFE for hero personas (§1.1). [VERIFIED]
- Aerials seed library via Apple's `entries.json` + aria2c (private use). Nightly systemd timer
  → ComfyUI API → active mode's asset dir → SSE hero-tile refresh. Wan >2.2 is API-only;
  re-check HF trending at phase 7. [VERIFIED]

## 10. Sim Lab (prompt → physics → live viz)

- **Newton** (`pip install "newton[examples]"`) — successor to warp.sim (**removed in Warp
  1.10**; any warp.sim tutorial is dead code); Warp 1.18 cu13 wheels require exactly R580+ —
  this box is the blessed path. Genesis deferred; Taichi dormant/broken on sm_120; Isaac Sim
  heavyweight-optional. [VERIFIED]
- **rerun 0.38.x**: sim calls `rr.serve_grpc()` + `rr.serve_web_viewer()`; kiosk iframes the
  locally-served viewer; **viewer version must equal SDK version** — the runner derives the
  URL from the installed version at launch. WebGPU is default in kiosk Chrome on this driver.
  [VERIFIED]
- **Prompt→sim**: Claude fills **parameterized scene templates** (freeform physics codegen ≈
  21.5% pass rate in 2026 benchmarks); 10-step dry-run validator; bounded repair. **Template
  enforcement is server-side**: the run entrypoint accepts only an enum of vetted template
  names + schema-validated params — never a path. [VERIFIED + panel security fix]
- **Runner v1 = no daemon** [panel fix]: Claude invokes
  `systemd-run --user --unit sim-N -p Environment=CUDA_VISIBLE_DEVICES=GPU-<uuid> conda run -n
  newton python templates/<t>.py --params p.json --viewer rerun --port <alloc>` directly (unit
  names without `@`); logs to `scratch/simruns/<ts>/`; a cleanup script kills orphaned CUDA
  PIDs (zombie VRAM = #1 flake source). A dash button covers the common case via `claude -p`.
  A separate `simrunnerd` appears only if button-driven sims outgrow that. GPU UUIDs from
  `nvidia-smi -L`; per-process attribution via `nvidia-smi pmon`/NVML. [VERIFIED]

## 11. Video Studio

- **Resolve Studio 21.1** [DECIDED]: free edition can't decode H.264/HEVC on Linux at all, AAC
  unsupported in both editions (one-time audio transcode into an edit cache on `scratch`),
  free lost scripting in 21.1; Studio adds dual-GPU + a **native MCP server officially
  supporting Claude Code** (~88 tools). Known installs frictions on 26.04 (t64 renames,
  bundled-glib removal, MakeResolveDeb; XWayland + `QT_QPA_PLATFORM=xcb`). [VERIFIED]
- **Kdenlive** native apt (25.12.3 in 26.04; backports PPA 26.08.2; never Flatpak — sandboxed
  libcuda breaks NVENC). MLT XML projects → Claude edits as text → `melt` renders headlessly.
  [VERIFIED]
- **Programmatic lane**: WhisperX transcripts → segment picks → ffmpeg 8 NVENC extract/concat;
  `auto-editor` silence cuts exporting editor project files. iPhone Dolby Vision P8.4 = HLG
  base layer → tone-map (`zscale+tonemap=hable` / libplacebo bt.2390), never naive-scale.
  [VERIFIED]
- **Dash panel = render-ops** (queue, NVENC util, transcript status, launch buttons via KWin
  rule) — a Qt app can't live in an iframe.
- **One ASR env** serves studio + recruiter (faster-whisper ≥1.2/CT2 ≥4.8 — the INT8-on-sm_120
  block is fixed; WhisperX for word-level). [VERIFIED]

## 12. Recruiter cockpit [DECIDED scope]

- **Twenty CRM** (weekly releases, kanban, REST+GraphQL+webhooks, **first-party MCP** in
  `.mcp.json` with key via `${VAR}`). [VERIFIED]
- **Google OAuth**: own project, Desktop client, External, **published to In-Production**
  (Testing tokens die every 7 days) — **start the consent-screen clock at phase 0** (it's a
  form, not code). [VERIFIED + panel]
- **n8n** (Sustainable Use licence covers this) for Gmail triage + Gem-style sequences
  (Claude-personalized steps, auto-stop on reply) surfaced via Glance custom-api tiles.
- **Scheduling**: Google Calendar appointment pages first; Cal.diy deferred. [panel fix]
- **Capture**: paste-in → Twenty; boolean/X-ray builder widget → flair backlog. [panel fix]
- `workspace recruiting`: KWin placement + dash view switch (§5 views).
- Interview notes: watch-folder → ASR env → `claude -p` → Twenty notes. Consent always.

## 13. Senses [DECIDED purchases; Claude-facing by design]

- **Webcam**: top-line UVC/PTZ-class or mirrorless+capture; OBS virtual cam. [PROPOSED picks at
  purchase time]
- **Room cams**: 2–3 PoE/ONVIF under **Frigate NVR** (GPU detection, `tank/frigate`, no cloud).
  **Perception interface** [panel fix]: Frigate MQTT/API events → `events.yml` → SSE/Claude
  context; an on-demand snapshot tool documented in CLAUDE.md ("snapshot my desk", "who's at
  the door") — events AND queryable eyes, not an archive.
- **Voice**: mic → ASR env push-to-talk; speaker ← Piper/Kokoro TTS as an **SSE consumer** of
  `events.yml` ("render done", "sim finished", "next call in 10").
- **Sensors**: power-metering smart plug (live watts tile — §14 ground truth) + desk mmWave
  presence (drives `fx away` with §5 hysteresis). Home Assistant only if sensor count demands.
- Monitor-facing camera stays cut; Claude self-verifies output via Wayland screen capture.

## 14. GPU & power

- **Build step zero** [TEST]: all three DP cables on GPU0 (`/dev/dri/by-path/`,
  `kscreen-doctor -o`); re-cable first if not. `KWIN_DRM_DEVICES=<by-path GPU0>` in
  environment.d. GPU1 = compute only (`CUDA_VISIBLE_DEVICES=GPU-<uuid>`). Wallpaper decode
  can't move to GPU1 (same-backend limitation) — it rides GPU0. [VERIFIED]
- **Honest budget**: triple-240Hz pins GPU0 ≈50–90W idle regardless; playback +20–35W; 60fps ≈
  2× the decode of 30. Measure (§13 smart plug + `nvidia-smi` tiles, Beszel later with
  `GPU_COLLECTOR=nvml` — its default polling blocks idle states) and show Leo the 30-vs-60
  delta. `CUDA_DISABLE_PERF_BOOST` [TEST]. [VERIFIED]
- powerguard split per §3.5.

## 15. Prerequisites — the direct answer

```bash
# ── preflight (fail loudly) ────────────────────────────────────────────────
[ "$XDG_SESSION_TYPE" = wayland ] || exit 1
ls -l /dev/dri/by-path/            # all 3 DP on GPU0?
for c in qdbus6 kwriteconfig6 kpackagetool6 plasma-apply-colorscheme \
         plasma-apply-cursortheme kwin-applywindowdecoration kscreen-doctor; do
  command -v $c || echo MISSING $c; done          # qdbus6 ships in qdbus-qt6 (universe)
google-chrome --version            # Chrome .deb, NOT snap chromium
nvcc --version || echo "toolkit missing → conda cuda-nvcc"
# per planned dataset: path absent/empty OR already a dataset (zfs list) — else STOP (§3.1)

# ── apt ────────────────────────────────────────────────────────────────────
sudo apt install ffmpeg libqt6multimedia6 qml6-module-qtmultimedia qdbus-qt6 \
     inotify-tools ttyd tmux jq nut sanoid gitleaks kdenlive
ffmpeg -encoders | grep nvenc && ffmpeg -hwaccels | grep cuda   # and libnvcuvid.so present
sudo add-apt-repository ppa:matinlotfali/kde-rounded-corners && sudo apt install kwin-effect-roundcorners
sudo apt-mark hold 'plasma-*' 'kwin-*'          # §5 version policy
# NVIDIA container toolkit (official repo) → nvidia-ctk runtime configure --runtime=docker
# Node 22/24 LTS via nodesource (Node 20 is EOL)
# /etc/docker/daemon.json: {"data-root":"/blazing/docker","ip":"127.0.0.1"}

# ── root-owned installs (make install from the repo; §4.4) ─────────────────
# /usr/local/bin/overhaulctl  /usr/local/sbin/{powerguard-shed,chrome-theme}
# sudoers pins: chrome-theme, powerguard-shed; zfs allow -u leo snapshot,clone,mount,hold …
# root syncoid timer: blazing/{stack,modes-assets} snapshots → tank/backup

# ── Plasma pieces (store/.deb installs — no cmake) ─────────────────────────
# SVWR (store 2139746) · Kando 3.0 .deb · panel-colorizer · Burn-My-Windows kwin6 · KZones
# Klassy: ONLY if OBS has an xUbuntu_26.04 target; else Breeze + colorschemes
# catppuccin/kde v0.4+ · 4 cursor themes

# ── conda envs ─────────────────────────────────────────────────────────────
# comfy:  torch 2.14 cu130 (stable) · cuda-nvcc 13.x · ninja · sageattention 2.2 ·
#         ComfyUI (--disable-xformers) + VideoHelperSuite + SeedVR2 + frame-interp nodes
# newton: newton[examples] · rerun-sdk 0.38.x (pinned)
# asr:    faster-whisper>=1.2 · ctranslate2>=4.8 · whisperx
# hf auth login · accept FLUX.2-dev (and LTX-2.5) licenses · HF_HOME=/blazing/hf (~400GB)

# ── the stack repo ─────────────────────────────────────────────────────────
# one zfs create per dataset (§3.1 migration recipe where non-empty)
# /blazing/stack: CLAUDE.md contracts/ docker-compose.yml caddy/ shell/ glance/ modes/
#   bin/ (modectl fx persona-create watcherd lint-*) state/{watch-map,events}.yml jobs/
#   secrets/(gitignored) systemd/ .claude/settings.json .mcp.json Makefile(install)
```
Purchases [DECIDED]: Resolve Studio ~$295 · Wallpaper Engine $4 · cameras/mic/speaker (§13).
Not buying: internal hardware, bigger UPS (powerguard instead). B2 offsite [DECISION-NEEDED].

## 16. Build order (dependency-edged; every row exits through a testable gate)

| # | Phase | Gate | Can run under earlier gates |
|---|-------|------|------------------------------|
| 0 | Preflight + safety floor (§3; incl. datasets, delegation, daemon.json, photos→tank, powerguard shed-path test) · **start Immich compose + indexing** · **start Google OAuth consent clock** | asserts green; snapshot/restore drill; shed test | — |
| 1 | Minimal overhaul harness (flat spec, runner, root installs, gitleaks) | **primitives drill**: checkpoint → planted bad file fails validate → good change activates → rollback restores byte-identical → resume after kill-9 | Immich indexes |
| 2 | Wallpaper soak (SVWR + env vars + 3 test loops + fx dial + driver interface) | multi-day soak incl. lock, suspend, output-cycling ×50, `dec%>0`, fallback plays reference loop | 3a/3b work proceeds |
| 3a | ttyd+tmux units + Caddy(host-net, loopback) + minimal shell | type in dash → Claude responds | soak continues |
| 3b | watcherd core + watch-map/events + PostToolUse hook | **the core demo**: edit file → one panel hot-reloads, no storm | |
| 3c | Kiosk hardening (unit Restart=always, KWin rule, keyboard guards, recycle+job-guard) | Ctrl+W survives; kill auto-recovers; recycle skips running job | trails into 4–5 |
| 4 | Glance panel + mode.js state mechanism + views in layout.json | command → dash morphs; view switch works | |
| 5 | modectl + manifest schema + 2 personas (Immich exports now ready) **+ flair installs as switch points + TTS consumer** | `mode X` round-trips all 8 points twice; TTS announces | |
| 6 | Immich hero tile + API wiring (indexing long done) | hero tile live | |
| 7 | GenAI pipeline (GPU1; bulk generation gated on phase-2 soak) | one loop end-to-end benchmarked; nightly timer on | parallel from 2 |
| 8 | persona-create as first real overhaul job → **§4.6 full drill** | one-prompt persona (all 8 points, generated); interrupt+resume; broken-candidate visible recovery | |
| 9 | Sim Lab (newton env, templates, runner, rerun panel) | prompt → sim → live viewport; zombie cleanup | |
| 10 | Studio (Resolve+MCP, Kdenlive, render-ops panel) | Claude cuts a reel; Resolve MCP rough-cut | |
| 11a | Twenty + MCP (board panel) | board in dash; Claude moves a candidate via MCP | |
| 11b | n8n sequences (OAuth ready since 0) | test-thread sequence with auto-stop | |
| 12 | Frigate + sensors + voice input + remaining flair/backlog | presence drives fx; snapshot-on-demand tool works | startable after 3b |

## 17. Open risks (tracked)

1. SVWR on NVIDIA/Wayland (#290/#292, suspend-UVM) — phase-2 soak decides; driver fallback ready. [TEST]
2. Loop-seam hitch at 3×3440×1440 — closed-GOP + test; driver fallback. [TEST]
3. KWin rule pinning kiosk to DP-2. [TEST]
4. Delegated `zfs allow` snapshot on this OpenZFS build. [TEST]
5. Klassy OBS target for 26.04. [TEST]
6. Resolve on 26.04 (t64/glib, XWayland). [TEST]
7. `CUDA_DISABLE_PERF_BOOST` effect. [TEST]
8. Immich cookie-in-iframe across loopback ports. [TEST]
9. Output-cycling stability under `fx away` (soak item). [TEST]
10. Docker-group root-equivalence remains the honest ceiling of the envelope (§3.8, §4.4).
11. Model landscape drift — re-check HF trending at phase 7.

## 18. Cut / deferred (deliberate)

LookAndFeel packages · Genesis · custom SDK chat UI (stage 2) · gridstack · custom animated-SVG
cursor authoring · Firefox theme extension · VACE outpaint when direct 21:9 works · monitor-
facing PTZ · Beszel (later, host-binary agent, only if Glance tiles prove insufficient) ·
Cal.diy (Google appointment pages first) · boolean/X-ray widget (backlog) · keyboard-guard
Chrome extension (build only if Ctrl+W escapes in practice) · Home Assistant (until sensors
demand) · simrunnerd daemon (until buttons outgrow `claude -p`) · LinkedIn anything · bigger
UPS · internal hardware.
```

---
*Companions: `research/research-digest-desktop.md`, `research/research-digest-mission-control.md`,
`research/design-review-panel.md`, `BRIEF_FOR_AI_TEAM.md`.*
