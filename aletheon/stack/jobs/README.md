# jobs/ — overhaul jobs (DESIGN.md §4)

One directory per job: `spec.json` (what), `state.json` (runner-owned journal — never edit),
`plan.md` (why + acceptance), `artifacts/` (staged files), `log/`.

Flow: `overhaulctl new <id>` → edit spec, stage files under `artifacts/` →
`overhaulctl run <id>` (checkpoint → validate → activate → probe; auto-revert on probe
failure) → after a crash: `overhaulctl resume <id>` → manual undo: `overhaulctl rollback <id>`.

**Phase-1 primitives drill** (the gate, §16): on dummy content —
1. `overhaulctl new drill-001`; stage a good file + a file that fails `jq -e .`.
   Phase 1 predates Caddy/the kiosk: TRIM the copied spec's validate list to the `jq`
   entry and the probe list to `["true"]` — the drill tests the engine primitives, not the
   panels (the full probe set is exercised by the phase-8 drill).
2. `run` → validate refuses; fix; `run` → activates; confirm live file
3. `rollback drill-001` → live file restored byte-identical
4. start a run, `kill -9` the runner mid-activate → `resume` → ends clean
