#!/usr/bin/env bash
# shellcheck disable=SC2088  # "~/..." inside messages is display text, not a path
# claude-readiness-check — READ-ONLY audit of Leo's workstation after an update.
#
# Changes nothing: no sudo, no installs, and it writes no files itself. It only reads system
# state, plus two network checks: `gh auth status` (asks GitHub whether your login is valid) and
# an SSH probe to github.com that shows which account your key belongs to (with host-key updates
# off, so ~/.ssh/known_hosts is never touched). Prints PASS / WARN / FAIL lines, each problem
# with a suggested fix. Run it as your normal user from a desktop terminal (Konsole):
#
#   bash claude-readiness-check.sh | tee ~/claude-readiness-report.txt
#
# Then hand the report to Claude Code on this PC and fix the WARN/FAIL items one at a time.
# Skim the report before pasting it anywhere else: it shows the hostname, paths, listening
# ports and SSH key labels (no passwords, tokens or file contents).
set -uo pipefail

P=0; W=0; F=0
pass()    { printf '  PASS  %s\n' "$1"; P=$((P+1)); }
warn()    { printf '  WARN  %s\n' "$1"; [ -n "${2:-}" ] && printf '        fix: %s\n' "$2"; W=$((W+1)); }
fail()    { printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        fix: %s\n' "$2"; F=$((F+1)); }
info()    { printf '  info  %s\n' "$1"; }
have()    { command -v "$1" >/dev/null 2>&1; }
section() { printf '\n== %s ==\n' "$1"; }
now=$(date +%s)

printf 'claude-readiness-check  %s  host=%s  user=%s\n' "$(date '+%F %T')" "$(hostname)" "$(id -un)"

# ─────────────────────────────────────────────────────────────────────────────
section "System and updates"
. /etc/os-release 2>/dev/null && info "OS: ${PRETTY_NAME:-unknown}"

running=$(uname -r)
newest=$(ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's#^/boot/vmlinuz-##' | sort -V | tail -1)
if [ -z "$newest" ]; then
  warn "no kernels found in /boot (is the bpool boot pool mounted?)" "sudo zpool import bpool; then check: mount | grep /boot"
elif [ "$newest" != "$running" ]; then
  warn "running kernel $running, newest installed $newest" "reboot when no GPU job is running"
else
  pass "running the newest installed kernel ($running)"
fi

if [ -e /var/run/reboot-required ]; then
  pkgs=$(head -5 /var/run/reboot-required.pkgs 2>/dev/null | tr '\n' ' ')
  warn "a reboot is pending (${pkgs:-packages updated})" "reboot, then re-run this check"
fi

lists_age=$(stat -c %Y /var/lib/apt/periodic/update-success-stamp 2>/dev/null || stat -c %Y /var/cache/apt/pkgcache.bin 2>/dev/null || true)
if [ -z "$lists_age" ] || [ $(( now - lists_age )) -gt 86400 ]; then
  warn "package lists are more than a day old, so the upgrade count below may be stale" "sudo apt update"
fi
upg=$(apt list --upgradable 2>/dev/null | tail -n +2)
n_upg=$(printf '%s' "$upg" | grep -c . || true)
if [ "$n_upg" -gt 0 ]; then
  risky=$(printf '%s\n' "$upg" | cut -d/ -f1 | grep -Ei 'plasma|kwin|nvidia|linux-image|zfs' | head -8 | tr '\n' ' ')
  warn "$n_upg packages can still be upgraded${risky:+ (review first: $risky)}" "sudo apt upgrade (check Plasma/NVIDIA/kernel lines first)"
else
  pass "no pending package upgrades"
fi

held=$(apt-mark showhold 2>/dev/null | tr '\n' ' ')
info "held packages: ${held:-none}"

if [ -n "$(dpkg --audit 2>/dev/null)" ]; then
  fail "dpkg reports half-installed or unconfigured packages" "sudo dpkg --configure -a && sudo apt -f install"
else
  pass "no broken or half-configured packages"
fi

repos=$(apt-cache policy 2>/dev/null | grep -oE 'https?://[^ ]+' | sort -u)
printf '%s\n' "$repos" | grep -q 'dl.google.com' \
  && pass "Google Chrome apt repo is active" \
  || warn "Google Chrome apt repo is not active (release upgrades disable third-party repos)" \
          "re-enable it from ~/Documents/pre-2604-apt-sources/ or reinstall the Chrome .deb"
printf '%s\n' "$repos" | grep -q 'nodesource' \
  && pass "NodeSource apt repo is active" \
  || info "NodeSource apt repo not active (only matters if Node comes from it)"

case "${XDG_SESSION_TYPE:-}" in
  wayland) pass "desktop session is Wayland" ;;
  x11)     warn "desktop session is X11 — the dashboard design assumes Wayland" "log out and pick 'Plasma (Wayland)' at the login screen" ;;
  *)       info "session type unknown (run this from a desktop terminal to check)" ;;
