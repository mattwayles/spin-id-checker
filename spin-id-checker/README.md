# spin-id-checker

Checks whether one of my Wheel of Fortune Spin IDs won today's drawing — automatically, every day, with a push notification either way.

## How it works

[`check_spin_id.py`](check_spin_id.py) (Python 3, standard library only):

1. Fetches the current winning Spin ID from [wheeloffortunesolutions.com/spinid.html](http://www.wheeloffortunesolutions.com/spinid.html).
2. Extracts the value(s) from `<td class="TableSpinID">` cells using a real HTML parser — the page keeps old winning IDs inside HTML comments, so a plain text search would false-match.
3. Compares them against the hard-coded `MY_SPIN_IDS` list.
4. Prints the result, optionally appends it to a log file, and sends a push notification via [ntfy.sh](https://ntfy.sh):
   - **No win:** a quiet, low-priority daily heartbeat — proof the script is still running.
   - **Win:** an urgent, emoji-laden alert that's hard to miss.

## Automation

A GitHub Actions workflow ([`.github/workflows/spin-check.yml`](../.github/workflows/spin-check.yml)) runs the check daily at 16:00 UTC (~12pm ET) and commits the result to [`spin_log.txt`](spin_log.txt), building a permanent history of every run:

```
2026-07-03T19:34:07Z  winning_id=RL3853004  result=no-win
```

It can also be triggered manually from the **Actions** tab (**Daily Spin ID Check → Run workflow**).

## Running locally

```sh
python3 check_spin_id.py                     # print the result
python3 check_spin_id.py --log spin_log.txt  # ...and append it to the log
```

No dependencies to install.

## Notifications setup

The ntfy topic name acts as a shared secret, so it is not stored in this repo:

1. Invent a hard-to-guess topic name (treat it like a password).
2. Subscribe to that topic in the [ntfy app](https://ntfy.sh/) on your phone.
3. Add it as a GitHub Actions secret named `NTFY_TOPIC` (repo → Settings → Secrets and variables → Actions).

For local runs, set it in the environment: `NTFY_TOPIC=<topic> python3 check_spin_id.py`. If unset, notifications are skipped and everything else still works.
