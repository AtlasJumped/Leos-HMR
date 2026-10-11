#!/bin/bash
# bootstrap — phase-0 host setup (DESIGN.md §3/§15). SAFE TO RE-RUN. Needs sudo for the
# dataset/daemon.json/environment steps; refuses destructive paths and migrates non-empty
# directories instead of shadowing them (§3.1).
set -euo pipefail
STACK="${ALETHEON_STACK:-/blazing/stack}"
USER_NAME="${SUDO_USER:-$USER}"

say() { echo "bootstrap: $*"; }

# ── 1. datasets (one zfs create per dataset; migrate non-empty dirs) ──────────
make_dataset() {
  local ds="$1" mnt="/$1"
  if zfs list "$ds" >/dev/null 2>&1; then say "dataset $ds exists"; return; fi
  if [[ -d "$mnt" && -n "$(ls -A "$mnt" 2>/dev/null)" ]]; then
    say "migrating non-empty $mnt into new dataset $ds"
    if [[ "$ds" == "blazing/docker" ]]; then
      say "stopping docker for data-root migration"; systemctl stop docker docker.socket
    fi
    local stage="/blazing/.migrate-$(basename "$ds")"
    zfs create -o mountpoint="$stage" "$ds"
    rsync -aHAX "$mnt/" "$stage/"
    mv "$mnt" "${mnt}.pre-dataset"
    zfs set mountpoint="$mnt" "$ds"
    say "old copy kept at ${mnt}.pre-dataset — remove after verifying"
    [[ "$ds" == "blazing/docker" ]] && systemctl start docker
  else
    zfs create "$ds"
  fi
  chown "$USER_NAME": "$mnt"
}
for ds in blazing/stack blazing/modes-assets blazing/hf blazing/docker blazing/generated; do
  make_dataset "$ds"
done
zfs list tank/photos >/dev/null 2>&1 || { zfs create tank/photos; chown "$USER_NAME": /tank/photos; }
zfs list tank/backup >/dev/null 2>&1 || zfs create tank/backup

# ── 2. docker daemon: loopback publishes + data-root (merge, don't clobber) ───
python3 - <<'EOF'
import json, os
p = "/etc/docker/daemon.json"
cfg = {}
if os.path.exists(p):
    cfg = json.load(open(p))
cfg["ip"] = "127.0.0.1"
cfg["data-root"] = "/blazing/docker"
json.dump(cfg, open(p, "w"), indent=2)
print("bootstrap: daemon.json merged:", cfg)
EOF
systemctl restart docker

# ── 3. session env: NVDEC for plasmashell AND kscreenlocker_greet (§7) ────────
ENVD="/home/$USER_NAME/.config/environment.d"
install -d -o "$USER_NAME" "$ENVD"
cat > "$ENVD/50-aletheon.conf" <<EOF
QT_FFMPEG_DECODING_HW_DEVICE_TYPES=cuda
ALETHEON_STACK=$STACK
EOF
chown "$USER_NAME": "$ENVD/50-aletheon.conf"
say "environment.d written — takes effect at next login"

# ── 4. lingering user manager (watcherd + jobs survive logout, §5) ────────────
loginctl enable-linger "$USER_NAME"

# ── 5. secrets (never in git) ─────────────────────────────────────────────────
SEC="$STACK/secrets"
install -d -m 700 -o "$USER_NAME" "$SEC"
# SIGPIPE-proof generator: bounded read, NO downstream pipe-closer (a trailing `head -c`
# would kill tr with SIGPIPE under pipefail — review-verified failure, exit 141).
gen() { local s; s=$(head -c 512 /dev/urandom | base64 -w0 | tr -dc 'A-Za-z0-9'); printf '%s' "${s:0:$1}"; }
# each file under its OWN guard so partial runs self-heal
if [[ ! -f "$SEC/watcherd-token" ]]; then gen 48 > "$SEC/watcherd-token"; fi
if [[ ! -f "$SEC/ttyd.env" ]]; then
  printf 'TTYD_CREDENTIAL=leo:%s\n' "$(gen 32)" > "$SEC/ttyd.env"
fi
if [[ ! -f "$SEC/caddy.env" ]]; then
  cred=$(grep -oP '(?<=TTYD_CREDENTIAL=).*' "$SEC/ttyd.env")
  printf 'TTYD_BASIC_B64=%s\n' "$(printf '%s' "$cred" | base64 -w0)" > "$SEC/caddy.env"
fi
if [[ ! -f "$SEC/compose.env" ]]; then
  printf 'IMMICH_DB_PASSWORD=%s\nTWENTY_DB_PASSWORD=%s\nTWENTY_APP_SECRET=%s\nN8N_ENCRYPTION_KEY=%s\n' \
    "$(gen 24)" "$(gen 24)" "$(gen 32)" "$(gen 32)" > "$SEC/compose.env"
  say "compose secrets generated → ALWAYS invoke compose with: --env-file secrets/compose.env"
fi
chmod 600 "$SEC"/* ; chown "$USER_NAME": "$SEC"/*

# ── 6. user units ─────────────────────────────────────────────────────────────
UNITS="/home/$USER_NAME/.config/systemd/user"
install -d -o "$USER_NAME" "$UNITS"
for u in "$STACK"/systemd/*.service "$STACK"/systemd/*.timer; do
  install -m 644 -o "$USER_NAME" "$u" "$UNITS/"
done
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$(id -u "$USER_NAME")" \
  systemctl --user daemon-reload
say "user units installed — enable with:"
say "  systemctl --user enable --now watcherd claude-tmux ttyd powerguard-session kiosk-recycle.timer"
say "  systemctl --user enable missioncontrol-kiosk   # after the KWin rule exists"

# ── 7. sanoid snapshots ───────────────────────────────────────────────────────
install -d /etc/sanoid
if ! grep -q aletheon /etc/sanoid/sanoid.conf 2>/dev/null; then
  cat >> /etc/sanoid/sanoid.conf <<'EOF'
# aletheon (DESIGN.md §3.1)
[blazing/stack]
  use_template = production
[blazing/modes-assets]
  use_template = production
[tank/photos]
  use_template = backup
[template_production]
  hourly = 48
  daily = 30
  autosnap = yes
  autoprune = yes
[template_backup]
  daily = 60
  autosnap = yes
  autoprune = yes
EOF
fi
systemctl enable --now sanoid.timer || say "WARN: sanoid.timer not available — check package"

# ── 8. git repo + gitleaks hook ───────────────────────────────────────────────
if [[ ! -d "$STACK/.git" ]]; then
  sudo -u "$USER_NAME" git -C "$STACK" init -b main
fi
HOOK="$STACK/.git/hooks/pre-commit"
cat > "$HOOK" <<'EOF'
#!/bin/sh
exec gitleaks protect --staged --redact
EOF
chmod +x "$HOOK"; chown "$USER_NAME": "$HOOK"

say "done. Next: bin/preflight.sh, then sudo make install, then phase 1 (jobs/README.md)."