esac

if have plasmashell; then
  pv=$(plasmashell --version 2>/dev/null | awk '{print $2}')
  case "$pv" in
    6.7.0|6.7.1) fail "Plasma $pv crashes the session when Chrome toggles fullscreen (KDE bug 521722)" "wait for 6.7.3+, or roll back from the pre-upgrade snapshot" ;;
    6.6.*)       pass "Plasma $pv (fine; stay below 6.7 until 6.7.3+ ships)" ;;
    "")          info "could not read the Plasma version" ;;
    *)           info "Plasma $pv" ;;
  esac
fi

use=$(df -P / | awk 'NR==2{gsub("%","",$5); print $5}')
[ "${use:-0}" -ge 85 ] && warn "root filesystem is ${use}% full" "clear caches or move data to the NVMe/HDD pools" \
                       || pass "root filesystem ${use}% used"

# ─────────────────────────────────────────────────────────────────────────────
section "GPUs"
if have nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
  n_gpu=$(nvidia-smi -L | grep -c '^GPU')
  [ "$n_gpu" -eq 2 ] && pass "both GPUs visible" \
                     || fail "nvidia-smi sees $n_gpu GPU(s), expected 2" "reboot; if still missing, check driver/DKMS for the running kernel"
  info "driver $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
  grep -q 'Open Kernel' /proc/driver/nvidia/version 2>/dev/null \
    && pass "NVIDIA open kernel module loaded (required for RTX 50-series)" \
    || warn "NVIDIA open kernel module not detected" "reinstall the -open driver package"
else
  fail "nvidia-smi cannot talk to the driver" "reboot; if it persists, the driver did not build for kernel $running"
fi

# ─────────────────────────────────────────────────────────────────────────────
section "ZFS"
if have zpool; then
  health=$(zpool status -x 2>&1)
  [ "$health" = "all pools are healthy" ] && pass "all pools healthy" \
                                           || fail "pool problem: $(printf '%s' "$health" | head -3 | tr '\n' ' ')" "zpool status -v"
  for p in rpool bpool blazing scratch tank; do
    zpool list -H -o name "$p" >/dev/null 2>&1 || warn "pool '$p' is not imported" "sudo zpool import $p"
  done
  while read -r name cap; do
    c=${cap%\%}
    [ "${c:-0}" -ge 80 ] && warn "pool $name is ${cap} full" "free space before it passes 90% (ZFS slows sharply)"
  done < <(zpool list -H -o name,cap 2>/dev/null)
  for p in $(zpool list -H -o name 2>/dev/null); do
    line=$(zpool status "$p" 2>/dev/null | grep -E 'scan:' | head -1)
    when=$(printf '%s' "$line" | sed -n 's/.*scrub repaired.* on //p')
    if [ -n "$when" ] && ts=$(date -d "$when" +%s 2>/dev/null); then
      age=$(( (now - ts) / 86400 ))
      [ "$age" -gt 35 ] && warn "pool $p last scrubbed $age days ago" "sudo zpool scrub $p" \
                        || pass "pool $p scrubbed $age days ago"
    else
      case "$line" in
        *"scrub in progress"*)    info "pool $p: scrub in progress" ;;
        *"resilver in progress"*) warn "pool $p is resilvering (rebuilding a disk)" "let it finish; zpool status $p shows progress" ;;
        *"scrub paused"*)         warn "pool $p has a paused scrub" "sudo zpool scrub $p (resumes it)" ;;
        *resilvered*)             info "pool $p: last scan was a resilver; no scrub since" ;;
        *)                        warn "pool $p has no completed scrub on record" "sudo zpool scrub $p" ;;
      esac
    fi
  done
  if have sanoid && systemctl is-active --quiet sanoid.timer 2>/dev/null; then
    pass "sanoid automatic snapshots are running"
  else
    warn "no automatic snapshot schedule (sanoid not installed or not running)" \
         "sudo apt install sanoid, then configure /etc/sanoid/sanoid.conf (DESIGN.md §3.1)"
  fi
  last=$(zfs list -H -t snapshot -o name,creation -s creation -r rpool 2>/dev/null | tail -1)
  info "newest rpool snapshot: ${last:-none}"
  systemctl is-active --quiet zfs-zed 2>/dev/null && pass "ZFS event daemon (zed) running" \
                                                  || warn "zfs-zed is not running" "sudo systemctl enable --now zfs-zed"
  if [ -d "/blazing/iCloud Download October 2026" ] && ! zfs list tank/photos >/dev/null 2>&1; then
    warn "the iCloud photo library only lives on blazing (one NVMe, no mirror)" \
         "copy it to a new tank/photos dataset on the mirrored HDDs (DESIGN.md §3.2)"
  fi
