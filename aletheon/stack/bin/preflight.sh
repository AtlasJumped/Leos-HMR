#!/bin/bash
# preflight — DESIGN.md §15 assertions. Run before ANY build phase; exits non-zero on the
# first hard failure. Also records GPU topology to state/gpu.json for simrun/modectl.
set -uo pipefail
STACK="${ALETHEON_STACK:-/blazing/stack}"
fails=0
fail() { echo "PREFLIGHT FAIL: $*" >&2; fails=$((fails+1)); }
note() { echo "preflight: $*"; }

# session
[[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] || fail "not a Wayland session"

# display cabling: all three DP connectors must enumerate on ONE card (§14 build step zero)
cards=$(ls -l /dev/dri/by-path/ 2>/dev/null | grep -c 'card[0-9]*$' || true)
note "DRM by-path entries: $cards (verify visually: all 3 DP on GPU0; re-cable if not)"

# CLI sweep
for c in qdbus6 kwriteconfig6 kpackagetool6 plasma-apply-colorscheme \
         plasma-apply-cursortheme kwin-applywindowdecoration kscreen-doctor \
         ffmpeg inotifywait ttyd tmux jq git curl sanoid; do
  command -v "$c" >/dev/null || fail "missing CLI: $c"
done

# ffmpeg hardware surface
ffmpeg -hide_banner -encoders 2>/dev/null | grep -q nvenc || fail "ffmpeg lacks nvenc encoders"
ffmpeg -hide_banner -hwaccels 2>/dev/null | grep -q cuda  || fail "ffmpeg lacks cuda hwaccel"
ls /usr/lib/x86_64-linux-gnu/libnvcuvid.so* >/dev/null 2>&1 || fail "libnvcuvid missing (libnvidia-decode)"

# browser: Chrome .deb, not snap chromium (policy paths + kiosk flags differ)
command -v google-chrome >/dev/null || fail "google-chrome (.deb) not found"
snap list chromium >/dev/null 2>&1 && note "WARN: snap chromium present — do not use it for the kiosk"

# node
nodev=$(node --version 2>/dev/null | sed 's/v\([0-9]*\).*/\1/') || nodev=0
[[ "${nodev:-0}" -ge 22 ]] || fail "Node >=22 required (have ${nodev:-none}; Node 20 is EOL)"

# docker publish default + data-root
if [[ -f /etc/docker/daemon.json ]]; then
  grep -q '"ip"[[:space:]]*:[[:space:]]*"127.0.0.1"' /etc/docker/daemon.json \
    || fail 'daemon.json missing "ip": "127.0.0.1" (Docker publishes 0.0.0.0 by default)'
  grep -q '"data-root"[[:space:]]*:[[:space:]]*"/blazing/docker"' /etc/docker/daemon.json \
    || note "WARN: docker data-root not on /blazing/docker"
else
  fail "/etc/docker/daemon.json missing"
fi

# planned datasets: path absent/empty OR already a dataset (§3.1)
for ds in blazing/stack blazing/modes-assets blazing/hf blazing/docker blazing/generated; do
  path="/${ds/blazing/blazing}"; path="/${ds}"
  if zfs list "$ds" >/dev/null 2>&1; then continue; fi
  if [[ -d "$path" && -n "$(ls -A "$path" 2>/dev/null)" ]]; then
    fail "$path is a non-empty dir but not a dataset — run setup/bootstrap.sh migration"
  fi
done

# zfs delegation for checkpoints (§4.4)  [TEST]
zfs allow blazing/stack 2>/dev/null | grep -q snapshot \
  || note "WARN: no snapshot delegation on blazing/stack (make install adds it)"

# GPU topology → state/gpu.json (display GPU = the one driving DRM; compute = the other)
mkdir -p "$STACK/state"
nvidia-smi -L | python3 -c '
import json, re, sys
gpus = []
for line in sys.stdin:
    m = re.match(r"GPU (\d+): (.*) \(UUID: (GPU-[0-9a-f-]+)\)", line.strip())
    if m:
        gpus.append({"index": int(m.group(1)), "name": m.group(2), "uuid": m.group(3)})
out = {"gpus": gpus}
if len(gpus) >= 2:
    # Convention (§14): GPU0 drives displays, GPU1 is compute. Verify cabling matches!
    out["display_uuid"] = gpus[0]["uuid"]
    out["compute_uuid"] = gpus[1]["uuid"]
json.dump(out, open("'"$STACK"'/state/gpu.json", "w"), indent=2)
print("preflight: wrote state/gpu.json:", json.dumps(out))
' || fail "nvidia-smi -L parse failed"

# secrets
[[ -f "$STACK/secrets/watcherd-token" ]] || note "WARN: secrets/watcherd-token missing — run setup/bootstrap.sh"

if [[ $fails -gt 0 ]]; then
  echo "preflight: $fails FAILURES — fix before building" >&2
  exit 1
fi
echo "preflight: all green"
