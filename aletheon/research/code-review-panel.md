
======================================================================
## LENS: correctness
VERDICT: Not deployable as-is: two first-contact breakers (setup/bootstrap.sh aborts with SIGPIPE/141 at secrets generation — empirically verified — and every `modectl apply` fails because screens.json's _comment key inflates the expected-output count) plus a cluster of major cross-file contract breaks: the shell ignores sse_action "none" and its own beforeunload guard blocks SSE-driven reloads, the sim viewer pipeline has no consumer, glance's bridge-mode container cannot reach its 127.0.0.1 widget URLs, the stock overhaul spec invokes a host caddy binary that doesn't exist (and overhaulctl's missing-

### [CRITICAL] setup/bootstrap.sh
PROBLEM: gen() is `tr -dc 'A-Za-z0-9' </dev/urandom | head -c N` (line 68) under `set -euo pipefail`. head closes the pipe after N bytes, tr is killed with SIGPIPE (exit 141), pipefail makes gen() return 141, and set -e aborts the whole script. Verified empirically: `gen 48 > file` exits 141 even though the file is written.
SCENARIO: First run ever: bootstrap writes secrets/watcherd-token at line 69 and immediately dies with status 141. ttyd.env, caddy.env, compose.env are never generated, user units are never installed, linger is never enabled, the sanoid config and gitleaks hook are never written. Re-running doesn't help: it now dies at `pass=$(gen 32)` on line 71 every time.
FIX: Make gen SIGPIPE-proof, e.g. `gen() { head -c 512 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c "$1"; }` (head on urandom terminates by itself) or `gen() { (tr -dc 'A-Za-z0-9' </dev/urandom || true) | head -c "$1"; }`, or use `openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "$1"` with the same guard.

### [CRITICAL] bin/modectl
PROBLEM: Line 92: `wp.outputs_up(expected=len(json.load(open(.../screens.json))))`. state/screens.json contains four keys — "_comment", "dp3", "dp1", "dp2" — so expected=4, but the machine has 3 outputs and `outputs_up` counts occurrences of "enabled" in `kscreen-doctor -o` (one per enabled output, max 3). 3 >= 4 is never true.
SCENARIO: Every `modectl apply <name>` dies with "outputs are down (fx away?)" even with all three monitors up. That breaks persona switching, `fx` level changes (fx calls `modectl apply`), and overhaul rollback (do_rollback runs `modectl apply --previous`, check=False, so the mode silently never reverts). Note bin/fx line 80 hardcodes expected=3 for the sam
FIX: Count only screen entries: `expected=len([k for k in json.load(open(...)) if not k.startswith("_")])`, or filter to values that are dicts with x/y keys. Better, centralize: have wallpaper_driver.screens() strip underscore keys and use `len(wp.screens())` in both modectl and fx.

### [MAJOR] bin/overhaulctl
PROBLEM: sh() (lines 25-30) passes check=False through to subprocess.run, but subprocess.run raises FileNotFoundError (not a nonzero returncode) when argv[0] does not exist. do_validate, do_probe, and reload_actions_for all assume a missing/broken command surfaces as r.returncode != 0.
SCENARIO: A probe spec entry whose binary is absent (e.g. the stock example spec's ["caddy", "validate", ...] on a host where caddy only exists inside the container) makes do_probe crash with an uncaught Python traceback BEFORE reaching the probe-failure branch — so the automatic rollback (do_rollback) never runs and the job is stranded in phase "activated" 
FIX: In sh(), when check is False, catch FileNotFoundError and return a synthetic CompletedProcess with returncode=127 and stdout=f"{cmd[0]}: not found"; when check is True, convert it to die(). That routes missing binaries through the normal validate-failed / probe-failed / auto-rollback paths.

### [MAJOR] jobs/example-spec.json
PROBLEM: The validate step runs ["caddy", "validate", "--config", "caddy/Caddyfile"] as a host command, but Caddy is only deployed as the caddy:2.10.0 container (docker-compose.yml); nothing installs a host caddy binary and bin/preflight.sh's CLI sweep does not include caddy. overhaulctl do_new copies this spec into every new job.
SCENARIO: The phase-1 drill in jobs/README.md (`overhaulctl new drill-001` → `run`) crashes at the validate phase on first contact with FileNotFoundError (compounded by the sh() bug above), so the gate exercise that is supposed to prove the overhaul machinery fails before it ever validates anything.
FIX: Change the validate entry to run inside the container: ["docker", "compose", "-f", "/blazing/stack/docker-compose.yml", "exec", "-T", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"] (matching the reload rule already in state/watch-map.json).

### [MAJOR] shell/shell.js
PROBLEM: handleEvent (line 105) does `if (panel === "shell") { location.reload(); return; }` without ever checking the action field. watcherd broadcasts the rule's sse_action verbatim, and state/watch-map.json deliberately sets panel "shell" with sse_action "none" for caddy/Caddyfile and docker-compose.yml precisely so the shell does NOT reload.
SCENARIO: Any edit to caddy/Caddyfile (inotify-watched via the caddy/ dir) or a hook-signaled docker-compose.yml edit broadcasts {panel:"shell", action:"none"} and the kiosk does a full page reload anyway — dropping panel scroll state and racing the gateway reload the SSE suppression was designed to avoid. The "none" escape hatch in the watch-map schema is d
FIX: Add `if (action === "none") return;` as the first line of handleEvent, before any panel-specific branch.

### [MAJOR] shell/shell.js
PROBLEM: guardKeys (line 153) registers `window.addEventListener("beforeunload", (e) => { e.preventDefault(); })`. In Chrome, preventDefault in beforeunload triggers the native leave-confirmation dialog for ANY navigation — including the shell's own programmatic `location.reload()` in handleEvent — once the page has sturdy user activation (which a kiosk being clicked on always has).
SCENARIO: Leo clicks around the dash, then edits state/layout.json or any shell/ file; the SSE "shell" event calls location.reload() and Chrome pops a 'Leave site?' dialog instead of reloading. The kiosk sits frozen behind a modal until someone clicks it — the opposite of the hot-reload demo this path implements. It also blocks/delays the beforeunload path d
FIX: Set a module flag, e.g. `let intentionalReload = false;`, set it true immediately before every programmatic location.reload(), and in the beforeunload handler do `if (!intentionalReload) e.preventDefault();`. (Ctrl+W/T/N/F5 are already covered by the keydown guard; the systemd Restart=always unit is the documented backstop.)

### [MAJOR] shell/shell.js
PROBLEM: bin/simrun writes viewer metadata (viewer_url) to state/sim.json (simrun line 93, comment: "watched → SSE → sim panel points at viewer_url"), and watch-map routes state/sim.json to panel "sim" — but shell.js contains no code that reads sim.json or sets the sim panel's iframe src. state/layout.json mounts the sim panel with src "about:blank", and handleEvent's generic branch (line 109) just re-assigns the existing src.
SCENARIO: `simrun run bodies` launches the sim and emits the SSE event, but the simlab view's sim panel reloads about:blank and stays blank forever. The entire §10 viewer pipeline (sim → rerun web viewer → dashboard) has no consumer end.
FIX: In handleEvent, special-case the sim panel: on {panel:"sim"} fetch /state/sim.json and set `mounted.get("sim").src = meta.viewer_url` when it changed (falling back to about:blank when the fetch fails). Caddy already serves it via handle_path /state/*.

### [MAJOR] glance/glance.yml
PROBLEM: The GPUs custom-api widget (line 17) targets http://127.0.0.1:8484/metrics/gpu and the Mode widget (line ~51) targets http://127.0.0.1:8085/assets/state/mode.json. These URLs are fetched server-side by the glance container, which runs on the default bridge network — 127.0.0.1 inside the container is the container's own loopback, not the host's, so watcherd (host loopback :8484) and the host-published :8085 mapping are both unreachable.
SCENARIO: On first `docker compose up`, the GPUs tile and Mode tile permanently show fetch errors; the dashboard's core machine-telemetry row never works. (Only caddy has network_mode: host.)
FIX: Give glance network_mode: host and set its server port to 8085 in glance.yml (removing the ports mapping), which also fixes server-stats reporting container stats; or keep bridge mode, point the Mode widget at its own container port (http://127.0.0.1:8080/assets/state/mode.json → actually /app/assets is served locally, so use localhost:8080) and front GPU metrics through a host-gateway-reachable address with watcherd bound to the docker bridge IP.

### [MAJOR] systemd/claude-tmux.service
PROBLEM: The unit combines Type=forking, RemainAfterExit=yes, and Restart=on-failure, with the comment claiming "the unit restarts it if the server dies". With RemainAfterExit=yes the unit stays 'active (exited)' after all processes are gone, and a clean exit (claude exits, Ctrl-D in the pane, `tmux kill-session`, tmux server exit 0) never matches on-failure — so nothing is restarted and `systemctl --user is-active` keeps reporting active for a dead session.
SCENARIO: Claude's process exits normally overnight; the tmux server shuts down with status 0; the unit remains active-exited; ttyd clients silently create a NEW unsupervised claude session inside ttyd.service's cgroup (ttyd runs `tmux new-session -A -s claude`), and overhaulctl's probe-failure handler restarts a unit that reports healthy while supervision i
FIX: Drop RemainAfterExit=yes and set Restart=always (clean exits must respawn, same rationale as the kiosk unit); keep Type=forking so systemd tracks the daemonized tmux server as main PID, and keep ExecStop as-is.

### [MAJOR] state/watch-map.json
PROBLEM: The docker-compose.yml reload rule (line 23) runs ["docker","compose","-f","/blazing/stack/docker-compose.yml","up","-d","--remove-orphans"] with no profile selection and no --env-file. Every service in docker-compose.yml is profile-gated (core/photos/recruiter), so a plain `up -d` selects zero services; and without `--env-file secrets/compose.env` the ${IMMICH_DB_PASSWORD}/${TWENTY_*}/${N8N_*} interpolations resolve to empty strings.
SCENARIO: An overhaul job that edits docker-compose.yml activates, overhaulctl runs this reload action, docker compose starts nothing (caddy/glance changes are never applied), and the probe phase then tests the old running stack — passing against stale state, exactly what §4.3 says probes must not do. If anyone adds a profile flag later without the env-file,
FIX: Change the rule's argv to ["docker","compose","-f","/blazing/stack/docker-compose.yml","--profile","core","--profile","photos","--env-file","/blazing/stack/secrets/compose.env","up","-d","--remove-orphans"] (and document the same invocation in jobs/README.md / secrets/README.md so manual and overhaul invocations match).


======================================================================
## LENS: security
VERDICT: Two findings break the deployment's stated security story on first contact: bootstrap.sh's secret generator kills the script under its own pipefail (verified: exit 141), and every .claude/settings.json deny rule uses single-slash patterns that Claude Code anchors at the project directory, so the entire advertised guardrail layer (bin/, secrets/, settings, .git) matches nothing. The watcherd/Caddy core is mostly sound — the CORS-preflight argument for mutating endpoints holds, ttyd's -O plus Caddy's host matcher genuinely blocks cross-origin WebSocket and DNS-rebinding paths to the terminal, /s

### [CRITICAL] setup/bootstrap.sh
PROBLEM: gen() (line 68: `tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1"`) always exits 141 under `set -euo pipefail`: head exits after N bytes, tr dies of SIGPIPE, pipefail surfaces 141, set -e aborts the script. Verified by running the exact function under `set -euo pipefail` — exit 141.
SCENARIO: First run: line 69 writes secrets/watcherd-token, then the script aborts. ttyd.env, caddy.env, compose.env, the chmod 600, user-unit install, sanoid, and the gitleaks hook never run. Re-runs abort again at line 72 (`pass=$(gen 32)`), so bootstrap can never complete — and compose fails to start (env_file secrets/caddy.env missing).
FIX: Give tr bounded input so it exits before head closes the pipe, e.g. `gen() { head -c 512 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }`, or simply `openssl rand -hex 24` / `openssl rand -hex 16` per secret. Add a smoke test: `bash -n` doesn't catch this; run bootstrap in a container once.

### [CRITICAL] .claude/settings.json
PROBLEM: Every deny rule (lines 5–19) uses a single-slash pattern like `Edit(/blazing/stack/bin/**)`. Per the Claude Code permissions docs, a `/path` pattern anchors at the settings source's project directory, not the filesystem root ("Use //Users/alice/file for absolute paths"). With the project at /blazing/stack, `Edit(/blazing/stack/bin/**)` resolves to /blazing/stack/blazing/stack/bin/** — a path that doesn't exist. All 14 deny rules, including Read(/blazing/stack/secrets/**), match nothing.
SCENARIO: Claude Code in /blazing/stack can Edit/Write bin/, systemd/, .mcp.json, .claude/settings.json, jobs/*/state.json, .git/ and Read/Edit secrets/ with zero friction. DESIGN.md §4.4 explicitly advertises these rules as the guardrail layer ("now explicitly covering …") — an external reviewer testing one rule will find the whole layer inert.
FIX: Rewrite each pattern either settings-relative (`Edit(/bin/**)`, `Read(/secrets/**)`, `Edit(/jobs/*/state.json)` …) or filesystem-absolute with a double slash (`Edit(//blazing/stack/bin/**)`). Then verify one rule live (ask Claude to touch bin/) before shipping.

### [MAJOR] bin/watcherd
PROBLEM: schedule() (lines 91–102) consumes only prefix/panel/extra_delay/sse_action from watch-map.json rules. The `reload` argv arrays in state/watch-map.json (e.g. `docker compose exec caddy caddy reload` for caddy/Caddyfile, `docker compose up -d` for docker-compose.yml) are never read or executed anywhere in watcherd. Additionally `sse_action: "none"` is still broadcast, and shell.js reloads the whole page for any `panel: "shell"` event regardless of action.
SCENARIO: Edit caddy/Caddyfile: watcherd fires panel=shell/action=none; Caddy is never reloaded, so the gateway keeps serving the old config while the kiosk page reloads, and CLAUDE.md's documented mutation channel ('watch-map reload rule runs caddy reload') silently does nothing. Same for docker-compose.yml edits — containers never re-upped.
FIX: In fire()/broadcast(), look up the matched rule, run its `reload` argv list via subprocess (with the same Popen pattern as run_event_actions), and skip the SSE broadcast when sse_action == "none". In shell.js handleEvent, ignore events whose action is "none".

### [MAJOR] caddy/Caddyfile
PROBLEM: The origin 127.0.0.1:8080 mixes the crown jewels with untrusted content: /claude* (lines 17–21) injects the ttyd Basic credential into every request, /token (lines 48–52) serves the watcherd bearer token, and /glance* (lines 55–57) proxies Glance same-origin — a third-party app whose configured widgets render live internet content (hacker-news, reddit, external RSS in glance/glance.yml). ttyd's -O origin check and the custom-header CORS argument both collapse for same-origin script.
SCENARIO: A single stored/reflected XSS in Glance's rendering of a feed item (or a malicious feed exploiting a template/widget bug) executes same-origin with the shell: it can fetch /token (full mutating access to watcherd) and open ws://127.0.0.1:8080/claude/ws — Origin matches Host, Caddy injects Authorization — giving keystroke injection into the Claude C
FIX: Move Glance off the gateway origin: iframe it directly from its own loopback port (http://127.0.0.1:8085) exactly as Immich already is (different localhost ports are different origins but same-site, so nothing else breaks), and drop the /glance* proxy. If the proxy must stay, at minimum serve /claude and /token from a second loopback site (e.g. 127.0.0.1:8090) that proxies nothing third-party.

### [MAJOR] bin/watcherd
PROBLEM: do_POST (lines 203–205) reads the full request body before any auth check, with `n = int(self.headers.get("Content-Length", 0) or 0)` unvalidated: a huge Content-Length is buffered entirely in RAM pre-auth, and a negative Content-Length makes rfile.read(n) read until connection close, hanging the handler thread indefinitely.
SCENARIO: Any website the operator visits can issue a cross-origin 'simple' POST to http://127.0.0.1:8080/signal (Caddy proxies it; no preflight needed because no custom header is required to *send*, only to be authorized) streaming a multi-GB body — watcherd buffers it before returning 403, exhausting memory. A local process can do the same directly on :848
FIX: Before reading: reject n < 0 or n > 65536 with 413 (`self._json({"error": "too large"}, 413)`), and perform the token check before reading the body for authed routes. Also set `timeout = 30` on the Handler class so half-open connections release their threads.

### [MAJOR] bin/simrun
PROBLEM: The 'server-side template enforcement' (lines 55–59, DESIGN.md §10: 'accepts only an enum of vetted template names … never a path [VERIFIED + panel security fix]') reads sim/registry.json and sim/templates/*.py from the leo-writable stack, and neither path is in the .claude/settings.json deny list or the CLAUDE.md never-edit list. The enforcement gate and the thing it gates are writable by the same actor.
SCENARIO: A Claude session (or any prompt-injected tool call) writes sim/templates/x.py plus a registry entry {"kind":"template","file":"x.py"} — two ordinary Edit calls that no rule flags — then `simrun run x` executes arbitrary code as a detached user unit pinned to GPU1. The design's claimed distinction between 'vetted templates' and 'freeform sim code' i
FIX: Add `Edit(/sim/registry.json)`, `Write(/sim/registry.json)`, `Edit(/sim/templates/**)`, `Write(/sim/templates/**)` to the (fixed) deny rules and list sim/ in CLAUDE.md's hard rules — or, to make it a real boundary, promote registry.json+templates to the root-owned /usr/local install set and have simrun read them from there.

### [MINOR] bin/watcherd
PROBLEM: POST /heartbeat (lines 206–209) is deliberately handled before _authed(), so it is CSRF-able: a cross-origin simple POST from any web page to http://127.0.0.1:8080/heartbeat succeeds (the opaque response doesn't matter, the side effect lands). shell.js already fetches the token at boot, so there is no reason for this endpoint to be open.
SCENARIO: A page open in any local browser keeps POSTing /heartbeat; /heartbeat/last then reports a fresh kiosk even when the kiosk is dead, so probe-kiosk-pingback 'verifies' a reload that never rendered and the §4.3 recovery path (kiosk restart) is suppressed — file recovery without screen recovery, exactly what the design says is not recovery.
FIX: Require X-Aletheon-Token on /heartbeat (move it below the _authed() check) and send the header from shell.js's heartbeat() using the already-fetched token.

### [MINOR] bin/watcherd
PROBLEM: The Handler never validates the Host header, and _authed() (line 163) compares the token with `!=` instead of a constant-time compare. Caddy's site matcher protects :8080 from DNS rebinding, but watcherd on 127.0.0.1:8484 answers any Host.
SCENARIO: A DNS-rebinding page served from evil.com:8484 flips its A record to 127.0.0.1 and becomes same-origin with watcherd: it reads /events (internal activity), /metrics/gpu, /session, and POSTs /heartbeat — no CORS or preflight obstacle at all, since to the browser it is same-origin.
FIX: In Handler, reject requests whose Host header is not in {"127.0.0.1:8484", "localhost:8484"} with 403 before routing, and use hmac.compare_digest(received, TOKEN) in _authed().

### [MINOR] bin/watcherd
PROBLEM: The SSE endpoint (lines 178–199) accepts unlimited subscribers on an unbounded ThreadingHTTPServer, and a client whose queue fills (queue.Full, lines 64–67) is removed from `clients` but its handler thread keeps writing keepalives to the open socket forever — the connection is never closed, so slow/stalled clients leak one thread + one socket each permanently.
SCENARIO: Any local process (or opaque no-cors fetches from a browser page) opens hundreds of /events connections and stalls reading: watcherd accumulates threads and sockets without bound; stalled clients removed as 'dead' still cost a thread for the daemon's lifetime, degrading the lingering unit that overhaul jobs depend on.
FIX: Cap concurrent SSE clients (e.g. reject with 503 above 32), and signal dead clients to disconnect: put a sentinel (None) in the dead queue and have the /events loop break and close when it dequeues the sentinel instead of sending keepalives forever.

### [MINOR] setup/bootstrap.sh
PROBLEM: caddy.env is only generated inside the `[[ ! -f "$SEC/ttyd.env" ]]` branch (lines 70–74), so its existence is keyed to a different file; and watcherd caches TOKEN once at import (bin/watcherd line 38), so a token provisioned after the daemon starts leaves mutating endpoints 503 until a manual restart.
SCENARIO: After any partial bootstrap (e.g. the gen() abort) or a deleted caddy.env, re-running bootstrap sees ttyd.env present and never recreates caddy.env — the caddy container fails on a missing env_file with no hint. Separately, enabling watcherd before the secrets step (or rotating the token) silently disables /signal and /reload until someone restarts
FIX: Generate each secret file under its own `[[ ! -f ]]` guard (derive TTYD_BASIC_B64 from ttyd.env when regenerating caddy.env). In watcherd, re-read the token per request (or on file mtime change) instead of once at import.


======================================================================
## LENS: conformance
VERDICT: Not deployable as written: four first-contact breakages. (1) `modectl apply` always refuses — state/screens.json's "_comment" key inflates the expected output count past what three monitors can ever satisfy — which also breaks fx reapply and the §4.3 revert routine's `modectl apply --previous`. (2) The outputs_up guard counts the substring "enabled", which "disabled" also contains, so the fx-away wallpaper-write guard passes exactly when it must fail. (3) setup/bootstrap.sh dies with SIGPIPE (verified, exit 141) at secret generation, so tokens, env files, user units, sanoid and the gitleaks ho

### [CRITICAL] aletheon/stack/bin/wallpaper_driver.py
PROBLEM: outputs_up() (line 116) does `r.stdout.count("enabled") >= expected` over `kscreen-doctor -o` text. The word "disabled" contains the substring "enabled", so every DISABLED output also increments the count. The guard the design added specifically for fx-away (§5: 'modectl deferring wallpaper writes while expected outputs are down') is inverted in exactly the case it exists for.
SCENARIO: `fx away` disables DP-1/DP-3. A later `fx low` calls wp.outputs_up(expected=3): output shows 1x 'enabled' + 2x 'disabled' = count 3 → passes → modectl is invoked while 2 of 3 containments are gone; the geometry-matched evaluateScript silently writes nothing for those screens, and modectl records success in state/mode.json for wallpapers that were n
FIX: Parse structurally: `kscreen-doctor -o --json` (or `-j`) and count outputs with `"enabled": true`; or at minimum count regex matches of r'(?<!dis)\benabled\b' per output line. Add a unit-less self-test with a captured sample containing a disabled output.

### [CRITICAL] aletheon/stack/bin/modectl
PROBLEM: apply() line 92 computes the expected output count as `len(json.load(open(.../screens.json)))`, but state/screens.json has FOUR top-level keys: dp3, dp1, dp2 and "_comment". Expected becomes 4 on a 3-monitor machine, and with all outputs up `kscreen-doctor -o` yields at most 3 'enabled' matches, so outputs_up() is always False.
SCENARIO: First `modectl apply <anything>` on the real machine dies with 'outputs are down (fx away?)' even with all three monitors enabled. This also breaks `fx` reapply, overhaulctl's activation step (`modectl apply`), and the §4.3 revert routine's `modectl apply --previous` — rollback can no longer restore the previous persona.
FIX: Count only screen entries: `expected = len([k for k in screens if not k.startswith("_")])`, or move screens under a `"screens": {...}` key in screens.json and update wallpaper_driver.screens() to match (then `len(wp.screens())`).

### [CRITICAL] aletheon/stack/setup/bootstrap.sh
PROBLEM: gen() at line 68 is `tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1"` under `set -euo pipefail`. head exits after N bytes, tr dies with SIGPIPE (141), pipefail makes the pipeline fail, set -e aborts the script. Verified by execution: the script exits 141 at the first `gen 48 > "$SEC/watcherd-token"`.
SCENARIO: Phase-0 bootstrap aborts at step 5 on every fresh run: no watcherd-token (watcherd mutating endpoints disabled, hook-signal dead), no ttyd.env/caddy.env (ttyd and caddy units fail to start), and steps 6-8 (user units, sanoid, git+gitleaks hook) never run — despite the header claiming 'SAFE TO RE-RUN'.
FIX: Make gen SIGPIPE-proof: `gen() { head -c 512 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c "$1"; }` (bounded read, tr never outlives head), or `openssl rand -hex 24`-style generation; alternatively append `|| true` inside the function and assert non-empty output.

### [CRITICAL] aletheon/stack/bin/watcherd
PROBLEM: schedule()/fire() (lines 91-109) read only prefix/panel/extra_delay/sse_action from watch-map rules. The rules' "reload" argv arrays are NEVER executed by watcherd (only overhaulctl's reload_actions_for uses them), and sse_action "none" is not suppressed — it is broadcast as action:"none", which shell.js (line 105) turns into a full `location.reload()` because the shell/state/shell-css branches ignore the action field. This contradicts CLAUDE.md ('watch-map reload rule runs caddy reload'), contracts/caddy.md ('wired in state/watch-map.json'), and the Caddyfile header itself.
SCENARIO: Claude edits caddy/Caddyfile through the documented mutation path: Caddy is never reloaded, so the gateway serves stale routes while the repo shows the new config — a silently inert core-demo path. Simultaneously the sse_action:"none" event reloads the entire Mission Control shell, the exact disruption "none" was added to prevent; same for every do
FIX: In fire(): execute `r["reload"]` argv lists via subprocess before broadcasting (log failures), and skip broadcast entirely when sse_action == "none" (still run reload actions). Carry the matched rule, not just (panel, action), through the pending timer. Defence in depth: make shell.js check `action === "reload"` before `location.reload()`.

### [MAJOR] aletheon/stack/state/watch-map.json
PROBLEM: The docker-compose reload action (line 23) runs `docker compose -f /blazing/stack/docker-compose.yml up -d --remove-orphans` with no `--env-file secrets/compose.env`. The compose file interpolates ${IMMICH_DB_PASSWORD}, ${TWENTY_DB_PASSWORD}, ${TWENTY_APP_SECRET}, ${N8N_ENCRYPTION_KEY}; secrets/compose.env is not auto-loaded (only `.env` in the project dir is). overhaulctl's reload_actions_for executes this same command.
SCENARIO: Any compose edit that triggers the reload recreates services with those variables empty: immich-server gets DB_PASSWORD="" and loses its database; worse, n8n recreated with an empty N8N_ENCRYPTION_KEY can no longer decrypt the stored Gmail OAuth refresh token (the one secret §1 says lives only in n8n's DB).
FIX: Change the rule to ["docker","compose","--env-file","/blazing/stack/secrets/compose.env","-f","/blazing/stack/docker-compose.yml","up","-d","--remove-orphans"], or add `env_file: secrets/compose.env` per service / a project-level `.env` symlink, and assert non-empty interpolation in the overhaul validate step (`docker compose config` with `--no-interpolate` diff or grep for ': ""').

### [MAJOR] aletheon/stack/shell/shell.js
PROBLEM: handleEvent() (lines 108-109) handles the sim panel by resetting `f.src = f.src.split("#")[0]`, but the sim iframe is mounted with src "about:blank" (state/layout.json) and nothing ever reads state/sim.json. simrun writes viewer_url into state/sim.json with the comment 'watched → SSE → sim panel points at viewer_url', but no code performs that pointing.
SCENARIO: Phase-9 gate 'prompt → sim → live viewport' fails: simrun launches the sim and rerun viewer, SSE fires panel=sim, and the sim viewport reloads about:blank forever. The rerun viewer is never displayed.
FIX: In handleEvent, special-case panel "sim": fetch("/state/sim.json"), and set the sim iframe's src to meta.viewer_url (guard: only 127.0.0.1 URLs). Keep the generic reload for other panels.

### [MAJOR] aletheon/stack/bin/overhaulctl
PROBLEM: check_preserve() (lines 114-119) fnmatches the manifest dst strings as written, and do_activate (line 174) resolves dst with os.path.join(STACK, dst). A dst of "./secrets/x", "state/../secrets/x", or "../outside" does not match preserve patterns like "secrets/*" but still lands in (or outside) the protected tree — os.path.join with an absolute dst even discards STACK entirely. DESIGN §4.5 promises 'the runner refuses specs that diff them'; the refusal is trivially bypassed by non-normalized paths.
SCENARIO: A spec (written by the Claude session the envelope is meant to bound) with manifest dst "glance/../secrets/watcherd-token" passes check_preserve and overwrites a preserved secret during activate; dst "../somewhere" writes outside /blazing/stack while the journal records a repo-relative path that rollback's git revert cannot undo.
FIX: In check_preserve/do_activate: `dst_abs = os.path.realpath(os.path.join(STACK, dst))`; die unless `dst_abs.startswith(STACK + os.sep)`; match preserve patterns against `os.path.relpath(dst_abs, STACK)`. Reject absolute dst outright.

### [MAJOR] aletheon/stack/bin/preflight.sh
PROBLEM: The CLI sweep (lines 18-22) omits `gitleaks` and the NUT tools (`upsmon`/`upsc`), both in §15's apt prerequisite list. gitleaks is a hard runtime dependency: bootstrap installs a pre-commit hook that is `exec gitleaks protect --staged --redact`, and overhaulctl's checkpoint/activate phases die when any commit fails.
SCENARIO: On a machine where the manual apt step was skipped or partial, preflight reports 'all green', then the very first `overhaulctl run` dies in checkpoint with 'checkpoint commit failed' (hook exec fails) — and every ordinary `git commit` in the repo fails the same way. The §3.5 UPS path similarly has no preflight assertion that NUT exists.
FIX: Add gitleaks, upsmon (or upsc) to the preflight `for c in ...` sweep; also assert the pre-commit hook is executable and `gitleaks version` runs. (nvcc is deliberately soft in §15 and can stay a note.)

### [MINOR] aletheon/stack/systemd/claude-tmux.service
PROBLEM: Type=forking with RemainAfterExit=yes: once the unit is active, systemd keeps it 'active (exited)' when the tmux server dies, so Restart=on-failure never fires. The unit's own comment ('the unit restarts it if the server dies') and DESIGN §6's 'Supervised: tmux runs as its own user unit (Restart=on-failure)' are both untrue as configured.
SCENARIO: tmux server crashes; claude-tmux.service stays active-exited, nothing respawns the session. The Claude panel shows ttyd re-creating a FRESH session via `tmux new -A` without `claude --continue` context recovery semantics the design expects from the unit, and overhaulctl's tmux probe retry path becomes the only (accidental) supervisor.
FIX: Drop RemainAfterExit=yes. Keep Type=forking so systemd tracks the tmux server PID, letting Restart=on-failure actually re-run ExecStart when the server dies.

### [MINOR] aletheon/stack/Makefile
PROBLEM: install-sudoers (lines 26-32) writes a NOPASSWD pin only for chrome-theme. DESIGN §15 explicitly requires 'sudoers pins: chrome-theme, powerguard-shed'. powerguard-shed is invoked via upssched/NOTIFYCMD, which runs as the unprivileged nut user — without a pin it cannot run nvidia-smi -pl, stop containers, or `systemctl poweroff`.
SCENARIO: On-battery event fires, upssched (as nut) runs powerguard-shed: every privileged action fails, GPUs stay at full draw on a CyberPower 1500 under dual-5090 load — the exact overload §3.5 exists to prevent. The phase-0 'shed test' gate would fail, but the install target claims completeness.
FIX: Add a second sudoers line (e.g. `nut ALL=(root) NOPASSWD: /usr/local/sbin/powerguard-shed` and/or the leo equivalent, matching how upssched is wired on this box) to install-sudoers, and document the upssched.conf CMDSCRIPT wiring the repo currently never installs.

