#!/usr/bin/env python3
"""Generate a master recommendation list from every profile's viewing.

Seeds come from two places, combined across every profile on the
account: the backed-up watchlist files (watchlists/profile-*.txt) and
the live Nuvio watch history (the sync_pull_watched_items RPC, fetched
with the account credentials). Each seed title is looked up on TMDB
(The Movie Database) by its IMDb id, TMDB's "recommendations" for it
are pulled, and the results are aggregated into one ranked list:

    recommendations.txt

Candidates already on any watchlist or already watched are excluded.
A candidate ranks by how many seed titles recommend it (ties broken by
TMDB vote average, then name), and each line notes a few of the seed
titles that led to it:

    content_id<TAB>content_type<TAB>name<TAB>because you watched

Watch history is best-effort: if NUVIO_EMAIL/NUVIO_PASSWORD are unset
or the pull fails, recommendations fall back to watchlists only.

TMDB's API is free for non-commercial use: create an account at
https://www.themoviedb.org, then create a key at
https://www.themoviedb.org/settings/api. Both the v3 API key and the
v4 read access token work as TMDB_API_KEY.

Usage:
    NUVIO_EMAIL=... NUVIO_PASSWORD=... TMDB_API_KEY=... \
        python3 generate_recommendations.py \
        [--watchlist-dir DIR] [--out FILE] [--limit N]
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from backup_watchlists import fetch_profiles, rpc, sign_in

API_BASE = "https://api.themoviedb.org/3"

API_KEY = os.environ.get("TMDB_API_KEY", "")

# TMDB media type -> watchlist content_type vocabulary.
CONTENT_TYPE = {"movie": "movie", "tv": "series"}

IMDB_ID_RE = re.compile(r"tt\d+")

# The Nuvio app pulls the whole history in one page this size.
HISTORY_PAGE_SIZE = 100_000

MAX_SOURCES_SHOWN = 3


def tmdb_get(path, params=None):
    params = dict(params or {})
    headers = {"Accept": "application/json"}
    # v4 read access tokens are JWTs (dotted); v3 keys go in the query.
    if "." in API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    else:
        params["api_key"] = API_KEY
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {error.code} from {path}: {detail}") from None


def clean_field(value):
    """Collapse tabs/newlines so a title can't break the line format."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_watchlist_items(watchlist_dir):
    """Collect unique items across all profile backups: imdb_id -> name."""
    items = {}
    for entry in sorted(os.listdir(watchlist_dir)):
        if not (entry.startswith("profile-") and entry.endswith(".txt")):
            continue
        with open(os.path.join(watchlist_dir, entry)) as backup_file:
            for line in backup_file:
                if not line.strip() or line.startswith("#"):
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 3:
                    continue
                items.setdefault(fields[0], fields[2])
    return items


def fetch_watch_history(token):
    """Distinct watched titles across all profiles: imdb_id -> name or "".

    History rows are per-episode for series; collapsing to content_id
    yields one seed per title. Rows may not carry a display name — the
    TMDB lookup fills those in later.
    """
    items = {}
    for profile in fetch_profiles(token):
        rows = rpc(
            token,
            "sync_pull_watched_items",
            {
                "p_profile_id": profile["profile_index"],
                "p_page": 1,
                "p_page_size": HISTORY_PAGE_SIZE,
            },
        )
        for row in rows or []:
            content_id = clean_field(row.get("content_id"))
            if content_id:
                items.setdefault(
                    content_id, clean_field(row.get("name") or row.get("title"))
                )
    return items


def find_on_tmdb(imdb_id):
    """Map an IMDb id to (tmdb_media_type, tmdb_id, tmdb_name), or None."""
    result = tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
    for media_type, key in (("movie", "movie_results"), ("tv", "tv_results")):
        if result.get(key):
            entry = result[key][0]
            name = clean_field(entry.get("title") or entry.get("name"))
            return media_type, entry["id"], name
    return None


def fetch_recommendations(media_type, tmdb_id):
    result = tmdb_get(f"/{media_type}/{tmdb_id}/recommendations")
    return result.get("results") or []


def because_you_watched(sources):
    shown = sorted(sources)[:MAX_SOURCES_SHOWN]
    suffix = f" (+{len(sources) - len(shown)} more)" if len(sources) > len(shown) else ""
    return ", ".join(shown) + suffix


