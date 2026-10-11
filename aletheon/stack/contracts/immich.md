# contract: immich

- **start/stop**: `docker compose --profile photos up -d` / `stop`; health: `curl -sf http://127.0.0.1:2283/api/server/ping`
- **owns**: photo index/faces/CLIP DB (`/blazing/generated/immich-pg`), thumbnails/ML cache. The LIBRARY (`/tank/photos`) is read-only and NOT owned.
- **interfaces**: REST (`x-api-key`): `POST /api/search/random` (dash tile), `GET /api/assets/{id}/thumbnail`, `POST /api/download/archive` (mode exports).
- **reload mechanism**: `docker compose restart immich-server` (bind-mounted config edits do NOT recreate containers).
- **INVARIANTS (preserve-protected — overhaulctl refuses specs diffing them)**:
  1. First library scan happens only AFTER photos sit at their final host path (`/tank/photos`). Immich keys external assets by path; moving the library after indexing orphans faces/albums/days of ML work.
  2. The in-container path `/mnt/photos` is **frozen forever**. Host moves = compose edit only.
- **export/restore**: nightly `pg_dump` → `/tank/backup/immich/`; restore = fresh stack + pg restore + rescan.
- **test**: upload-free — `search/random` returns an asset after indexing.
