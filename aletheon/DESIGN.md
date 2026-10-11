# ALETHEON MISSION CONTROL — Systems Design v3

> 2026-10-11. Supersedes `DESKTOP_UPGRADE_PLAN.md` (now historical).
> Provenance tags used throughout:
> **[VERIFIED]** = confirmed against primary sources (repos/release notes/source code) by a
> 66-agent research+adversarial-verification pass, Oct 2026 — details in `research/*.md`.
> **[DECIDED]** = Leo's explicit decision. **[PROPOSED]** = design, not yet run on this machine.
> **[TEST]** = must be validated on the machine before building on it.
> External review: 4 AI critiques folded in (overhaul-orchestration feedback incorporated in §4,
> with corrections where proposals were technically wrong — see §4.7).

---

## 0. One-paragraph summary

A **Mission Control** master page runs fullscreen on the top monitor with a **static Claude
terminal panel at its center**; Claude Code runs on the host and edits plain-text files (and
calls service APIs) that drive every other panel, which hot-reload around it. A **persona/mode
system** re-skins the entire machine in one command — always-on video wallpapers on the work
monitors, Plasma colors/cursor/lock-screen, dashboard theme, browser color. **Major changes run
as resumable, checkpointed overhaul jobs** with validation gates and recovery that lives outside
the thing being changed. The dual 5090s split duty: GPU0 drives displays + wallpaper decode,
GPU1 runs sims/ComfyUI/ML. Everything lives in one git repo (`/blazing/stack`) that any Claude
session reads to get total context.

---

## 1. Goals and hard boundaries

