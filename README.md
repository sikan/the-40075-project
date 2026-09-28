# the-40075-project

A data-first Concept2 logbook and static website for a 40,075 km lifetime rowing goal, approximately the length of Earth's equator.

The repository name is **the-40075-project**. The website's short display name remains **row**, with `row.islandinamber.com` planned for later. GitHub Pages is the first hosting target.

**Current state:** the first live import is complete. Its 1,555 workouts and 15,925,131 meters match the Concept2 logbook exactly, as does the displayed lifetime duration. The generated site uses real data. Calories remain unreconciled; see `DATA_STATUS.md`.

Requires Python 3.9 or newer. Runtime and build code use only the Python and browser standard libraries.

Concept2 access is strictly read-only: the client sends GET requests only. Never create, edit, or delete Concept2 records or change logbook settings. The user handles code and documentation commits and pushes. The GitHub Actions bot is limited to committing successful data changes under `data/archive/`; see `AGENTS.md`.

## Manual refresh

From the project directory, run:

```sh
python3 scripts/tracker.py refresh
```

Or open `scripts/Refresh Logbook.command` on macOS. This reads new or edited activities, saves a successful import, and rebuilds `dist/`. If importing fails, it stops before building. Add `--full` to request a complete reconciliation. This command does not deploy, commit, or push anything.

## GitHub automation

`.github/workflows/sync-and-deploy.yml` is ready for the repository setup described in `GITHUB_SETUP.md`. It provides:

- a **Run workflow** button with an optional full-reconciliation switch;
- an unattended incremental check every six hours;
- a monthly full reconciliation, enforced by the importer;
- a data-only bot commit when the tracked archive actually changes;
- tests, archive validation, a clean static build, and GitHub Pages deployment in the same run.

No-op incremental checks leave the manifest unchanged, avoiding timestamp-only commits. The Concept2 token is read from the `CONCEPT2_TOKEN` GitHub Actions secret and is never added to the repository or generated site.

## First local connection

1. Sign into [Concept2 Logbook](https://log.concept2.com/).
2. Open **Edit Profile → Applications → Concept2 Logbook API** and generate a personal authorization token. This application needs only read access.
3. Save it at a hidden terminal prompt:

   ```sh
   python3 scripts/tracker.py setup-token
   ```

   It is stored under `.secrets/` with owner-only permissions.

4. Import and audit:

   ```sh
   python3 scripts/tracker.py sync
   python3 scripts/tracker.py audit
   ```

   The first run downloads all pages with workout details and available stroke samples. Later runs use a five-minute overlapping `updated_after` window. A full reconciliation runs every 30 days or when requested with `sync --full`.

5. Build and serve the website locally:

   ```sh
   python3 scripts/tracker.py build
   python3 -m http.server 8765 --bind 127.0.0.1 --directory dist
   ```

   Open [the local site](http://127.0.0.1:8765/). Serve only `dist`, never the project root.

## Stored data

```text
data/archive/                    tracked raw Concept2 archive
  manifest.json                 account, active/retired IDs, successful checkpoints
  workouts/<Concept2 ID>.json   original detailed result and stroke availability
  strokes/<Concept2 ID>.json    original nonempty stroke samples, when available
  pending.json                  ignored recovery journal; exists only during commit/recovery
web/                            website source
dist/                           ignored generated Pages artifact
  data/index.json               compact activity index and totals
  data/activities/<ID>.json     projected workout metrics and splits/intervals
  data/strokes/<ID>.json        projected samples, loaded only on a detail page
```

The raw archive is intentionally public and preserves original API fields. It includes workout notes, source/device metadata, dates, timezones, physiology, and the Concept2 account/activity IDs. It does not contain the API token, account contact details, passwords, or location tracks. `publish_comments` controls only whether notes appear in the rendered website; the notes remain present in the tracked raw archive.

The browser-facing files use an explicit field allowlist. Deleted results are confirmed through a read-only detail request before they are retired from active totals, and their raw files remain archived.

## Counting policy and source units

The goal is 40,075,000 meters. Progress includes `rower`, `dynamic`, and `slides` workouts and any recorded interval rest distance. The activity table displays work distance; each detail page distinguishes work, rest, and goal contribution. Totals use the parent workout once and never add splits again.

Workout distance is meters and workout time is tenths of a second. Stroke distance is decimeters; stroke time and pace are tenths of a second. Stroke time and distance restart at each interval. Source dates and timezone fields are retained. Optional missing values remain absent rather than becoming zero.

## Failure behavior

- Pagination, counts, IDs, account identity, manifest structure, workout records, and stroke archives are validated.
- Downloads finish in disk staging before active records change.
- Checkpoints advance only after storage succeeds. A recovery journal blocks publishing if a disk commit is interrupted.
- A missing-strokes 404 is recorded as unavailable. Authorization, network, and server failures abort the import.
- Public output is built in staging and swapped atomically, preserving the last good site after a failed build.
- Monthly complete reconciliation catches deletions and changes that an incremental timestamp might miss.

Concept2 does not document snapshot-stable pagination or guarantee that stroke-only changes update a parent timestamp. A failed initial download restarts rather than resuming individual staged downloads.

## Checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/tracker.py audit --expected-meters 15925131 --expected-activities 1555
python3 scripts/tracker.py build
```

The tests cover pagination, retry and failure handling, identity binding, interrupted-write recovery, manifest and stroke validation, raw/browser projection, refresh ordering, and the HTML/JavaScript DOM contract. The GitHub workflow additionally runs `node --check web/app.js` before deployment.

API reference: [Concept2 Logbook API](https://log.concept2.com/developers/documentation/).
