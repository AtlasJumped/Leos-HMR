# Review Brief #2 — Aletheon Mission Control, Design v3.1

> For the external AI review panel. 2026-10-11. Self-contained; the design itself is the
> attached `DESIGN.md` (read it in full before reviewing). Evidence base: `research/` —
> two research passes (66 agents: 11 researchers, ~50 adversarial fact-checkers, 2
> completeness critics; all claims tagged by confidence with primary sources) plus a 5-lens
> adversarial design review (40 findings: 8 critical / 27 major / 5 minor), all integrated
> into v3.1. Four earlier external critiques (yours among them) are already folded in.

## 1. What you are reviewing

A systems design for a single-user Linux workstation ("Aletheon": Ubuntu 26.04.1, KDE Plasma
6.6.6 Wayland via GDM, 2× RTX 5090 / sm_120 / driver 580.178, Threadripper 9970X, 128 GB ECC,
three 3440×1440@240 ultrawides, ZFS pools, Docker 29, Claude Code on the host as the operator).
The owner (Leo, a recruiter) wants: always-on video wallpapers; a one-command persona system
Claude can extend by generating brand-new personas; a Mission Control kiosk whose central panel
is a live Claude terminal that modifies the rest of the dash by editing files; prompt-driven GPU
physics sims with live visualization; a video studio; a recruiter cockpit; cameras/voice as
system senses; maximal visuals. Hard boundaries: no LinkedIn automation, no internal-hardware
purchases, no permission-bypass modes, secrets never in git.

## 2. Status taxonomy (use these words in your review)

- **Observed**: true of the machine today (hardware list, OS/session, installed tools).
- **Verified**: confirmed on primary sources Oct 2026 by the research passes (tagged in
  DESIGN.md; receipts in `research/*.md`). Do not re-litigate without contrary evidence.
- **Inferred**: reasoned but unconfirmed on this machine — DESIGN.md tags these [TEST].
- **Proposed**: design choices (architecture, schemas, build order) — your main target.
- **Decided**: the owner's explicit calls — challenge only with a concrete cost he hasn't seen.
- **Implemented**: NOTHING. No part of this design is deployed. The machine is unchanged.

## 3. The decisions most worth attacking (Proposed, load-bearing)

1. **Overhaul engine v1 is deliberately flat** (§4.2): checkpoint → validate → activate →
   probe → rollback as a ~200–300-line deterministic runner; spec entries are executable shell
   commands/file-pairs; journal-first activation with a mechanical crash-recovery rule; ONE
   revert routine ending in a kiosk restart + re-probe. Waves/DAG deferred. Is anything here
   still under- or over-built for the §4.6 acceptance drill?
2. **Honest permission envelope** (§4.4): deny rules admitted to be accident-guardrails (they
   don't bind Bash); the real boundary = root-owned installs under /usr/local + non-delegated
   zfs destroy/rollback + root syncoid replication; docker-group root-equivalence named as the
   ceiling. Is the residual risk acceptably stated, and is anything cheap still missing?
3. **watcherd core frozen; behavior in data files** (§5): SSE transport + heartbeat deny-listed;
   path→panel routing, event→TTS rules, future automations all in Claude-editable YAML. Does
   this actually keep "type a command, dash morphs" true at month 12?
4. **Claude panel through Caddy with injected auth** (§6), no direct unauthenticated ttyd, no
   persistent CDP port, supervised tmux/ttyd units, a single sanctioned iframe-remount
   exception. Any remaining local-attack or dead-panel path?
5. **Wallpaper driver interface + soak gate** (§7): SVWR primary, waywallen fallback must play
   the reference encode before the spec freezes; bulk generation blocked on the soak; per-mode
   fps field (30|60) + fx dial instead of a silent 24–30 default.
6. **Personas as git-tracked manifests** (§8): full 8-switch-point schema that generated and
   hand-written personas must both satisfy; binaries in a snapshotted dataset; LookAndFeel
   packages cut. Does persona rollback now genuinely ride the same revert routine?
7. **Build order** (§16): dependency-edged, Immich + OAuth clocks start at phase 0, the engine's
   full acceptance lives at phase 8, phase-1 gate is primitives-only. Find the row that is
   still secretly three weeks, or a dependency edge still pointing backwards.

## 4. Open items awaiting the owner (don't redesign around them)

- DP-2 wallpaper under the kiosk: static image + shell motion layer (default) vs literal
  always-video at ~+15W for occluded pixels. [DECISION-NEEDED]
- Offsite backup (Backblaze B2 ~$2/mo) — default yes. [DECISION-NEEDED]
- 30 vs 60 fps default — to be decided from measured watt delta after phase-2/14 measurement.
- SDDM switch for a themeable login screen — default yes, one-time, deliberate.

## 5. Known residual risks (named, not hidden)

§17 lists 11, headlined by: SVWR NVIDIA/Wayland stability (soak + named fallback), suspend-UVM
deadlock report, delegated zfs allow on this build, KWin kiosk rule, Resolve-on-26.04
frictions, docker-group ceiling. If you find a risk NOT on that list, that is a top-value
finding.

## 6. What a maximally useful review returns

Ranked findings, each with: the DESIGN.md section, severity (will-break / rework-later /
polish), a concrete failure scenario on THIS machine, and a specific fix. Rules: cite the
research digests before re-asserting ecosystem facts; respect Decided items unless you bring
new cost; distinguish your five status words; preserve disagreements with prior reviews rather
than silently overwriting them; no padding, no restated summaries of the doc. Review the same
named revision (v3.1) so findings are comparable; propose text edits where possible.

## 7. What happens next

Accepted findings become v3.2 edits plus entries in the decision log; the build then starts at
phase 0 with Claude Code executing against DESIGN.md §15–16, each phase exiting through its
gate. The first engineering artifact is the phase-1 primitives drill, not a dashboard.
