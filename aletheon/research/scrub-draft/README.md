# scrub-draft — DRAFT, mock-tested only

Outline of the nightly "keep footage with Leo, expire the rest" job against Frigate 0.18's HTTP API
(see ../home-cameras-digest.md, topic `scrub-pipeline`). **Not deployed. Not verified against a live Frigate.**

- `frigate_scrub.py` — current design: person *event* intervals (not review items), tri-state policy,
  dry-run by default, non-destructive export mode as default.
- `frigate_scrub_v1_review_based.py` — superseded: review items skip seated/stationary people.
- `test_scrub.py` — run with `python3 test_scrub.py` (prints ALL TESTS PASSED); mock server only. `test_scrub_v1.py` covers the superseded version.

Before enabling ANY deletion: verify each endpoint with one curl on the live install, run dry-run for 7+
nights, confirm detector-outage and stationary-person handling, and keep the ZFS safety snapshot.
