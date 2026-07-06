# nuvio-watchlist-sync

Backs up the Nuvio watchlist (library) of every profile on the account into text files committed to this repository, so the lists survive even if the app crashes, loses data, or disappears.

## How it works

Once a week, a GitHub Actions workflow runs [`backup_watchlists.py`](backup_watchlists.py), which:

1. Signs in to the Nuvio Cloud API with the account email/password (`POST /auth/v1/token?grant_type=password`).
2. Lists every profile on the account (`sync_pull_profiles`).
3. Pulls each profile's full watchlist (`sync_pull_library`, paginated).
4. Mirrors each watchlist into `watchlists/profile-<name>.txt` (e.g. `watchlists/profile-datt.txt`): a comment header with the profile name and a `Last synced` UTC timestamp, then one tab-separated line per item (`content_id`, `content_type`, `name`).

The merge is incremental: items already backed up are left untouched (same line, same position), new items are appended in the order they were added in the app, and items removed from the watchlist are removed from the backup. Files are matched to profiles by the profile index recorded in their header, so renaming a profile renames its backup file without losing history. Files for deleted profiles are removed. Item lines only change when the watchlist actually changes; the `Last synced` timestamp updates every run, so each weekly run commits and the files always show when the last successful sync happened.

API reference: [Nuvio Public API](https://nuvioapp.space/docs).

## Recommendations

A second job in the same workflow, `recommendations`, runs after `backup` completes and checks out the commit it just pushed. It runs [`generate_recommendations.py`](generate_recommendations.py), which turns everything the account has watched or wants to watch into a master recommendation list in [`recommendations.txt`](recommendations.txt):

1. Reads every `watchlists/profile-*.txt` file and pulls every profile's watch history from Nuvio (`sync_pull_watched_items`), de-duplicating the combined seed titles across profiles.
2. Looks each seed up on [TMDB](https://www.themoviedb.org) by its IMDb id (`/find`) and pulls TMDB's recommendations for it.
3. Aggregates across all seeds: a candidate ranks by how many seed titles recommend it (ties broken by TMDB vote average), and anything already watched or on any watchlist is excluded.
4. Writes the top 50 (`--limit` to change) as tab-separated lines — `content_id`, `content_type`, `name`, and a "because you watched" column citing a few of the seed titles that led to it.

This job is best-effort and commits independently of `backup`: if the `TMDB_API_KEY` secret is missing or TMDB is down, it's skipped without affecting the watchlist backup, which has already committed and pushed by that point. Watch history is likewise best-effort — if the Nuvio credentials are absent or the pull fails, recommendations fall back to watchlists only.

**Setup:** create a free TMDB account, get an API key at <https://www.themoviedb.org/settings/api> (the v3 key and the v4 read access token both work), and add it as the `TMDB_API_KEY` repository secret.

## Web UI

[`site/`](site/) is a static page (no build step) that renders `site/recommendations.json` — written by `generate_recommendations.py` alongside the text file — as a poster grid with TMDB cover art, ratings, vote counts, genres, and descriptions. Cards open a detail view with the full overview, the "because you watched" seed titles, and TMDB/IMDb links; the toolbar filters by movies/series, sorts by match/rating/year/title, and searches across titles, genres, and seeds. Cover art loads straight from TMDB's public image CDN, so the page needs no API key.

**Deploy on Vercel:** import the GitHub repo at <https://vercel.com/new>, set **Root Directory** to `nuvio-watchlist-sync/site`, framework preset "Other" — no build command or env vars needed. Each weekly sync commits a fresh `recommendations.json`, which triggers an automatic redeploy.

**Preview locally:** `python3 -m http.server -d site` and open <http://localhost:8000>.

## Run locally

```sh
NUVIO_EMAIL="you@example.com" NUVIO_PASSWORD="..." python3 backup_watchlists.py
NUVIO_EMAIL="you@example.com" NUVIO_PASSWORD="..." TMDB_API_KEY="..." python3 generate_recommendations.py
```

No dependencies beyond the Python 3 standard library. Backups are written to `watchlists/` (override with `--out-dir`); recommendations go to `recommendations.txt` (override with `--out`).

## Configuration

| Environment variable | Required | Purpose |
|---------------------|----------|---------|
| `NUVIO_EMAIL` | yes | Nuvio account email |
| `NUVIO_PASSWORD` | yes | Nuvio account password |
| `NUVIO_API_KEY` | no | Overrides the built-in public publishable key |
| `TMDB_API_KEY` | for recommendations | TMDB v3 API key or v4 read access token |

The workflow reads all three from GitHub Actions repository secrets of the same names.
