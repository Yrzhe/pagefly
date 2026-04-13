# Changelog

All notable changes to PageFly are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Scheduled task execution history** — every scheduled task run (system and user) is now recorded to the `task_runs` table with status (running/success/failed), started/finished timestamps, output, error, duration, and source (cron vs. user-triggered).
- **Run Now button** on user schedule cards — trigger a task immediately via `POST /api/schedules/{task_id}/run-now`; runs asynchronously and appears in history when complete.
- **Expandable run history** on the Schedules panel — click a schedule to view its recent runs; click a run to open a modal with full output / error and metadata.
- **`ingest` task type** implemented — dispatches to the query agent (same brain as the Telegram bot), so scheduled ingest/custom tasks can use all MCP tools (read/write knowledge, search, ingest URLs, compile wiki, etc.).
- New API endpoints: `GET /api/schedules/{task_id}/runs`, `GET /api/schedule-runs/recent`, `GET /api/schedule-runs/{run_id}`, `POST /api/schedules/{task_id}/run-now`.
- Telegram notifications now include a `Run #{id}` reference and truncate long output (3500 char cap) with a pointer to the Schedules tab for the full output.

### Changed
- Unified `custom` and `ingest` scheduled task types — both delegate to `src/agents/query.py:ask()`; the stored `task_type` still drives filtering and colors in the UI.
- Scheduler wraps every task in `_run_with_recording` — task failures never crash the scheduler, DB write failures log warnings but don't fail the task, notify failures are swallowed.