else
  fail "ZFS tools not found" "sudo apt install zfsutils-linux"
fi

# ─────────────────────────────────────────────────────────────────────────────
section "Docker"
if have docker; then
  systemctl is-active --quiet docker 2>/dev/null && pass "Docker is running" \
                                                 || fail "Docker is not running" "sudo systemctl start docker"
  docker compose version >/dev/null 2>&1 && pass "docker compose v2 available" \
                                         || warn "docker compose v2 missing" "sudo apt install docker-compose-v2"
  id -nG | grep -qw docker && info "you are in the docker group (equivalent to root access)"
  if [ -f /etc/docker/daemon.json ] && grep -qE '"ip"[[:space:]]*:[[:space:]]*"127\.0\.0\.1"' /etc/docker/daemon.json; then
    pass "Docker publishes container ports on localhost only"
  else
    warn "Docker will publish container ports to your whole network by default" \
         'add "ip": "127.0.0.1" to /etc/docker/daemon.json, then sudo systemctl restart docker'
  fi
  have nvidia-ctk && pass "NVIDIA container toolkit installed" \
                  || warn "NVIDIA container toolkit missing (GPU containers like Immich/Frigate need it)" \
                          "install nvidia-container-toolkit, then sudo nvidia-ctk runtime configure --runtime=docker"
else
  warn "Docker not installed" "sudo apt install docker.io docker-compose-v2"
fi

# ─────────────────────────────────────────────────────────────────────────────
section "Network exposure"
if have ss; then
  open=$(ss -H -tln 2>/dev/null | awk '{print $4}' | grep -vE '^(127\.|\[::1\]|::1|\[::ffff:127\.)' | sort -u | tr '\n' ' ')
  if [ -n "$open" ]; then
    warn "TCP ports reachable from your network: $open" "close or bind to 127.0.0.1 anything you don't need on the LAN (sshd is the usual exception)"
  else
    pass "no TCP port listens beyond localhost"
  fi
else
  info "ss not available; listening ports not checked"
fi

