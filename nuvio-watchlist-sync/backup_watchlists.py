#!/usr/bin/env python3
"""Back up Nuvio watchlists for every profile on the account.

Signs in to the Nuvio Cloud API (Supabase-backed) with the account
email/password, lists all profiles, pulls each profile's library (the
app's watchlist of bookmarked items), and mirrors it into one text file
per profile under the output directory, named after the profile:

    watchlists/profile-datt.txt, watchlists/profile-danielle.txt, ...

Each file starts with a comment header (profile name and a "Last
synced" UTC timestamp) followed by one item per line as tab-separated
fields:

    content_id<TAB>content_type<TAB>name

The merge is incremental so git diffs stay minimal: items already in
the backup keep their existing line and position, new items are
appended in the order they were added to the watchlist, and items no
longer on the watchlist are dropped. Files for profiles that no longer
exist on the account are deleted. Files are matched to profiles by the
profile index recorded in their header, so renaming a profile renames
its backup file without losing history.

Usage:
    NUVIO_EMAIL=... NUVIO_PASSWORD=... python3 backup_watchlists.py [--out-dir DIR]

API reference: https://nuvioapp.space/docs (Nuvio Public API).
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.nuvio.tv"

# Nuvio's publishable key is intentionally public (it appears in the
# official API docs); it only identifies the client, all authorization
# comes from the bearer token.
PUBLISHABLE_KEY = os.environ.get(
    "NUVIO_API_KEY", "sb_publishable_1Clq8rlTVACkdcZuqr6_AD__xUUC_EN"
)

PAGE_SIZE = 500

HEADER_INDEX_RE = re.compile(r"^# Nuvio watchlist backup — profile (\d+):")


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unnamed"


def post_json(url, payload, token=None):
    headers = {
        "Content-Type": "application/json",
        "apikey": PUBLISHABLE_KEY,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from None
    return json.loads(body) if body.strip() else None


def sign_in(email, password):
    result = post_json(
        f"{API_BASE}/auth/v1/token?grant_type=password",
        {"email": email, "password": password},
    )
    return result["access_token"]


def rpc(token, function, payload):
    return post_json(f"{API_BASE}/rest/v1/rpc/{function}", payload, token=token)


def fetch_profiles(token):
    return rpc(token, "sync_pull_profiles", {})


def fetch_watchlist(token, profile_index):
    """Pull the full library for one profile, following pagination."""
    items = []
    offset = 0
    while True:
        page = rpc(
            token,
            "sync_pull_library",
            {"p_profile_id": profile_index, "p_limit": PAGE_SIZE, "p_offset": offset},
        )
        items.extend(page)
        if len(page) < PAGE_SIZE:
            return items
        offset += PAGE_SIZE


def clean_field(value):
    """Collapse tabs/newlines so a title can't break the line format."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def item_line(item):
    return "\t".join(
        [
            clean_field(item.get("content_id")),
            clean_field(item.get("content_type")),
            clean_field(item.get("name")),
        ]
    )


def read_backup_lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as backup_file:
        return [
            line.rstrip("\n")
            for line in backup_file
            if line.strip() and not line.startswith("#")
        ]


def merge_backup(existing_lines, items):
    """Keep existing lines for items still present, append new ones.

    Returns (lines, added_count, removed_count). Existing items are
    left untouched (their line and position are preserved) so the
    backup only changes when the watchlist actually changes.
    """
    current_ids = {clean_field(item.get("content_id")) for item in items}
    kept = [line for line in existing_lines if line.split("\t", 1)[0] in current_ids]
    kept_ids = {line.split("\t", 1)[0] for line in kept}
    new_items = sorted(
        (item for item in items if clean_field(item.get("content_id")) not in kept_ids),
        key=lambda item: item.get("added_at") or 0,
    )
    lines = kept + [item_line(item) for item in new_items]
    return lines, len(new_items), len(existing_lines) - len(kept)


def write_backup(path, profile, lines):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = (
        f"# Nuvio watchlist backup — profile {profile['profile_index']}: "
        f"{clean_field(profile.get('name'))}\n"
        f"# Last synced: {timestamp}\n"
        "# content_id\tcontent_type\tname\n"
    )
    with open(path, "w") as backup_file:
        backup_file.write(header)
        backup_file.writelines(line + "\n" for line in lines)


def profile_backup_files(out_dir):
    """Yield (path, profile_index) for each existing backup file."""
    for entry in sorted(os.listdir(out_dir)):
        if not (entry.startswith("profile-") and entry.endswith(".txt")):
            continue
        path = os.path.join(out_dir, entry)
        with open(path) as backup_file:
            match = HEADER_INDEX_RE.match(backup_file.readline())
        if match:
            yield path, int(match.group(1))


def find_existing_file(out_dir, profile_index):
    for path, index in profile_backup_files(out_dir):
        if index == profile_index:
            return path
    return None


def remove_stale_profile_files(out_dir, active_indexes):
    for path, index in profile_backup_files(out_dir):
        if index not in active_indexes:
            os.remove(path)
            print(f"Removed backup for deleted profile: {os.path.basename(path)}")


def main():
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "--out-dir", default="watchlists", help="directory for backup files"
    )
    args = arg_parser.parse_args()

    email = os.environ.get("NUVIO_EMAIL")
    password = os.environ.get("NUVIO_PASSWORD")
    if not email or not password:
        print("NUVIO_EMAIL and NUVIO_PASSWORD must be set.", file=sys.stderr)
        sys.exit(1)

    try:
        token = sign_in(email, password)
    except Exception as error:
        print(f"Nuvio sign-in failed: {error}", file=sys.stderr)
        sys.exit(1)

    profiles = fetch_profiles(token)
    if not profiles:
        print("No profiles returned; leaving backups untouched.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)

    for profile in sorted(profiles, key=lambda p: p["profile_index"]):
        index = profile["profile_index"]
        items = fetch_watchlist(token, index)
        old_path = find_existing_file(args.out_dir, index)
        new_path = os.path.join(
            args.out_dir, f"profile-{slugify(clean_field(profile.get('name')))}.txt"
        )
        lines, added, removed = merge_backup(read_backup_lines(old_path), items)
        write_backup(new_path, profile, lines)
        if old_path and old_path != new_path:
            os.remove(old_path)
        print(
            f"Profile {index} ({clean_field(profile.get('name'))}): "
            f"{len(lines)} items ({added} added, {removed} removed)"
        )

    remove_stale_profile_files(
        args.out_dir, {profile["profile_index"] for profile in profiles}
    )


if __name__ == "__main__":
    main()
