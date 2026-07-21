# DemoSense

Hierarchical membership, reporting, and survey system for Democratic Party clubs.
See `DemoSense_Development_Plan.md` for the full design and phase plan.

## Status

Phases 1-4 complete: data model + hierarchy, API + auth + RBAC, surveys +
responses, and aggregation/rollup. The app is async throughout (SQLAlchemy
2.0 async + FastAPI). Login is via JWT (fastapi-users). Every read/write
endpoint is scoped to the org units a person's role grants cover - a county
admin can see and manage their own county's subtree and nothing else,
enforced server-side and covered by tests (`tests/test_rbac.py`). The real
"Hometown Survey" and "Member Story" surveys (`DemoSense Surveys V1.pdf`)
are seeded and answer-validated per question kind/config
(`tests/test_survey_validation.py`, `tests/test_survey_api.py`). Rollups are
computed directly from completed answers filtered by org-unit path prefix
(or group membership) - correct by construction, no bottom-up merging of
pre-averaged child stats, verified against hand-computed numbers
(`tests/test_rollup.py`: a county's aggregate exactly equals the sum of its
clubs'). A confidentiality threshold (`respondent_n < 5`) suppresses
detailed stats at read time, enforced in the API layer, not the client.
Phase 5 (dashboard) is next.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in:
- `DATABASE_URL` - a Postgres connection string (`postgresql+psycopg://...`).
  Developed against a free [Neon](https://neon.tech) Postgres 17 instance -
  any Postgres 16+ works.
- `JWT_SECRET` - generate with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Enable required extensions once, then run migrations:

```bash
python -c "
from demosense.config import settings
from sqlalchemy import create_engine, text
engine = create_engine(settings.database_url)
with engine.begin() as conn:
    conn.execute(text('CREATE EXTENSION IF NOT EXISTS citext'))
    conn.execute(text('CREATE EXTENSION IF NOT EXISTS pgcrypto'))
"
alembic upgrade head
python scripts/seed_position_types.py
python scripts/seed_surveys.py
```

## Running the API

```bash
python scripts/run_api.py
```

Serves on http://127.0.0.1:8000 with interactive docs at `/docs`.

The public `/auth/register` endpoint cannot grant superuser (by design -
fastapi-users strips that from untrusted input). Bootstrap the first one
directly:

```bash
python scripts/create_superuser.py you@example.com "First" "Last"
```

From there: log in as the superuser (`POST /auth/jwt/login`) to create the
org hierarchy (`POST /org-units`) and grant roles to other accounts
(`POST /role-grants`) - club/county/state/national admins can then manage
their own scope without further superuser involvement.

**Note on Windows:** psycopg3's async mode needs the SelectorEventLoop, not
the ProactorEventLoop Windows defaults to. Every async entrypoint (the API
server, Alembic, scripts, tests) calls
`demosense.winloop.use_selector_event_loop_on_windows()` before anything
else - if you add a new entrypoint, do the same.

**Note on Neon:** the engine is created with `pool_pre_ping=True`
(`src/demosense/db.py`) - Neon's compute can suspend and terminate idle
pooled connections, which otherwise surfaces as an `AdminShutdown` /
`OperationalError` on the next request. Pre-ping tests each connection
before use and transparently reconnects.

## Filling out a survey

```
GET  /surveys                              # list open surveys
GET  /surveys/{survey_id}                  # full definition incl. questions
POST /surveys/{survey_id}/responses        # start a response {org_unit_id, anonymous?}
PATCH /responses/{response_set_id}/answers # save answers, partial saves OK
                                            #   {"answers": [{"question_id", "value_bool"|
                                            #   "value_numeric"|"value_text"|"value_choice"}]}
POST /responses/{response_set_id}/submit   # finalize - rejects if a required
                                            # question has no answer, or if
                                            # already submitted
```

Any authenticated active person may respond - filing a report isn't
admin-gated the way creating org units is. `org_unit_id` must be the
survey's `target_org_unit_id` or a descendant of it. Setting
`anonymous: true` on creation means `person_id` (and caucus/committee
`group_ids`) are never recorded for that response, even though the API
call itself is authenticated - there's no "list responses" endpoint in v1,
so an anonymous response's id is the only way to reach it again.

Survey definitions themselves are seed-script-only in v1 (`scripts/seed_surveys.py`)
- no API endpoint creates surveys. Per the plan: "you have 15 questions and
you control them," don't build a survey builder for two known question sets.

## Rollups and aggregates

```
POST /surveys/{survey_id}/rollup            # recompute every (question, org
                                              # node) aggregate for a survey -
                                              # admin access over the survey's
                                              # target_org_unit required
GET  /org-units/{unit_id}/aggregates?survey_id=...  # read them back, scoped
                                              # like any other read
```

Each aggregate row is computed directly from completed answers whose
`org_unit_path` is at-or-below the node (or, for cross-cutting groups, whose
`group_ids` contains it) - never by combining child nodes' pre-computed
stats, which is what makes "county = sum of clubs" true by construction
rather than something that has to be gotten right in application code.
`stats` always includes `"n"`; when `respondent_n < 5`
(`services/rollup.MIN_RESPONDENTS_FOR_DETAIL`) the API returns
`"stats": null, "suppressed": true` and only the count - raw `answer` rows
are never one API call away from a small-group deanonymization. There's no
scheduled/nightly rollup job yet (plan Phase 4 step 5) - `POST .../rollup`
is a manual trigger; wiring APScheduler is a small follow-up, not yet done.
Text questions are skipped (`stats: null` isn't written) - free-text rollup
is Phase 6 (AI summarization).

Rollup does one DB round-trip per (org unit, question) pair, so a
full-hierarchy trigger is O(nodes x questions) sequential queries - fine at
pilot scale (confirmed live: ~85 queries for a 5-node tree x 17 questions
took well under the default 20s but is noticeably not instant over a
network DB). Would want batching if the hierarchy grows much larger.

## Loading real data

```bash
python scripts/import_county.py path/to/your_county.csv
```

See the docstring in `scripts/import_county.py` for the expected CSV columns.
`scripts/sample_county_template.csv` is a filled-in example (fictional
placeholder people - not real data, safe to import/delete freely).

## Tests

```bash
pytest
```

`test_hierarchy.py`, `test_survey_validation.py`, and `test_rollup.py` wrap
each test in a transaction that's rolled back afterward (or need no DB at
all) - fast, no cleanup needed; this works for rollup too since
`run_rollup_for_survey` only `flush()`s, like the other services.
`test_rbac.py` and `test_survey_api.py` go through the real HTTP API (route
handlers commit directly, so there's no transaction to roll back) and tear
down exactly what each test created. All run against the real
`DATABASE_URL` - no separate test database needed. Org unit slugs in tests
are tagged with a random suffix per run - `org_unit.slug` is globally
unique, and real seed data commits units like `usa` outside any test
transaction.

## Repository layout

```
src/demosense/
    models/     SQLAlchemy ORM classes
    schemas/    Pydantic request/response models
    services/   business logic - hierarchy, rbac, audit, survey validation, rollup
    api/        FastAPI app + route modules
    auth.py     fastapi-users wiring (JWT, user manager)
    workers/    scheduled jobs (none yet - rollup is manually triggered)
alembic/        migrations
tests/
scripts/        data import, seeding, server launcher, superuser bootstrap
```
