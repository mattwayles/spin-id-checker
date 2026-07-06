# automations

A collection of small, independent automations, each living in its own top-level directory with its own GitHub Actions workflow.

## Packages

- [`spin-id-checker/`](spin-id-checker/) — checks whether a Wheel of Fortune Spin ID has won today's drawing, on a daily schedule, with a push notification either way.

## Layout conventions

Each package is self-contained: its own README, its own dependencies (if any), its own log/state files. GitHub Actions requires workflow files to live under the shared [`.github/workflows/`](.github/workflows/) directory at the repo root, but each workflow scopes itself to one package via `working-directory` and its own trigger/schedule — packages don't share runtime state or secrets unless a workflow explicitly does so.

To add a new automation:

1. Create a new top-level directory for it.
2. Add a workflow file under `.github/workflows/` that sets `working-directory` (or `cd`s) into that directory.
3. Give the package its own README describing what it does and how to run it locally.
