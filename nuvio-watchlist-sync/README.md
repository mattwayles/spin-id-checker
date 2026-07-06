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

## Run locally

```sh
NUVIO_EMAIL="you@example.com" NUVIO_PASSWORD="..." python3 backup_watchlists.py
```

No dependencies beyond the Python 3 standard library. Backups are written to `watchlists/` (override with `--out-dir`).

## Configuration

| Environment variable | Required | Purpose |
|---------------------|----------|---------|
| `NUVIO_EMAIL` | yes | Nuvio account email |
| `NUVIO_PASSWORD` | yes | Nuvio account password |
| `NUVIO_API_KEY` | no | Overrides the built-in public publishable key |

The workflow reads `NUVIO_EMAIL` and `NUVIO_PASSWORD` from GitHub Actions repository secrets of the same names.
