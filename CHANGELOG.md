# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] - 2026-06-18

### Added
- Interactive menu to choose resource type (Servers / Websites) and operation.
- **Create** mode for bulk-importing new resources from CSV.
- **Update — Replace** mode that overwrites a resource's access policies.
- **Update — Append** mode that merges CSV policies into existing ones
  (permissions are unioned, never downgraded).
- **Dry-run** mode that validates and previews payloads without making changes.
- Pre-flight validation that checks every connector, group, user and
  resource name in the CSV before any change is made.
- Automatic injection of the running API user with `Manage` access on every
  resource, so the automation never locks itself out.
- Three-level permission columns (`VIEW` / `CONNECT` / `MANAGE`) for both
  groups and users, with semicolon-separated multi-value support.
- Command-line flags (`--resource`, `--mode`, `--csv`, `--dry-run`, `--yes`)
  for non-interactive / scripted runs.
- Timestamped run logs written to `logs/`.
- Environment-based configuration via `.env`.
