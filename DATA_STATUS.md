# Live data validation — 27 September 2026

The first complete import and local website build succeeded. Concept2 was accessed with GET requests only. No Concept2 data or settings were modified, and no Git commits or pushes were performed.

| Check | Imported result | Comparison with the logbook |
|---|---:|---|
| Workouts | 1,555 unique records | Exact match |
| Lifetime distance | 15,925,131 m | Exact match |
| Work duration | 49 days, 17 hours, 47 minutes, 1.8 seconds | Matches the displayed 49 days, 17 hours |
| Recorded calories | 920,947 | Logbook displays 943,089; unresolved difference of 22,142 |

All imported workouts are rower activities, dated 9 June 2015 through 25 September 2026. None has recorded rest distance. Progress toward 40,075 km is 39.74%, with 24,149.869 km remaining.

Stroke samples are available for 1,052 workouts, totaling 1,065,201 samples. The other 503 workouts have no samples; their former empty placeholder files were removed without removing telemetry. The tracked archive preserves the original workout details and all nonempty samples.

The full download covered all 63 API pages. Two representative batch records and their stroke samples matched the individual workout endpoints exactly. An immediate incremental sync downloaded zero activities and changed no workout or stroke content.

All 30 automated tests pass. A clean rebuild from the real archive is reproducible. A separate export audit confirmed every public activity and stroke file matches its allowed source fields, with no missing or extra activities. Browser checks covered the overview, year filtering, pagination, keyboard activation, workout details, charts, unavailable telemetry, and split-discrepancy notices.

## Known source discrepancies

61 workouts omit `calories_total`: 44 from Concept2 Utility, 16 from Web, and one from ErgData iOS. Missing values alone have not been shown to explain the calorie difference. The website displays available per-workout calories and does not claim a reconciled lifetime calorie total.

Two workouts have substantial disagreements between source split durations and the parent workout duration: `41529581` and `58248951`. Both original representations are retained. Their detail pages include a discrepancy notice, and lifetime totals use the parent workout values. Other split differences are small rounding differences.

## Publication decision

The raw archive is intentionally included in the repository for completeness. It exposes the previously reviewed workout notes and device/source metadata along with detailed workout history. Credentials remain excluded. Generated `dist/` files are deployed as a Pages artifact instead of being committed.

The user handles all code and documentation commits and pushes. After repository setup, GitHub Actions may commit and push only successful changes under `data/archive/`.

## Remaining work

- Create the GitHub repository, add the Actions secret, select GitHub Actions as the Pages source, and make the initial user-controlled commit and push.
- Verify the first manual workflow run and Pages deployment.
- Connect `row.islandinamber.com` later.
- Continue improving presentation after hosting is stable.
