#!/usr/bin/env python3
"""Check Wheel of Fortune Spin IDs against the current winning ID.

Fetches http://www.wheeloffortunesolutions.com/spinid.html, extracts the
spin ID value(s) from <td class="TableSpinID"> cells, and compares them
against a hard-coded list of our spin IDs.

Usage:
    python3 check_spin_id.py [--log FILE]

With --log, appends a one-line entry (timestamp, winning IDs, outcome)
to FILE for historical tracking.

Sends a push notification with the outcome via ntfy.sh if the
NTFY_TOPIC environment variable is set (subscribe to the same topic in
the ntfy phone app to receive it): a quiet daily heartbeat on a loss,
an urgent celebration on a win.
"""

import argparse
import os
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

URL = "http://www.wheeloffortunesolutions.com/spinid.html"

MY_SPIN_IDS = [
    "RR3854572101",
    "JH8449088738",
    "MW3930992364",
    "MB2118330725",
    "DR5743219"
]


class SpinIdParser(HTMLParser):
    """Collects text from <td class="TableSpinID"> cells.

    Using an HTML parser (rather than a regex) matters here: the page keeps
    old winning IDs inside HTML comments, which the parser skips.
    """

    def __init__(self):
        super().__init__()
        self.spin_ids = []
        self._in_spin_id_cell = False
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            classes = dict(attrs).get("class", "")
            if "tablespinid" in classes.lower().split():
                self._in_spin_id_cell = True
                self._buffer = []

    def handle_endtag(self, tag):
        if tag == "td" and self._in_spin_id_cell:
            self._in_spin_id_cell = False
            text = "".join(self._buffer).strip()
            if text:
                self.spin_ids.append(text)

    def handle_data(self, data):
        if self._in_spin_id_cell:
            self._buffer.append(data)


def fetch_winning_spin_ids(url=URL):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    parser = SpinIdParser()
    parser.feed(html)
    return parser.spin_ids


def send_notification(matches):
    """Push the day's outcome to the ntfy.sh topic named in NTFY_TOPIC.

    The topic name acts as a shared secret, so it comes from the
    environment (a GitHub Actions secret) rather than the source.
    HTTP headers only allow ASCII, so emojis live in the body and in
    ntfy's emoji-shortcode Tags header.
    """
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set; skipping notification.", file=sys.stderr)
        return
    if matches:
        message = (
            "\U0001f6a8\U0001f389 HOLY CRAP, SPIN ID "
            f"{', '.join(matches)}"
            " ACTUALLY WON TODAY'S WHEEL OF FORTUNE SPIN ID DRAWING! "
            "\U0001f389\U0001f4b0\U0001f525\U0001f973"
        )
        headers = {
            "Title": "!!! WHEEL OF FORTUNE SPIN ID WINNER !!!",
            "Priority": "urgent",
            "Tags": "rotating_light,tada,moneybag,partying_face",
        }
    else:
        message = "Your Spin ID did not win today's drawing :("
        headers = {
            "Title": "Wheel of Fortune Spin ID check",
            "Priority": "low",
            "Tags": "shrug",
        }
    request = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=30)
        print("Notification sent.")
    except Exception as error:
        print(f"Failed to send notification: {error}", file=sys.stderr)


def append_log(log_path, winning_ids, matches):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    outcome = f"WIN ({','.join(matches)})" if matches else "no-win"
    with open(log_path, "a") as log_file:
        log_file.write(
            f"{timestamp}  winning_id={','.join(winning_ids)}  result={outcome}\n"
        )


def main():
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("--log", metavar="FILE", help="append the result to FILE")
    args = arg_parser.parse_args()

    try:
        winning_ids = fetch_winning_spin_ids()
    except Exception as error:
        print(f"Error fetching spin ID page: {error}", file=sys.stderr)
        sys.exit(1)

    if not winning_ids:
        print("No spin ID found on the page.", file=sys.stderr)
        sys.exit(1)

    matches = [spin_id for spin_id in MY_SPIN_IDS if spin_id in winning_ids]
    if matches:
        for winning_id in matches:
            print(f"Winner! Winning ID: {winning_id}")
    else:
        print("no win, try again next time!")

    if args.log:
        append_log(args.log, winning_ids, matches)

    send_notification(matches)


if __name__ == "__main__":
    main()