**Goals (Leo's asks):**
1. Full-screen video wallpaper playing at all times on the work monitors. [DECIDED: always-on,
   30/60fps loops, with an `fx` dial to lower/pause before heavy GPU use or time away]
2. One-command persona switch across the whole system; Claude can also *generate a brand-new
   persona from a prompt* (find content, generate content, render the theme).
3. Mission Control dashboard with a central Claude chat box; typing a command in the dash
   modifies the dash (Claude panel static, everything else live). [DECIDED]
4. Prompt-driven GPU physics sims with live 3D viz, live plots, logs, GPU use visible.
5. A video editing studio (GUI + Claude-scriptable lane). [DECIDED: Resolve Studio purchase]
6. A recruiter control panel (pipeline, follow-ups, calendar/email, sequences, notes).
   [DECIDED: LinkedIn Recruiter + Gmail/GCal integration targets]
7. Cutting-edge visuals: cursor, KWin effects, browser theming.
8. Cameras/mic/speaker as system senses. [DECIDED: top-line webcam; motion cams for life
   capture; mic + speaker; sensors welcome. Monitor-facing camera CUT — screen capture is
   strictly better]

**Hard boundaries:**
- **No LinkedIn automation** of any kind (bots/scrapers/auto-messaging). LinkedIn UA §8.2
  prohibits it, enforcement is active, Talent APIs are partner-gated beyond individual reach.
  [VERIFIED] Email/calendar/CRM automation is the legitimate Gem-equivalent surface.
- **No internal PC hardware purchases** (no RAM/VRAM/storage). [DECIDED]
- **No `--dangerously-skip-permissions`** for the dashboard Claude session — Anthropic reserves
  bypass for isolated containers/VMs; interactive default is `auto` mode (classifier-reviewed).
  [VERIFIED]
- The **login screen (GDM) does not join the mode system** (root-owned GNOME greeter). Optional
  deliberate one-time switch to SDDM/Plasma Login Manager later (§8.6). [VERIFIED]
- Apple aerial packs: **private offline use only**; no license exists for redistribution. [VERIFIED]
- Claude never records calls without consent; work-ATS data stays off this personal machine.

---

## 2. Architecture overview

```
                    DP-2 (top, 3440x1440@240): MISSION CONTROL KIOSK
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  machine tiles │ world feeds │        CLAUDE          │ me/photos tile   │
 │  (Glance +     │ (Glance)    │  ttyd → tmux → claude  │ (Immich API)     │
 │   GPU/ZFS API) │             │  [STATIC IFRAME,       │ recruiter board  │
 │  sim viewport  │ render-ops  │   served direct]       │ (Twenty)         │
 │  (rerun)       │ panel       │                        │                  │
 └──────────────────────────────────────────────────────────────────────────┘
   DP-3 bottom-left: work (video wallpaper)   DP-1 bottom-right: work (video wallpaper)

 HOST                                     DOCKER (data-root on /blazing/docker)
 ─ claude (tmux session "claude")         ─ caddy        gateway :8080 (127.0.0.1 ONLY)
 ─ ttyd 1.7.7  (127.0.0.1:7681)           ─ glance       dashboard content
 ─ watcherd    (SSE reload + jobs API)    ─ immich stack (server/ML-cuda/pg/redis)
 ─ beszel-agent (HOST binary: ZFS+GPU)    ─ beszel hub   (phase 2)
 ─ sim runner  (systemd-run, GPU1)        ─ twenty       CRM (phase: recruiter)
 ─ overhaulctl (checkpoint/validate/      ─ n8n          email/cal automation (phase: recruiter)
   activate/rollback)
 ─ modectl / fx / persona-create
 ZFS: blazing/{stack,modes,hf,docker,generated}  scratch/{proxies,simruns}  tank/{photos,frigate,backup}
```

**The self-modification loop** (the core demo): Leo types in the Claude panel → Claude (host)
edits files in `/blazing/stack` or calls a panel's API (Twenty MCP, Immich REST) → `watcherd`
(inotify/chokidar, debounced 1.5s, path→panel routing map) emits a typed SSE event → the shell
reloads **only the affected iframe** (CSS swaps a `<link>` with cache-buster; Glance gets a ~1s
delay so its own server-side fsnotify reload finishes first [VERIFIED]). The Claude iframe is
never remounted. Mutation paths are **documented per panel in CLAUDE.md**: file-driven (Glance
YAML, shell layout/theme, Caddyfile, mode files) vs API-driven (Twenty via MCP, Immich via REST,
n8n via webhooks) — so "add a column to my pipeline" goes through the right channel instead of
silently doing nothing.

---

## 3. Safety floor (build before anything glows)

1. **ZFS dataset layout + snapshots.** Create real datasets so checkpoints are targeted:
   `blazing/stack`, `blazing/modes`, `blazing/hf`, `blazing/docker`, `blazing/generated`,
   `tank/photos`, `tank/backup`, `tank/frigate`. Install `sanoid`: hourly snaps on
   `rpool/USERDATA` + `blazing/stack` + `blazing/modes`, daily on `tank`, auto-pruned.
2. **Photos to the mirror.** Move the iCloud library to `tank/photos` (mirrored HDDs); Immich
   mounts it `:ro`. `/blazing` keeps only caches/derived data. (The one irreplaceable dataset
   stops living on a single unmirrored NVMe.)
3. **Repos to private GitHub.** `/blazing/stack` is a git repo from day 0; post-commit push.
4. **Agent browser profile.** Dedicated Chrome profile for anything agent-driven: no saved
   passwords, no autofill, no payment methods.
5. **UPS + load-shedding.** [DECIDED: keep existing CyberPower 1500] `nut` watches it over USB.
   On-battery event → `powerguard` sheds load **immediately**: `nvidia-smi -pl 150` on both
   GPUs, pause sim/ComfyUI queue (SIGSTOP), `fx paused` — draw drops under the UPS ceiling in
   seconds; graceful shutdown (stop containers, `zpool sync`) if outage persists >60s. This
   closes the only real gap (blackout during heavy compute) without new hardware.
6. **Offsite** (pending Leo's call): Backblaze B2 via rclone cron for `tank/photos` (~$2/mo,
   encrypted, keys stored off-machine). Without it, fire/theft/ransomware has no answer.
7. **Docker on ZFS.** Set Docker `data-root: /blazing/docker`; overlay2-on-ZFS works on
   OpenZFS 2.2+/Ubuntu 26.04 — verify `docker info | grep -A1 Storage`. [VERIFIED]

---

## 4. The Overhaul Engine (`overhaulctl`) — one prompt, one recoverable operation

Adopted from external review, with corrections (§4.7). Principle:

> **Major changes run as resumable, testable overhaul jobs, with automatic activation inside an
> established permission envelope and recovery independent of the changed application.**

### 4.1 Job model (coordinator outside the conversation)

A job is a **directory**, not a chat transcript: `/blazing/stack/jobs/<id>/`
```
spec.json      # the compiled change spec (schema §4.2)
state.json     # machine-updated: current wave, completed tasks, checkpoint names, attempt counts
plan.md        # human/Claude-readable intent, acceptance criteria, preserve-list
log/           # per-wave logs, assertion outputs
artifacts/     # generated configs/assets staged here before activation
```
Any Claude session (or `claude -p --resume`) can resume a job from `state.json` after a crash,
closed browser, or context loss. The runner is deterministic; Claude's job is to *write the spec
and the staged files*, the runner's job is to *execute waves and judge assertions*.

### 4.2 OVERHAUL_SPEC schema (v1)

```json
{
  "id": "brutalist-scifi-001",
  "intent": "one-sentence goal",
  "preserve": ["tank/photos", "immich db", "tmux session claude", "jobs/*"],
  "acceptance": ["mode brutalist applies end-to-end", "all panels 200", "kiosk visible"],
  "limits": { "max_wave_attempts": 2, "max_budget_usd": 15, "gpu": 1 },
  "checkpoint": { "zfs": ["blazing/stack", "blazing/modes"], "git": true },
  "waves": [
    { "n": 1, "type": "asset_gen",  "gpu": 1, "tasks": ["gen stills", "gen loops"] },
    { "n": 2, "type": "configs",    "tasks": ["stage glance theme", "stage mode.conf", "stage shell css"] },
    { "n": 3, "type": "validate",   "tasks": ["caddy validate", "docker compose config", "glance config:validate", "jq/yq lint"] },
    { "n": 4, "type": "activate",   "tasks": ["sync staged→live", "compose up -d (changed services)", "modectl apply", "SSE reload"] },
    { "n": 5, "type": "probe",      "tasks": ["healthz sweep", "kiosk pingback", "GPU0 headroom", "assertion list"] }
  ],
  "rollback": "git revert of activation commit + compose up -d + modectl apply <previous>; zfs rollback ONLY manual, services stopped"
}
```

### 4.3 Lifecycle

**Inspect → Plan/Spec → Checkpoint → Build (staged) → Validate → Activate → Probe → Observe →
Record.** Checkpoint = `git commit -A` on `/blazing/stack` + `zfs snapshot` of the datasets the
spec names. Build writes **only** to `jobs/<id>/artifacts/` and `staging/` paths. Validate is
syntax/dry-run only (`caddy validate`, `docker compose config`, `python -m py_compile`,
`jq`/`yq`, Glance config check). Activate is a **small, ordinary diff**: rsync staged files to
live paths in one git commit, `compose up -d` only for services whose config changed, `caddy
reload`, `modectl apply`, SSE events. Probe runs the assertion list; on failure the runner
auto-reverts the activation commit, re-ups services, and writes a failure report to the job dir
— **bounded repair attempts (2 per wave), then stop with a report, never loop declaring success.**

### 4.4 Permission envelope (enforced, not promised)

- Claude Code **deny rules** in `/blazing/stack/.claude/settings.json`: no Edit/Write to
  `bin/**` (the runner + recovery scripts), `jobs/*/state.json`, `.git/**`, systemd unit sources
  for watcherd/overhaulctl. The runner refuses specs that touch `preserve` paths.
- Headless invocations carry `--max-budget-usd` and `--max-turns`. [VERIFIED flags exist]
- ZFS snapshots are root-owned; Claude runs as leo — snapshot deletion is simply not reachable.
- Recovery lives OUTSIDE the app being changed: `overhaulctl rollback <id>` is callable from any
  TTY/Konsole on the work monitors; the tmux `claude` session survives kiosk/gateway death; the
  ttyd iframe is served **directly from ttyd's port, not through Caddy**, so a broken Caddyfile
  cannot take down Claude's own panel. [addresses self-lockout gap]

### 4.5 Component contracts

`/blazing/stack/contracts/<component>.md` — one page each: start/stop/health command, data it
owns, interfaces others depend on, export/restore procedure, essential-function test,
permissions required. Claude reads these before replacing a component.

### 4.6 First demonstration (acceptance for the engine itself)

One prompt replaces the dashboard layout and two personas, **preserves the active chat and all
stored data, survives a mid-build interrupt (resume from state.json), and recovers from a
deliberately broken candidate** (bad Caddyfile planted in staging → validate catches it; bad
shell page planted past validate → probe pingback fails → auto-revert). Until this demo passes,
the engine is not "done".

### 4.7 Corrections to the proposed designs (why this differs from the pasted critiques)

- **`zfs rollback` is not a casual undo**: it only targets the *most recent* snapshot (older
  requires destroying intervening ones) and yanking a mounted dataset under running containers
  corrupts their view. It is the **manual, last-resort** path with services stopped. The routine
  rollback is `git revert` + `compose up -d` — configs are tiny; data migrations rehearse on a
  **`zfs clone`** instead.
- **Atomic symlink cutover doesn't retarget running containers**: bind-mounts resolve at
  container start. Cutover is therefore "small diff + `compose up -d` for changed services", not
  symlink magic.
- **"Compositor latency < 10 ms" is not a practical assertion** — no stable public metric.
  Probes are: HTTP 200 sweep, `kiosk pingback` (shell JS POSTs a heartbeat to watcherd after
  render), GPU0 VRAM headroom, service health, `tmux has-session -t claude`.
- **No watchdog-triggered automatic `zfs rollback`.** A watchdog that nukes state on a 60s
  timeout will eventually fire during a slow boot and destroy good state. The watchdog
  (systemd) restarts *services* and reverts *the last activation commit*; dataset rollback is
  human-initiated.

---

## 5. Mission Control shell

- **One master page** in one Chrome kiosk window pinned to DP-2 — beats KWin-tiled windows on
  theming, layout animation, and Claude-editability. [VERIFIED comparison]
- **Shell = static HTML + CSS grid + vanilla JS + iframes. Zero build step.** Persona = one CSS
  custom-properties file + `layout.json`. No Vite dev server in production (documented unbounded
  RAM growth over days [VERIFIED]); no gridstack (Claude editing layout.json IS rearranging).
- **Gateway**: Caddy in compose, **site address `127.0.0.1:8080`** (never 0.0.0.0 — a writable
  Claude terminal must not be LAN-reachable; verify with `ss -tlnp` after every reload; smoke
  test: curl from another host must fail). WebSockets proxied automatically; SSE flushes
  automatically; `header_down -X-Frame-Options` only where needed. [VERIFIED]
- **Frame/auth facts** [VERIFIED]: Glance, Immich, ttyd, rerun send no frame-blocking headers;
  Beszel (PocketBase) sends `X-Frame-Options: SAMEORIGIN` — unblock via its `CSP` env var.
  **Immich cannot live under a subpath** — it stays on its own port; different localhost ports
  are same-site, so its SameSite=Lax session cookie works in the iframe. Decide origins BEFORE
  wiring panels.
- **watcherd** (~150-line Node or Python daemon, host): inotify/chokidar watch on
  `/blazing/stack/{shell,glance,modes,state}` → debounce 1.5s → path→panel map → typed SSE at
  `/events` (via Caddy). Also hosts: `POST /reload/<panel>`, kiosk heartbeat, the sim-runner API
  (§10), powerguard hooks. A Claude Code **PostToolUse hook** (matcher `Edit|Write`, async,
  filtered to stack paths) POSTs the same events — belt and braces. [VERIFIED hook mechanics]
- **Keyboard reality** [gap-verified]: Chrome kiosk does NOT suppress Ctrl+W/T/N — and Ctrl+W is
  constant terminal muscle-memory. Layers: top-level `keydown` preventDefault for the dangerous
  combos (works while shell has focus), a tiny `--load-extension` that guards close shortcuts +
  onBeforeUnload (covers iframe focus), `Restart=always` as backstop. Clicking the Claude panel
  explicitly focuses its iframe; the shell shows a visible focus ring so "my typing goes
  nowhere" is never silent.
- **Kiosk ops**: Chrome ≥140 is native Wayland automatically on a Wayland session (the
  `--ozone-platform-hint` flag was REMOVED; don't cargo-cult it) [VERIFIED]. Wayland clients
  can't self-position → one KWin window rule matching the kiosk's dedicated
  `--class=missioncontrol --user-data-dir=...` forces Screen=DP-2 + Fullscreen ([TEST] verify
  once with "Detect Window Properties"). Run as a **systemd user service**
  (`After=plasma-kwin_wayland.service`, `WantedBy=graphical-session.target`,
  `Restart=on-failure`, `MemoryMax=14G` backstop) + a 04:30 recycle timer that **skips if the
  tmux claude pane had output in the last 10 min** (`tmux display -p '#{t:window_activity}'`).
  State survives recycles: tmux holds the session, Chrome profile persists, panels re-auth from
  cookies. [VERIFIED pattern + gap fix]
- **Screen blanking**: Plasma Wayland has NO per-monitor idle blanking (kscreen-doctor --dpms
  hits all screens) [VERIFIED]. Disable auto screen-off; `away` mode scripts
  `kscreen-doctor output.DP-1.disable output.DP-3.disable` and `fx paused`.
- **Plasma version policy**: `apt-mark hold` Plasma at 6.6.6. 6.7.0/6.7.1 ship a KWin crash when
  Chromium toggles fullscreen (KDE bug 521722 — the kiosk is exactly that) and 6.6.x has NVIDIA
  triple-buffering disabled (frame pacing). Move only when Ubuntu ships ≥6.7.3 AND the 521722
  fix is confirmed; re-test kiosk fullscreen immediately after. [VERIFIED]

## 6. The Claude panel

- **Stage 1 (now)**: `ttyd -W -i 127.0.0.1 -O -t disableLeaveAlert=true -t titleFixed=Claude
  -t 'theme={...}' tmux new -A -s claude claude` — the real Claude Code TUI (streaming,
  permission prompts, Shift+Tab modes) inside the dash for free. ttyd 1.7.7 binary (active
  project, slow releases) sets no frame headers → iframes cleanly. [VERIFIED]
- **Auth**: basic-auth prompts are BLOCKED inside iframes (Chrome ≥59), so `-c user:pass` would
  blank the panel [gap-verified]. On pure-localhost this is moot (nothing else can reach it);
  if a credential is ever wanted, Caddy injects `header_up Authorization "Basic ..."` on a
  gateway route instead. The panel iframe is served **direct from :7681**, bypassing Caddy
  (survives gateway breakage).
- **tmux discipline**: `setw -g aggressive-resize on`; attach from other terminals with grouped
  sessions (`tmux new-session -t claude`) so a Konsole attach doesn't shrink the dash panel;
  `set -g history-limit 50000` (scrollback survives kiosk recycles because ttyd re-runs
  `tmux new -A`). [gap fix]
- **Permission mode**: `auto` (default) or `acceptEdits` for the panel session. Scoped dashboard
  buttons shell out to `claude -p --output-format stream-json --resume <pinned-session>
  --allowedTools ...` with budget caps. [VERIFIED flags]
- **Stage 2 (optional later)**: custom chat panel on `@anthropic-ai/claude-agent-sdk` 0.3.x —
  an **official example exists**: `anthropics/claude-agent-sdk-demos` → `simple-chatapp`
  (React+Express+ws). [VERIFIED] Only if the terminal aesthetic stops being enough.
- **Phone**: Tailscale-bound ttyd or Happy (slopus/happy, MIT, active) later; CloudCLI
  (siteboon/claudecodeui, 14k★, AGPL) as a separate full-screen tab if wanted — needs Node 22+
  (upgrade Node anyway: Node 20 is past EOL). Dead ends to avoid: sugyan/claude-code-webui
  (archived), Crystal (deprecated), Conductor (Mac-only), sshx (no self-host). [VERIFIED]

## 7. Video wallpaper layer + fx dial

- **Engine**: Smart Video Wallpaper Reborn v2.16.0, plugin ID
  `luisbocanegra.smart.video.wallpaper.reborn` (KDE Store 2139746). Plasma-6-native, per-screen
  videos (per-containment config), playlists/crossfade, lock-screen capable, pause conditions,
  dark/light per-mode videos (v2.15+). Deps: `libqt6multimedia6 qml6-module-qtmultimedia`.
  Do NOT use mpvpaper (plasmashell's opaque desktop occludes it — maintainer: unsupported on
  KWin); catsout WE plugin is archived (successor waywallen = fallback only). [VERIFIED]
- **Decode**: Qt Multimedia FFmpeg backend + NVDEC via
  `QT_FFMPEG_DECODING_HW_DEVICE_TYPES=cuda` — set in **`~/.config/environment.d/`**, NOT the
  plugin UI, so `kscreenlocker_greet` inherits it too (separate process!). Confirm decode with
  `nvidia-smi dmon -s u` (dec% > 0 = hardware; 0% = bug, not success). [gap fix, VERIFIED]
- **Per-screen policy** [resolves the always-on vs power contradiction]:
  DP-1 + DP-3: video, `PauseMode=3` (never) per Leo's call, pause-on-screen-off stays on.
  **DP-2: static per-mode image** — the fullscreen kiosk hides it; decoding behind an opaque
  window is pure waste.
- **Content spec**: 3440×1440-native loops, 24–30fps default (60 for showcase modes), HEVC
  10-bit NVENC, single closed GOP, 20–40 Mbps. Not 4K/60 — scaling + the plugin's known Qt
  Multimedia overhead (2–3× mpv's GPU util, issue #18) are the real costs, not NVDEC. [VERIFIED]
- **`fx` dial** [DECIDED]: `fx full|low|paused|away` — writes PauseMode/enabled per screen via
  the same evaluateScript mechanism + pauses Glance animations + (away) disables work outputs.
  Dash toggle + CLI + auto-hooks (sim runner sets `fx low` while a job runs on GPU0… normally
  none do; powerguard sets `fx paused` on battery; presence sensor can drive `away`).
- **Exact switch mechanism** [VERIFIED from plugin source]:
  ```js
  // qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '...'
  for (var key in desktops()) { var d = desktops()[key];
    if (d.screen < 0) continue; var g = screenGeometry(d.screen);
    // 0,1440=DP-3  3440,1440=DP-1  1699,0=DP-2 (match by geometry, not index)
    d.wallpaperPlugin = "luisbocanegra.smart.video.wallpaper.reborn";
    d.currentConfigGroup = ["Wallpaper","luisbocanegra.smart.video.wallpaper.reborn","General"];
    d.writeConfig("VideoUrls", JSON.stringify([{filename:"file:///blazing/modes/<m>/videos/"+screenTag(g)+".mp4",enabled:true,duration:0,customDuration:0,loop:true}]));
    d.writeConfig("PauseMode", 3);
  }
  ```
  Lock screen: `kwriteconfig6 --file kscreenlockerrc --group Greeter --key WallpaperPlugin ...`
  + nested `[Greeter][Wallpaper][<id>][General] VideoUrls`; applies at next lock. [VERIFIED]
- **Week-1 soak gate** [gap fix]: install with 3 ffmpeg test loops; run multi-day soak covering
  lock/unlock, screen-off, mode switches, and **`systemctl suspend`** (open 5090 bug: suspend
  deadlock in nvidia_uvm with hw-decoded video wallpaper — if it reproduces, lock screen falls
  back to static images). Fallback chain: GStreamer backend → waywallen. Only after the soak
  passes does bulk GPU asset generation start. Known NVIDIA/Wayland issues exist on the plugin's
  tracker (#290/#292 black-screen/crash) — mitigations: `QSG_RHI_BACKEND=vulkan`,
  `QT_DISABLE_HW_TEXTURES_CONVERSION=1`. [VERIFIED risks]

## 8. Persona/mode system

### 8.1 Layout
```
/blazing/modes/<name>/
  mode.conf           # COLOR_SCHEME, CURSOR_THEME, LOOKANDFEEL_ID, GLANCE_THEME, KANDO_THEME,
                      # BROWSER_HEX, DECO (optional), DP2_IMAGE
  videos/dp1.mp4 dp3.mp4     stills/dp2.png lock.{mp4,png}
  glance-theme.yml    # $include'd by glance.yml
  shell.css           # CSS custom properties for the shell
```
State: `/blazing/stack/state/mode.json` (bind-mounted into Glance's assets dir so the injected
`mode.js` can `fetch('/assets/state/mode.json')` — a browser page cannot read local files; this
is the concrete design the research critic demanded). [gap fix]

### 8.2 `modectl apply <name>` — the 8 switch points (all live, no logout) [VERIFIED each]
1. `plasma-apply-lookandfeel -a <mode-id>` (4 hand-written LookAndFeel kpackages bundle
   colorscheme/icons/cursor/deco defaults; installed via `kpackagetool6 -t Plasma/LookAndFeel -i`)
   — or individually: `plasma-apply-colorscheme` (NOTE: re-applying a modified scheme requires a
   different name — alternate two names), `plasma-apply-cursortheme`, `plasma-apply-desktoptheme`.
2. Wallpaper videos per screen via evaluateScript (§7) + DP-2 static via `org.kde.image`.
3. Lock screen via `kwriteconfig6` on `kscreenlockerrc`.
4. Konsole: loop `org.kde.konsole*` D-Bus services → `/Sessions/N setProfile <Mode>` + default
   via `konsolerc`.
5. Kando: rewrite `menuTheme`/`menuThemeColors` in `~/.config/kando/config.json` (hot-reloaded).
6. Panel accents: panel-colorizer v8 D-Bus preset switch.
7. Window decorations: `kwin-applywindowdecoration` (+ `qdbus6 org.kde.KWin /KWin reconfigure`).
8. Dashboard: write `state/mode.json` + swap `glance-theme.yml` include → Glance hot-reloads
   server-side; `mode.js` calls `/api/set-theme/<mode>` (live CSS, cookie-persisted) and reloads
   the iframe only on layout change; shell.css swap via SSE.

### 8.3 Browser theming [VERIFIED]
- **Chrome = the easy win**: `{"BrowserThemeColor": "#<accent>"}` into
  `/etc/opt/chrome/policies/managed/mode.json` — Chrome file-watches policies on Linux and
  re-skins running windows in seconds. One-time setup: `sudo install -d -o leo
  /etc/opt/chrome/policies/managed` so modectl needs no sudo. Verify the browser is the Chrome
  .deb, not snap Chromium (different policy path + confinement). Dark/light rides the
  xdg-desktop-portal automatically (Chrome ≥114).
- **Firefox**: per-mode profiles with preinstalled themes (zero code). The custom
  browser.theme.update() extension is CUT from v1 (second bespoke daemon for a secondary
  browser). policies.json/userChrome.css are startup-only — provisioning, not switching.

### 8.4 Cursors [VERIFIED + cut applied]
Plasma 6 SVG cursor format supports animated cursors; Breeze ships them. Live switch via
`plasma-apply-cursortheme` (XWayland apps lag until restart). **v1 uses 4 existing maintained
themes** (Breeze variants, Bibata colorways, Oreo) — hand-authoring recolored animated SVG sets
is days of work for a 32px payoff; revisit with `phisch/cursor-theme-builder` later.

### 8.5 `persona-create "<prompt>"` (runs as an overhaul job)
Claude: names the persona → generates stills (FLUX.2 FP8) + 2 loops (Wan FLF2V pipeline §9) on
GPU1 → derives a color scheme from the imagery (quantize → KDE colorscheme file, alternate-name
trick) → picks cursor from the installed set → writes mode dir + LookAndFeel package + Glance
include → validate wave → `modectl apply`. KDE Store assets (themes/cursors) fetch via
`kpackagetool6`/direct GitHub rather than the GUI "Get New" dialogs.

### 8.6 Login screen decision (Leo, one-time)
GDM = static login forever. His on-machine plan already chose SDDM but never applied it.
Recommendation: switch to SDDM (or Plasma Login Manager, which uniquely supports the video
wallpaper plugin on the login screen) during a quiet moment — deliberate migration, not part of
mode switching. Until then: assert `XDG_SESSION_TYPE=wayland` at the top of modectl (if GDM ever
falls back to X11, every mechanism here runs in the wrong world — exit loudly). [gap fix]

## 9. Generation pipeline (GPU1)

- **PyTorch**: stable 2.14.x **cu130 — no nightly**. sm_120 has been in stable since 2.7;
  cu130 is the PyPI default since 2.11. TECH_STACK.md's "nightly only" note is stale — rebuild
  envs accordingly. Verify `torch.cuda.get_device_capability() == (12,0)`. [VERIFIED]
- **nvcc reality check** [gap fix]: "CUDA 13.0" in nvidia-smi is the driver API, not the
  toolkit. SageAttention compiles from source → install `cuda-nvcc` 13.x **inside the conda
  env** (matches the cu130 wheel), `pip install ninja`. ComfyUI runs `--disable-xformers`
  (prebuilt xformers tops out at sm_89 and pip-installing it can silently replace torch).
  [VERIFIED]
- **Weights** (~400GB, gated) [gap fix]: `pip install -U "huggingface_hub[cli]"`, `hf auth
  login`, accept FLUX.2-dev (and LTX-2.5 if used) licenses in the browser first;
  `HF_HOME=/blazing/hf`. Per Leo's rule weights are refetchable — but itemized: Wan2.2 A14B fp8
  (both experts), VACE, lightx2v Lightning LoRAs, SeedVR2 3B+7B, FLUX.2-dev FP8 (+Mistral TE,
  offloaded to 128GB RAM).
- **Loop pipeline** (trimmed per critics): FLUX.2 still at 21:9 → **Wan 2.2 14B FLF2V with the
  same frame first+last** (the one technique guaranteeing mathematically seamless loops;
  official ComfyUI template) + Lightning 4-step LoRA → generate at 21:9-friendly latent where
  tolerated (VACE outpaint only when needed) → **SeedVR2** (batch≥5, built for 32GB cards) to
  3440×1440 → encode `hevc_nvenc` 10-bit closed-GOP. **60fps interpolation CUT by default**
  (contradicts the 24–30fps power finding; RIFE available for showcase modes). [VERIFIED]
- **Aerials seed library**: Apple's `entries.json` manifest + aria2c (dmn001 downloader) — 4K
  SDR HEVC, private use only.
- **Nightly job**: systemd timer → ComfyUI API on GPU1 → new loops/stills into the active
  mode's dir → SSE refreshes the hero tile. Wan 2.5/2.6/2.7/3.0 are API-only; Wan 2.2 remains
  the open-weights flagship — re-check at build time. [VERIFIED]

## 10. Sim Lab (prompt → physics → live viz)

- **Engine**: **Newton** (`pip install "newton[examples]"`, Linux Foundation project —
  Disney/DeepMind/NVIDIA) — the successor to warp.sim (**warp.sim was REMOVED in Warp 1.10**;
  any plan or tutorial using it is dead code). Rides Warp 1.18 whose CUDA 13.4 wheels require
  exactly R580+ — this box is the blessed path. MuJoCo-Warp rigid bodies + cloth/softbody/MPM.
  Genesis = deferred (second engine before the first has run = over-engineering). Taichi =
  dormant, broken on sm_120, avoid. Isaac Sim = heavyweight optional later. [VERIFIED]
- **Viz**: rerun-sdk 0.38.x. Sim calls `rr.serve_grpc()` + `rr.serve_web_viewer()` (ports
  allocated by the runner); kiosk iframes the **locally served viewer** (offline, no app.rerun.io
  dependency). One blueprint = 3D viewport + time-series + text logs. **Viewer version must
  exactly match SDK version** — the runner generates the iframe URL from
  `python -c "import rerun; print(rerun.__version__)"` at launch. WebGPU is enabled by default
  in kiosk Chrome on this driver (Chrome ≥147 on NVIDIA/Wayland). [VERIFIED]
- **Prompt→sim pattern**: Claude fills **parameterized scene templates** (repo of vetted Newton
  scenes + YAML param schema) rather than free-writing engine code (2026 benchmarks: ~21.5%
  pass rate for freeform physics codegen); 10-step GPU dry-run validator; log-feedback repair
  loop (bounded). [VERIFIED]
- **Runner** (part of watcherd): `POST /sim/run` → `systemd-run --user --unit sim@N
  -p Environment=CUDA_VISIBLE_DEVICES=GPU-<uuid-of-GPU1> conda run -n newton python scene.py
  --viewer rerun --port <alloc>`; `POST /sim/stop`; logs tee'd to `scratch/simruns/<ts>/`;
  kills orphaned CUDA processes on failure (zombie VRAM is the #1 flakiness source). GPU UUIDs
  from `nvidia-smi -L` (two identical cards — never trust ordering). Per-process attribution
  tile via `nvidia-smi pmon -s um`/NVML. [gap fix, VERIFIED]

## 11. Video Studio

- **GUI tier**: **DaVinci Resolve Studio 21.1** [DECIDED purchase]. Why Studio is mandatory on
  Linux: free edition cannot decode H.264/HEVC at all (the 3,784 iPhone clips), AAC is
  unsupported on Linux in BOTH editions (one-time `ffmpeg` audio transcode pass into an edit
  cache on `scratch`), and 21.1 removed Python scripting from free. Studio adds dual-5090
  processing and — the kicker — a **native MCP server (File → Setup AI Assistants) officially
  supporting Claude Code** (~88 tools: organize media, rough cuts, batch render). Install
  frictions are known: t64 package renames + bundled-glib removal on Ubuntu 26.04
  (MakeResolveDeb is the clean wrapper); runs under XWayland (`QT_QPA_PLATFORM=xcb` if it
  crashes on startup). [VERIFIED]
- **Everyday/scriptable tier**: **Kdenlive** native apt package (26.04 ships 25.12.3 with
  working NVENC; the KDE backports PPA has 26.08.2 — avoid the Flatpak: sandboxed libcuda breaks
  NVENC). Built-in Whisper subtitles; projects are MLT XML → Claude generates/edits them as text
  and renders headlessly with `melt`. [VERIFIED]
- **Claude's programmatic lane**: WhisperX transcripts → Claude picks segments → ffmpeg 8
  (`hevc_nvenc`/`av1_nvenc -preset p7 -tune hq`) extract+concat; `auto-editor` for silence cuts
  (exports Kdenlive/Resolve project files for human polish). iPhone HDR is Dolby Vision P8.4 =
  plain HLG base layer: tone-map with `zscale+tonemap=hable` or libplacebo bt.2390 when
  delivering SDR — never naive-scale (gray washed-out output). [VERIFIED]
- **Dash panel = "render ops", not an embedded editor** (a Qt app can't live in an iframe —
  integration gap the critics caught): job queue, NVENC utilization, transcript status, buttons
  that POST to watcherd to launch Kdenlive/Resolve placed by KWin rule on a work monitor.
- **One ASR stack for everything** [cut applied]: a single `asr` conda env (faster-whisper ≥1.2 /
  CTranslate2 ≥4.8 — the old "INT8 disabled on sm_120" caveat was fixed; WhisperX for word-level)
  serves studio subtitles AND recruiter notes; Kdenlive imports the SRT.

## 12. Recruiter cockpit [DECIDED: Gmail/GCal + LinkedIn Recruiter workflow]

- **Pipeline**: **Twenty CRM** (v2.4x, weekly releases, 58k★) — kanban + REST + GraphQL +
  webhooks + **first-party MCP server** registered in `.mcp.json` → "move Jane to Offer,
  schedule follow-up Friday" becomes direct tool calls. [VERIFIED]
- **Email/Calendar**: own Google Cloud project, OAuth **Desktop** client, External type,
  consent screen **published to In-Production** (Testing-mode refresh tokens die every 7 days
  — the classic trap). n8n (Sustainable Use License covers personal self-hosting) runs Gmail
  triage + **Gem-style sequences**: Claude-personalized multi-step email campaigns from Leo's
  own Gmail, auto-stop on reply, follow-ups surfaced as dash tiles via Glance custom-api
  widgets. [VERIFIED]
- **Scheduling**: Cal.diy (calcom repo, MIT since Apr 2026, personal-use) or Google Calendar
  appointment pages. **Capture**: paste-in — Leo copies a profile/URL; Claude structures it
  into Twenty and drafts outreach for manual sending. A home-built boolean/X-ray search builder
  widget (no OSS recruiter dashboard worth adopting exists). [VERIFIED]
- **Workspace command**: `workspace recruiting` launches/places LinkedIn Recruiter, Gmail,
  pipeline board windows via KWin rules on the work monitors.
- **Interview notes**: watch-folder on scratch → asr env transcribes → `claude -p` summarizes
  into Twenty notes. Consent required, always.

## 13. Senses: cameras, voice, sensors [DECIDED to buy]

- **Webcam** (calls/recording): top-line UVC PTZ-class (e.g. Insta360 Link 2-class) or
  mirrorless + capture card for true top-of-line; OBS virtual cam. Final model picks verified
  for Linux UVC at purchase time. [PROPOSED]
- **Room cams** (life capture): 2–3 PoE/ONVIF cameras under **Frigate NVR** — local GPU object
  detection, events to `tank/frigate`, zero cloud. Clips flow into Immich/studio. [PROPOSED]
- **Monitor-facing PTZ: CUT** — Wayland screen capture gives Claude lossless pixels; a camera
  adds glare and moiré. Claude self-verifies output via Spectacle/PipeWire screenshots.
- **Voice**: mic → asr env (push-to-talk → Claude); speaker ← Piper/Kokoro TTS announcements
  from watcherd events ("render done", "sim finished", "next call in 10"). [PROPOSED]
- **Sensors**: power-metering smart plug on the PC circuit (live watts tile — real data for the
  UPS/power story) + mmWave presence at the desk (drives `fx away`/lock). Home Assistant enters
  only if sensor count grows. [PROPOSED]

## 14. GPU & power management

- **Topology** [TEST — build step zero]: verify ALL THREE DisplayPort cables are on GPU0
  (`ls -l /dev/dri/by-path/`, `kscreen-doctor -o`). If not, re-cable first — everything below
  assumes it. Pin KWin: `KWIN_DRM_DEVICES=/dev/dri/by-path/<pci-GPU0>-card` in environment.d
  (by-path = stable across boots). GPU1 carries zero display state → sims/ComfyUI/ML via
  `CUDA_VISIBLE_DEVICES=GPU-<uuid>`. Wallpaper decode CANNOT be pinned to GPU1 (plugin's GPU
  selector only separates backend *types*; both cards are CUDA) — it rides GPU0 by design.
  [VERIFIED]
- **Honest power budget**: triple-240Hz pins GPU0 VRAM clocks → ~50–90W idle regardless of
  wallpaper; continuous playback adds ~20–35W. Leo accepts this [DECIDED]. Mitigations that
  don't violate "always-on": DP-2 static, 24–30fps content, pause-on-screen-off, `fx` dial,
  `CUDA_DISABLE_PERF_BOOST` (R580 driver knob for the CUDA-context P-state floor — [TEST]).
  Measure, don't guess: before/after `power.draw`/`pstate` averages across static/paused/
  playing/gaming states; Beszel agent with `GPU_COLLECTOR=nvml` (its default nvidia-smi polling
  itself blocks idle states). [VERIFIED]
- **powerguard** (§3.5) owns UPS load-shedding.

## 15. Prerequisites — the direct answer ("what must be in the system first")

```bash
# ── preflight assertions (fail loudly) ─────────────────────────────────────
[ "$XDG_SESSION_TYPE" = wayland ] || exit 1
ls -l /dev/dri/by-path/   # all 3 DP connectors on GPU0?
for c in qdbus6 kwriteconfig6 kpackagetool6 plasma-apply-colorscheme \
         plasma-apply-cursortheme plasma-apply-lookandfeel \
         kwin-applywindowdecoration kscreen-doctor; do command -v $c || echo MISSING $c; done
google-chrome --version   # Chrome .deb, NOT snap chromium (policy paths + kiosk differ)

# ── apt ────────────────────────────────────────────────────────────────────
sudo apt install ffmpeg libqt6multimedia6 qml6-module-qtmultimedia qdbus-qt6 \
     inotify-tools ttyd tmux jq nut sanoid kdenlive
# verify: ffmpeg -encoders | grep nvenc ; ffmpeg -hwaccels | grep cuda
#         ls /usr/lib/x86_64-linux-gnu/libnvcuvid.so  (libnvidia-decode-580)
sudo add-apt-repository ppa:matinlotfali/kde-rounded-corners && sudo apt install kwin-effect-roundcorners
sudo apt-mark hold 'plasma-*' 'kwin-*'     # §5 Plasma version policy
sudo install -d -o leo /etc/opt/chrome/policies/managed    # modectl browser theming, no sudo later
# NVIDIA container toolkit (official apt repo) → nvidia-ctk runtime configure --runtime=docker
# Node 22/24 LTS via nodesource (Node 20 is EOL)

# ── Plasma pieces (no cmake needed — packages/store installs) ──────────────
# Smart Video Wallpaper Reborn (KDE Store 2139746, kpackagetool6 user install)
# Kando 3.0 .deb · panel-colorizer (store) · Burn-My-Windows kwin6 pack · KZones (store)
# Klassy: check OBS has an xUbuntu_26.04 target FIRST; else skip (Breeze + colorschemes = 90%)
# catppuccin/kde v0.4+ repo clone · 4 cursor themes (Breeze/Bibata/Oreo)

# ── conda envs ──────────────────────────────────────────────────────────────
# comfy:  python 3.12 · torch 2.14 cu130 (STABLE — no nightly) · cuda-nvcc 13.x (in-env) ·
#         ninja · sageattention 2.2 · ComfyUI clone + VideoHelperSuite + SeedVR2 nodes
# newton: newton[examples] · rerun-sdk 0.38.x (pin; viewer must match)
# asr:    faster-whisper>=1.2 · ctranslate2>=4.8 · whisperx
# HF:     pip install -U "huggingface_hub[cli]" ; hf auth login ;
#         accept FLUX.2-dev license in browser ; HF_HOME=/blazing/hf  (~400 GB budget)

# ── the stack repo (THE system of record) ──────────────────────────────────
zfs create blazing/stack blazing/modes blazing/hf blazing/docker blazing/generated
git init /blazing/stack   # CLAUDE.md, contracts/, docker-compose.yml, caddy/, shell/,
                          # glance/, modectl/, bin/ (overhaulctl, watcherd, powerguard, fx),
                          # jobs/, state/, systemd/, .claude/settings.json (deny rules), .mcp.json
```
Purchases [DECIDED]: Resolve Studio ~$295 · Wallpaper Engine $4 (content source, optional) ·
cameras/mic/speaker per §13. Not buying: internal hardware, bigger UPS (powerguard instead).

## 16. Build order (each phase exits through a gate)

| # | Phase | Gate to exit |
|---|-------|--------------|
| 0 | **Preflight**: cabling, wayland assert, CLI sweep, Chrome .deb check, Node 22, datasets + sanoid + photos→tank, Docker data-root, agent browser profile | all asserts green; snapshot/restore drill done |
| 1 | **Minimal overhaul harness**: git repo + `overhaulctl` v1 (checkpoint/validate/activate/rollback) + deny rules | §4.6 broken-candidate drill passes |
| 2 | **Wallpaper soak**: SVWR + env vars + 3 test loops + fx dial | multi-day soak incl. lock + suspend; `dec%>0` confirmed |
| 3 | **Shell + Claude panel**: Caddy (loopback), shell page, ttyd/tmux, keyboard guards, watcherd SSE, PostToolUse hook, kiosk unit + KWin rule | type in dash → edit file → panel reloads; Ctrl+W survives; kiosk auto-recovers from kill |
| 4 | **Glance panel** (+ mode.js state mechanism) | first end-to-end "command → dash morphs" demo |
| 5 | **modectl + 2 personas** (women/dogs from Immich exports once ready; interim: curated packs) | `mode X` round-trips all 8 switch points twice |
| 6 | **Immich stack** (external :ro library, CUDA ML, SigLIP2 model) — start early, indexing takes days | faces+CLIP done; hero tile live |
| 7 | **GenAI pipeline** on GPU1 (parallel from phase 2) | one loop end-to-end benchmarked; nightly timer on |
| 8 | **persona-create** as first real overhaul job (§4.6 demo = this) | one-prompt new persona, interrupted + resumed + rolled back once |
| 9 | **Sim Lab** (newton env, runner, rerun panel) | prompt → sim → live viewport; zombie-cleanup verified |
| 10 | **Studio** (Resolve Studio + MCP, Kdenlive, asr env, render-ops panel) | Claude cuts a reel by prompt; Resolve MCP drives a rough cut |
| 11 | **Recruiter** (Twenty+MCP, OAuth early — consent screen takes a session, n8n sequences, Cal.diy) | sequence runs end-to-end on a test thread; board in dash |
| 12 | **Senses + flair** (Frigate, voice/TTS, sensors; BMW/KZones/cube/Kando polish) | presence drives fx; TTS announces a render |

## 17. Open risks (tracked, with owners)

1. SVWR on NVIDIA/Wayland (#290/#292, suspend-UVM #281) — phase-2 soak decides; fallbacks named. [TEST]
2. Qt Multimedia loop-seam hitch at 3×3440×1440 — closed-GOP content + test; mpv/waywallen fallback. [TEST]
3. KWin rule pinning kiosk to DP-2 on Wayland — verify once. [TEST]
4. Klassy OBS target for 26.04 — check before adopting. [TEST]
5. Resolve on 26.04 (t64/glib workarounds, XWayland) — known fixes, verify. [TEST]
6. `CUDA_DISABLE_PERF_BOOST` effect on idle watts — measure. [TEST]
7. Immich cookie-in-iframe across ports — same-site should hold; else /etc/hosts subdomains +
   `tls internal`. [TEST]
8. Wan-2.2 era models superseded — re-check HF trending at phase 7, not before.
9. Glance theme-poll JS (`document: head:` injection) — small custom glue; keep CDP reload fallback.

## 18. Cut / deferred (deliberate, not forgotten)

Genesis engine · custom Agent-SDK chat UI (stage 2) · gridstack drag-layout · custom per-mode
animated SVG cursor authoring · Firefox theme extension · 60fps interpolation by default ·
VACE outpaint when direct 21:9 works · monitor-facing PTZ camera · Beszel (enters phase 4+ as
host-binary agent only if Glance custom-api tiles prove insufficient) · Home Assistant (until
sensor count demands it) · LinkedIn anything · bigger UPS · internal hardware.
```

---
*Companion docs: `research/research-digest-desktop.md`, `research/research-digest-mission-control.md`
(verified claims + adversarial verdicts + critic gaps, Oct 2026), `BRIEF_FOR_AI_TEAM.md`.*