# ─────────────────────────────────────────────────────────────────────────────
section "Claude Code"
if have claude; then
  cpath=$(command -v claude)
  info "claude $(claude --version 2>/dev/null | head -1) at $cpath"
  npm_copy=no
  if have npm && [ -d "$(dirname "$(dirname "$(command -v npm)")")/lib/node_modules/@anthropic-ai/claude-code" ]; then
    npm_copy=yes
  fi
  for c in $(which -a claude 2>/dev/null); do
    case "$(readlink -f "$c")" in *node_modules/@anthropic-ai/claude-code*) npm_copy=yes ;; esac
  done
  if [ "$cpath" = "$HOME/.local/bin/claude" ]; then
    pass "Claude Code is the native install"
    [ "$npm_copy" = yes ] && warn "an old npm copy of Claude Code is also installed" "npm uninstall -g @anthropic-ai/claude-code"
  elif [ "$npm_copy" = yes ]; then
    warn "the claude on your PATH is the old npm install, not the native installer" \
         "install the native build (claude.com/claude-code), then npm uninstall -g @anthropic-ai/claude-code"
  else
    info "claude is not at ~/.local/bin/claude (native default); check this is the install you expect"
  fi
  n_claude=$(which -a claude 2>/dev/null | sort -u | wc -l)
  [ "$n_claude" -gt 1 ] && warn "$n_claude different claude executables on PATH: $(which -a claude | sort -u | tr '\n' ' ')" \
                            "keep ~/.local/bin/claude; remove the others"
  [ -d "$HOME/.claude/local" ] && warn "a legacy local install exists in ~/.claude/local" "rm -rf ~/.claude/local"
  if env | grep -qE '^(ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN)='; then
    warn "ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN is set in your shell — Claude Code bills that key instead of your subscription, and Remote Control refuses to start" \
         "remove it from ~/.bashrc / ~/.profile unless you meant to use an API key"
  fi
  info "also run 'claude doctor' yourself: it checks the install and settings and explains any warning"
else
  fail "claude not found on PATH" "reinstall with the native installer from claude.com/claude-code"
fi

C=~/.claude
if [ -f "$C/settings.json" ]; then
  if have jq; then
    jq -e . "$C/settings.json" >/dev/null 2>&1 \
      && pass "~/.claude/settings.json is valid JSON (keys: $(jq -r 'keys|join(", ")' "$C/settings.json"))" \
      || fail "~/.claude/settings.json is not valid JSON — Claude Code ignores it" "fix the syntax error (jq . ~/.claude/settings.json shows where)"
    info "default permission mode: $(jq -r '.permissions.defaultMode // "not set (auto is the built-in default)"' "$C/settings.json" 2>/dev/null)"
    if jq -e '.autoMode' "$C/settings.json" >/dev/null 2>&1; then
      for k in environment allow soft_deny hard_deny; do
        if jq -e --arg k "$k" '.autoMode[$k] | type == "array"' "$C/settings.json" >/dev/null 2>&1 \
           && ! jq -e --arg k "$k" '.autoMode[$k] | index("$defaults")' "$C/settings.json" >/dev/null 2>&1; then
          warn "autoMode.$k has no \"\$defaults\" entry, so Claude Code's built-in $k rules are switched off" \
               "add \"\$defaults\" as the first item of autoMode.$k"
        fi
      done
      pass "auto mode has custom rules (check them with: claude auto-mode config)"
    else
      info "no custom auto-mode rules yet (aletheon/tools/apply-claude-settings.sh adds the recommended ones)"
    fi
    jq -e '.env.ANTHROPIC_API_KEY // .apiKeyHelper' "$C/settings.json" >/dev/null 2>&1 \
      && warn "settings.json sets an API key or apiKeyHelper — Remote Control needs a claude.ai login instead" "remove it unless intended"
  else
    info "~/.claude/settings.json exists (install jq to validate it)"
  fi
else
  info "no ~/.claude/settings.json (defaults in use)"
fi

if [ -f "$C/.credentials.json" ]; then
  perm=$(stat -c %a "$C/.credentials.json")
  [ "$perm" = "600" ] && pass "Claude login file is private (600)" \
                      || warn "Claude login file has permissions $perm" "chmod 600 ~/.claude/.credentials.json"
fi