def build_candidates(items):
    """Aggregate TMDB recommendations across every seed title.

    `items` maps imdb_id -> display name ("" to use TMDB's). Returns
    candidates mapping (media_type, tmdb_id) -> {"name", "vote",
    "sources"}; seed titles themselves are excluded.
    """
    seeds = []
    seed_keys = set()
    for imdb_id, name in sorted(items.items()):
        if not IMDB_ID_RE.fullmatch(imdb_id):
            print(f"Skipping non-IMDb id {imdb_id!r} ({name})", file=sys.stderr)
            continue
        try:
            found = find_on_tmdb(imdb_id)
        except RuntimeError as error:
            print(f"Lookup failed for {name} ({imdb_id}): {error}", file=sys.stderr)
            continue
        if not found:
            print(f"No TMDB match for {name} ({imdb_id})", file=sys.stderr)
            continue
        media_type, tmdb_id, tmdb_name = found
        seeds.append(((media_type, tmdb_id), name or tmdb_name or imdb_id))
        seed_keys.add((media_type, tmdb_id))
    print(f"Mapped {len(seeds)}/{len(items)} seed titles to TMDB")

    candidates = {}
    for (media_type, tmdb_id), seed_name in seeds:
        try:
            recommendations = fetch_recommendations(media_type, tmdb_id)
        except RuntimeError as error:
            print(f"Recommendations failed for {seed_name}: {error}", file=sys.stderr)
            continue
        for rec in recommendations:
            rec_type = rec.get("media_type") or media_type
            key = (rec_type, rec["id"])
            if key in seed_keys:
                continue
            entry = candidates.setdefault(
                key,
                {
                    "name": clean_field(rec.get("title") or rec.get("name")),
                    "vote": round(rec.get("vote_average") or 0, 1),
                    "sources": set(),
                },
            )
            entry["sources"].add(seed_name)
    print(f"Collected {len(candidates)} candidates from {len(seeds)} items")
    return candidates


def rank_candidates(candidates):
    return sorted(
        candidates.items(),
        key=lambda kv: (-len(kv[1]["sources"]), -kv[1]["vote"], kv[1]["name"]),
    )


def resolve_lines(ranked, seed_imdb_ids, limit):
    """Turn ranked candidates into output lines, fetching IMDb ids lazily."""
    lines = []
    for (media_type, tmdb_id), info in ranked:
        if len(lines) >= limit:
            break
        try:
            external = tmdb_get(f"/{media_type}/{tmdb_id}/external_ids")
        except RuntimeError as error:
            print(f"External ids failed for {info['name']}: {error}", file=sys.stderr)
            external = {}
        imdb_id = external.get("imdb_id") or f"tmdb:{tmdb_id}"
        if imdb_id in seed_imdb_ids:
            continue
        lines.append(
            "\t".join(
                [
                    imdb_id,
                    CONTENT_TYPE[media_type],
                    info["name"],
                    because_you_watched(info["sources"]),
                ]
            )
        )
    return lines


def write_recommendations(path, lines):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = (
        "# Nuvio recommendations — aggregated from every profile's "
        "watchlist and watch history\n"
        "# Engine: TMDB recommendations (https://www.themoviedb.org)\n"
        f"# Last generated: {timestamp}\n"
        "# content_id\tcontent_type\tname\tbecause you watched\n"
    )
    with open(path, "w") as out_file:
        out_file.write(header)
        out_file.writelines(line + "\n" for line in lines)


def main():
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "--watchlist-dir", default="watchlists", help="directory with backup files"
    )
    arg_parser.add_argument(
        "--out", default="recommendations.txt", help="output file path"
    )
    arg_parser.add_argument(
        "--limit", type=int, default=50, help="number of recommendations to keep"
    )
    args = arg_parser.parse_args()

    if not API_KEY:
        print("TMDB_API_KEY must be set.", file=sys.stderr)
        sys.exit(1)
    try:
        tmdb_get("/configuration")
    except RuntimeError as error:
        print(f"TMDB auth check failed: {error}", file=sys.stderr)
        sys.exit(1)

    items = read_watchlist_items(args.watchlist_dir)
    if not items:
        print(f"No watchlist items found in {args.watchlist_dir}.", file=sys.stderr)
        sys.exit(1)
    watchlist_count = len(items)

    email = os.environ.get("NUVIO_EMAIL")
    password = os.environ.get("NUVIO_PASSWORD")
    history = {}
    if email and password:
        try:
            history = fetch_watch_history(sign_in(email, password))
        except Exception as error:
            print(
                f"Watch history unavailable ({error}); using watchlists only.",
                file=sys.stderr,
            )
    else:
        print(
            "NUVIO_EMAIL/NUVIO_PASSWORD not set; using watchlists only.",
            file=sys.stderr,
        )
    for imdb_id, name in history.items():
        items.setdefault(imdb_id, name)
    print(
        f"Seeds: {watchlist_count} from watchlists, "
        f"{len(items) - watchlist_count} more from watch history"
    )

    candidates = build_candidates(items)
    lines = resolve_lines(rank_candidates(candidates), set(items), args.limit)
    write_recommendations(args.out, lines)
    print(f"Wrote {len(lines)} recommendations to {args.out}")


if __name__ == "__main__":
    main()
