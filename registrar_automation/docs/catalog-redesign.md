# Catalog Redesign: Eliminating Runtime Scraping

**Date:** 2026-07-03
**Status:** Proposed — written ahead of the next registration window, work not started.

## Problem

Registration is currently broken, and the window to fix it before the next
registration is slim. Two structural problems drive most failures:

1. **Runtime scraping dependency.** Course section IDs
   (`instance_X_component_Y_section_Z`) are discovered by a Playwright
   scraper *inside the user flow* — after schedule.txt is uploaded, the bot
   spawns a Celery scraping task against testregistrar. But testregistrar is
   frequently turned off a day or two before real registration. Last cycle it
   went down before the schedule was uploaded, so course codes were never
   scraped and the bot could not do its job.
2. **The scraper treats a static site as a dynamic one.** The registrar is a
   ~10-year-old Drupal site that has not substantially changed. Browser
   automation (Chromium, 2GB shm, timeouts, silent skips) is heavy machinery
   for what is likely a few plain HTTP endpoints.

## Key facts the design leans on

- **testregistrar and the real registrar share the same course codes/IDs.**
  Verified empirically in past registrations done through this program.
- **IDs are believed stable across time** — courses get added/deleted, but
  existing IDs don't appear to be renumbered. This is a *belief*, not a
  verified fact; the design protects against it being wrong (see Diff Report).
  - Open risk: IDs might be per-semester database rows (same course, new row
    each semester). Comparing two harvests across a semester boundary will
    answer this definitively.
- **Registration itself already needs no browser.** `core/api_registrar.py`
  runs on plain `requests`. Playwright exists *only* for catalog discovery.

## Target architecture

Replace "scrape at upload time" with "harvest early, store locally, look up
instantly."

### 1. Course catalog database — SQLite (not Redis)

Catalog data is durable, small, and precious; Redis stays as ephemeral job
plumbing. A single SQLite file gives durability across restarts, direct
inspectability while debugging, easy copying, and optional git-committed
snapshots for free history.

Schema (approximate):

```
course_code      TEXT    -- e.g. PHYS161
component_type   TEXT    -- Lecture / Lab / Seminar / ...
section_number   INTEGER
instance_id      INTEGER
component_id     INTEGER
section_id       INTEGER
semester         TEXT
harvested_at     TIMESTAMP
source           TEXT    -- 'test' or 'real'
```

### 2. Standalone harvest command — decoupled from the bot

A terminal command run whenever testregistrar is observed to be up (days or
weeks before registration): log in, walk the course list (candidate courses,
or the whole catalog — it's small), write everything to SQLite with a
timestamp. Because harvesting is decoupled, "testregistrar went down before
schedule upload" is no longer fatal — the harvest happened last week.

### 3. Schedule validation becomes a local lookup

Upload schedule.txt → validate against SQLite → instant response. Deletes the
scraping Celery task, the `scraper_queue`, and the bot's 2s-poll/60s-timeout
loop. Courses missing from the catalog produce a clear early error
("PHYS161 not in catalog, last harvest 2026-06-25") days before registration
instead of a failure at T-0.

### 4. Diff report + staleness warning — the safety net for the ID-stability assumption

- Each new harvest is diffed against the previous snapshot: added courses,
  removed courses, and — the killer case — any existing course whose IDs
  changed. If the stability hypothesis holds, this report reads "no changes"
  every cycle and costs nothing. If it ever breaks, it's caught in a report,
  not in a failed registration.
- The bot surfaces catalog age at job creation: "registering with catalog
  data harvested 9 days ago."

### Stretch goal: kill Playwright entirely

The section panel (`div#instanceSectionsPanel`) that the scraper reads is
almost certainly populated by an AJAX call to the same Drupal API family that
`register_course()` already uses. **Investigation step:** next time the site
is reachable, open devtools, click a course, and capture the network request
behind the panel. If it's a plain GET/POST, harvesting becomes a `requests`
loop and Playwright/Chromium leave the project completely (smaller Docker
image, no browser timeouts silently dropping courses). Worst case, Playwright
is demoted from runtime dependency to an offline harvest-only tool.

### Explicit non-goal

No dual path (live-scrape fallback + DB) in v1. A fallback scrape would fail
in exactly the situation it is meant to cover (site down), while doubling the
testing surface. DB-only, with loud staleness warnings.

## What this deletes

- `core/api_scraper.py` (or demotes it to an offline harvest tool)
- Playwright dependency + `playwright:v1.40.0-jammy` Docker base (→ `python:slim`)
- `scraper_queue` and the `update_course_ids` Celery task
- The bot's schedule-validation polling loop
- The whole class of "browser timed out / testregistrar is down" failures at
  registration time

Remaining moving parts at T-0: scheduler fires → requests login →
requests register calls using IDs from a local file.

## Order of attack

1. **Investigate the section-panel endpoint** (devtools capture, ~10 min when
   the site is up). Decides pure-HTTP harvest vs Playwright-as-offline-tool.
2. **Build the SQLite catalog + harvest script** using whatever step 1 yields.
3. **Rewire schedule validation** to read the catalog locally.
4. **Add the diff report + staleness warning.**
5. **Fold in reliability fixes from the 2026-07-03 code review** (see below) —
   the slim registration window makes the T-0 fixes non-optional.

## Appendix: code review findings (2026-07-03)

Independent of the redesign, in priority order:

1. **Confirmed bug — scheduler broker URL is not an f-string.**
   `scheduler/scheduler.py:15`: `broker='redis://{REDIS_HOST}:6379/0'` is a
   literal string; Celery resolves a host literally named `{REDIS_HOST}`.
   Fails/hangs on first `send_task`. Fix + full end-to-end test against
   testregistrar before trusting anything else.
2. **Config chaos.** `core/tasks.py:15` hardcodes `localhost:6379` while
   `celery_app.py` reads env; `REDIS_HOST` defaults differ per module
   (`127.0.0.1` vs `redis`); notification endpoint hardcoded to
   `http://127.0.0.1:8000`; `update_course_ids` hardcodes `mode='test'`.
   Centralize into one settings module imported everywhere.
3. **No retries at the critical moment.** One attempt per course in
   `run_registration`; pre-login session TTL (5 min) can expire before the
   registration task fires; scheduler is a single unsupervised loop
   (`restart: always` + idempotent dispatch — a crash between "send task" and
   "delete key" currently double-fires).
4. **Silent failure swallowing.** Bot polling loop `except Exception:
   continue`; Playwright timeouts skip courses silently; unknown section
   types accepted without complaint. Also add a dry-run health check (login,
   parse, verify selectors/endpoints) to run the evening before registration.
5. **Hygiene.** `verify=False` on all requests (real credentials exposed to
   MITM); credentials in plaintext through Redis/Celery bodies; no TTLs on
   job/index Redis keys; dead code (`core/redis_utils.py`, unused
   `confirming` FSM state); `DEFAULT_ATTEMPTS = 100` duplicated in two files;
   web API has zero authentication (acceptable only while loopback-only).
6. **Stack age.** Deps pinned to late-2023 (Playwright 1.40, aiogram 3.2,
   FastAPI 0.108). Refresh during the rework.

Note: `.env` is **not** tracked in git (`*.env` ignore works), but the bot
token lives in plaintext on disk — rotating it occasionally is cheap
insurance.

## Open question

Does any old scraped data exist to compare IDs across semesters? That would
settle the ID-stability assumption before harvest #1 vs #2 can.