if [ -f "$C/CLAUDE.md" ]; then
  lines=$(wc -l < "$C/CLAUDE.md")
  [ "$lines" -gt 200 ] && warn "~/.claude/CLAUDE.md is $lines lines (guidance: under about 200; it loads into every session)" \
                              "move reference material into ~/Documents/TECH_STACK.md and import it" \
                       || info "~/.claude/CLAUDE.md: $lines lines"
  grep -qE '@~?/?.*TECH_STACK\.md' "$C/CLAUDE.md" \
    && pass "CLAUDE.md imports TECH_STACK.md" \
    || info "CLAUDE.md does not import TECH_STACK.md (add a line: @~/Documents/TECH_STACK.md)"
  grep -qiF "$(hostname)" "$C/CLAUDE.md" \
    && pass "CLAUDE.md names this machine ($(hostname))" \
    || warn "CLAUDE.md never mentions this machine's hostname ($(hostname)) — it may describe it under an old name" \
            "correct the machine name in ~/.claude/CLAUDE.md"
else
  warn "no ~/.claude/CLAUDE.md, so Claude starts every session without knowing this machine" \
       "create one that points to ~/Documents/TECH_STACK.md"
fi

TS=~/Documents/TECH_STACK.md
if [ -f "$TS" ]; then
  stale=$(grep -oE 'Plasma 5\.27|on X11|Must use nightly|nightly cu128|Node\.js \| 20' "$TS" | sort -u | tr '\n' ';')
  [ -n "$stale" ] && warn "TECH_STACK.md still has outdated facts Claude will trust: $stale" \
                          "ask Claude on this PC to refresh TECH_STACK.md using this report" \
                  || pass "TECH_STACK.md has no known-stale lines"
fi

if [ -d ~/.git ]; then
  tracked=$(git -C ~ ls-files 2>/dev/null | wc -l)
  remotes=$(git -C ~ remote 2>/dev/null | wc -l)
  warn "your home folder is a git repository ($tracked tracked files, $remotes remotes) — every folder under it counts as 'inside a repo'" \
       "if it tracks nothing: mv ~/.git ~/.git.unused-$(date +%F)"
fi

if have node; then
  nv=$(node --version | sed 's/^v//; s/\..*//')
  [ "${nv:-0}" -ge 22 ] && pass "Node $(node --version)" \
                        || warn "Node $(node --version) is past end-of-life" "install Node 22 or 24 LTS"
fi

if have gh; then
  GH_NO_UPDATE_NOTIFIER=1 gh auth status >/dev/null 2>&1 && pass "GitHub CLI logged in" \
                                 || warn "GitHub CLI is not logged in (or its token expired)" "gh auth login"
else
  info "GitHub CLI (gh) not installed"
fi
[ -n "$(git config --global user.name)" ] && [ -n "$(git config --global user.email)" ] \
  && pass "git name and email configured" \
  || warn "git name/email not set" 'git config --global user.name "…"; git config --global user.email "…"'

keys=$(ssh-add -l 2>/dev/null | awk '{$1=$2=""; print}' | sed 's/^  //' | tr '\n' ';')
info "SSH keys loaded in the agent: ${keys:-none}"
gh_ssh=$(timeout 15 ssh -o BatchMode=yes -o ConnectTimeout=5 -o UpdateHostKeys=no -o StrictHostKeyChecking=yes -T git@github.com 2>&1 | grep -oE 'Hi [^!]+' | head -1)
info "GitHub over SSH: ${gh_ssh:-no key accepted (fine if you use HTTPS + gh)}"

have bwrap && info "bubblewrap present (Claude Code's sandbox can use it)" \
           || info "bubblewrap not installed (needed only for Claude Code's sandbox mode)"

# ─────────────────────────────────────────────────────────────────────────────
section "Power"
if have upsc; then
  ups=$(upsc -l 2>/dev/null | head -1)
  if [ -n "$ups" ]; then
    info "UPS '$ups': status $(upsc "$ups" ups.status 2>/dev/null), battery $(upsc "$ups" battery.charge 2>/dev/null)%, load $(upsc "$ups" ups.load 2>/dev/null)%"
  else
    warn "NUT is installed but no UPS is configured" "configure /etc/nut for the CyberPower (DESIGN.md §3.5)"
  fi
else
  info "NUT not installed — no automatic clean shutdown on a long outage (DESIGN.md §3.5)"
fi

# ─────────────────────────────────────────────────────────────────────────────
printf '\nSummary: %d pass, %d warn, %d fail\n' "$P" "$W" "$F"
