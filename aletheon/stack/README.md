# Aletheon Mission Control — stack

Implementation of `../DESIGN.md` v3.1. This directory IS `/blazing/stack` on the workstation:
copy it there (or clone the repo and symlink), then build phase by phase — every phase exits
through a testable gate (DESIGN.md §16).

## Install order (maps to DESIGN.md phases)

```bash
# Phase 0 — host setup (root): datasets w/ migration guards, docker daemon.json, secrets,
# environment.d, linger, sanoid, user units, git hook
sudo setup/bootstrap.sh
bin/preflight.sh                      # must print "all green"
sudo make install                     # root-promotes overhaulctl/powerguard-shed/chrome-theme,
                                      # sudoers pin, zfs delegation, syncoid replication
# move photos: rsync -aHAX --info=progress2 "/blazing/iCloud Download October 2026/" /tank/photos/
docker compose --env-file secrets/compose.env --profile core --profile photos up -d
# (Immich indexing starts now and runs for days — that's the point of phase-0 placement)

# Phase 1 — primitives drill (jobs/README.md) — the overhaul engine gate

# Phase 2 — wallpaper soak: install Smart Video Wallpaper Reborn (KDE Store 2139746),
# generate 3 test loops:
#   ffmpeg -f lavfi -i testsrc2=size=3440x1440:rate=30 -t 20 -c:v hevc_nvenc \
#          -profile:v main10 -g 600 /blazing/modes-assets/default/videos/dp1-30.mp4
# then: bin/modectl validate default && bin/modectl apply default
# soak checklist: lock/unlock, screen off, systemctl suspend, output-cycling x50,
# nvidia-smi dmon -s u → dec% > 0 on GPU0

# Phase 3a/3b — panel + loop:
systemctl --user enable --now watcherd claude-tmux ttyd powerguard-session
docker compose --env-file secrets/compose.env --profile core up -d   # caddy + glance
# open http://127.0.0.1:8080 — type in the Claude panel; edit glance/glance.yml → panel reloads

# Phase 3c — kiosk: create the KWin rule (match class "missioncontrol", force Screen=DP-2 +
# Fullscreen), then: systemctl --user enable --now missioncontrol-kiosk kiosk-recycle.timer
```

Later phases (modes/persona-create, generation pipeline, sim lab, studio, recruiter) follow
DESIGN.md §16 rows 4–12; the compose `photos`/`recruiter` profiles and `sim/registry.json`
are their landing zones.

## Layout
`bin/` runners + helpers (deny-listed for in-repo edits; root copies are the enforced ones) ·
`caddy/` gateway · `shell/` the master page · `glance/` dashboard config · `state/`
Claude-editable routing/layout/mode/fx data · `modes/` persona manifests (text; binaries in
`/blazing/modes-assets`) · `jobs/` overhaul jobs · `sim/` vetted templates ·
`contracts/` per-component operating contracts · `systemd/` user units ·
`setup/bootstrap.sh` + `Makefile` host provisioning.

## [TEST] markers
Grep `\[TEST\]` across the tree before trusting a mechanism on the machine — those are the
verified-on-paper-not-on-metal seams (DESIGN.md §17), led by: SVWR soak, zfs delegation,
KWin kiosk rule, Newton template API, Twenty MCP endpoint shape.
