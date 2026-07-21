# DemoSense — Strategic Development Plan

**A hierarchical membership, reporting, and survey system for Democratic Party clubs**

Prepared July 2026 · Target builder profile: intermediate Python developer, solo or 2–3 person volunteer team

---

## 0. How to read this document

Sections 1–4 are **design** (what you are building and why the data model looks the way it does). Sections 5–9 are **execution** (the phased build, week by week). Sections 10–13 are **supporting concerns** — skills you need to pick up, where AI-assisted tooling like Lovable helps and where it will hurt you, risks, and how you know you're done.

If you only read two sections, read **Section 3 (the data model)** and **Section 6 (Phase 1)**. Everything else is downstream of getting the schema right.

---

## 1. Scope decision: build the spine first

The DemoSense overview describes roughly a dozen subsystems — surveys, club health reports, incident reporting, a member expertise directory, hometown pages, a wiki, a video library, shared club websites, an internal social layer, opposition monitoring. That is a five-year program for a funded team. It is not a first project.

Almost all of it depends on one thing existing first: **a correct, queryable model of who belongs to what, and where that sits in the hierarchy.** Every rollup, every dashboard scope, every "which members are in this county" query, and every permission check reads from that model. Get it wrong and you rewrite everything above it.

So the scope of this plan is deliberately narrow:

| In scope (v1) | Deferred (v2+) |
|---|---|
| Organizational hierarchy (national → state → county → local) | Club websites / shared CMS |
| Cross-cutting groups (caucuses, committees) | Wiki and video library |
| People, memberships, positions/offices | Internal social layer |
| Survey definition and response capture | Mobile canvassing app |
| Monthly structured club health report | Opposition monitoring archive |
| Aggregation and rollup through the hierarchy | Member expertise directory (v1.5 — cheap to add) |
| Role-gated dashboard | AI summarization (v1.5 — deliberately last) |

Ship the left column. It's the thing that makes the right column possible, and it's the thing you can demo to a county committee to get buy-in.

---

## 2. Reading your ER sketch

Your sketch contains three ideas. Two are correct as drawn; one needs a decision.

**Sketch 1 — Person ⟷ Caucus/Club, many-to-many.** Correct. A person belongs to several clubs; a club has many people.

**Sketch 2 — Club → Members → Position.** Also correct, and the important detail is that `Position` hangs off the *membership*, not off the *person*. A person can be Treasurer of one club and an ordinary member of another. Position is a property of the relationship, not of the human.

**Sketch 3 — Person → [junction] → Clubs/Groups**, annotated `PID1 CLUB1`. This is the resolution of the many-to-many into a physical join table, which is exactly right. The `CUID?` note in the margin is the open question: what is the primary key?

**Decision on keys.** Use a surrogate `UUID` primary key on the junction table rather than a composite `(person_id, club_id)`. Reason: a person can leave a club and rejoin two years later. With a composite key that's an update that destroys history; with a surrogate key plus `start_date`/`end_date` it's a second row and you keep the membership history — which you will want for club health trends. Add a partial unique index to prevent two *simultaneously active* memberships in the same club.

**One thing the sketch is missing.** There is no entity for the hierarchy itself. `Club` in your sketch is flat. But a club belongs to a county, which belongs to a state, which belongs to the national organization — and the entire value of the system is rolling data *up* that chain. That needs to be modelled explicitly, and it's the subject of the next section.

---

## 3. The data model

### 3.1 Modelling the hierarchy

You have two independent structures that both need rollups:

1. **The geographic tree** — National → State → County → Local club. Strictly hierarchical, each node has exactly one parent.
2. **Cross-cutting groups** — caucuses (Rural, Veterans, Environment), standing committees, issue groups. These are *not* in the tree. A member of the Santa Barbara club may also be in the statewide Healthcare Caucus. Both memberships must feed rollups independently.

The mistake to avoid is inventing separate `state`, `county`, `club` tables. That gives you four near-identical tables, four sets of joins, and breaks the moment someone creates a regional body that sits between county and club (they exist). Instead use **one `org_unit` table with a self-referencing parent and a `level` enum**. This is the *adjacency list* pattern.

Adjacency lists are awkward for "give me everything beneath this node" queries. Two solutions, both good on PostgreSQL:

- **Recursive CTE** (`WITH RECURSIVE`) — no extra schema, standard SQL, fast enough for a few thousand nodes. **Start here.**
- **`ltree` materialized path** — a Postgres extension storing `usa.ca.santa_barbara.goleta_club` as an indexed path column. Subtree queries become a single indexed operator. Adopt if recursive CTEs get slow, which at Party scale they probably won't.

### 3.2 Core schema (PostgreSQL DDL)

```sql
-- ============================================================
-- ORGANIZATIONAL STRUCTURE
-- ============================================================

CREATE TYPE org_level AS ENUM ('national', 'state', 'region', 'county', 'local');
CREATE TYPE group_kind AS ENUM ('caucus', 'committee', 'issue_group', 'constituency_group');

CREATE TABLE org_unit (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id     UUID REFERENCES org_unit(id) ON DELETE RESTRICT,
    level         org_level NOT NULL,
    name          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    -- denormalised path, maintained by trigger; enables fast subtree reads
    path          TEXT NOT NULL,
    fips_code     TEXT,              -- county/state standard geo code, nullable
    website_url   TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT national_has_no_parent
        CHECK ((level = 'national') = (parent_id IS NULL))
);
CREATE INDEX ON org_unit (parent_id);
CREATE INDEX ON org_unit (path text_pattern_ops);

-- Cross-cutting groups: parallel to the tree, NOT inside it.
-- scope_org_unit_id says how far the group reaches (statewide caucus,
-- county committee), which is what lets you scope its dashboards.
CREATE TABLE org_group (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind               group_kind NOT NULL,
    name               TEXT NOT NULL,
    slug               TEXT NOT NULL UNIQUE,
    scope_org_unit_id  UUID NOT NULL REFERENCES org_unit(id),
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- PEOPLE AND MEMBERSHIP  (this is your sketch, formalised)
-- ============================================================

CREATE TABLE person (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         CITEXT UNIQUE,     -- CITEXT = case-insensitive
    phone         TEXT,
    postal_code   TEXT,
    home_org_unit_id UUID REFERENCES org_unit(id),  -- their "primary" club
    joined_party_on  DATE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Positions are a controlled vocabulary, not free text, or your
-- "how many clubs have a treasurer?" query will never work.
CREATE TABLE position_type (
    id            SMALLSERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,   -- 'president', 'treasurer', 'member'
    label         TEXT NOT NULL,
    is_officer    BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order    SMALLINT NOT NULL DEFAULT 100
);

-- THE JUNCTION TABLE from your sketch.
-- Surrogate PK + date range = full membership history.
CREATE TABLE membership (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id        UUID NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    org_unit_id      UUID REFERENCES org_unit(id) ON DELETE CASCADE,
    org_group_id     UUID REFERENCES org_group(id) ON DELETE CASCADE,
    position_type_id SMALLINT NOT NULL REFERENCES position_type(id),
    start_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date         DATE,
    notes            TEXT,
    -- a membership attaches to a club OR a group, never both, never neither
    CONSTRAINT exactly_one_target CHECK (
        (org_unit_id IS NOT NULL) <> (org_group_id IS NOT NULL)
    ),
    CONSTRAINT sane_dates CHECK (end_date IS NULL OR end_date >= start_date)
);

-- Prevent duplicate *active* memberships, while still allowing
-- a person to rejoin later as a new row.
CREATE UNIQUE INDEX one_active_club_membership
    ON membership (person_id, org_unit_id)
    WHERE end_date IS NULL AND org_unit_id IS NOT NULL;
CREATE UNIQUE INDEX one_active_group_membership
    ON membership (person_id, org_group_id)
    WHERE end_date IS NULL AND org_group_id IS NOT NULL;

CREATE INDEX ON membership (org_unit_id) WHERE end_date IS NULL;
CREATE INDEX ON membership (org_group_id) WHERE end_date IS NULL;

-- ============================================================
-- SURVEYS AND REPORTS
-- ============================================================

CREATE TYPE question_kind AS ENUM ('boolean', 'ordinal', 'single_choice',
                                   'multi_choice', 'numeric', 'text');
CREATE TYPE survey_status AS ENUM ('draft', 'open', 'closed', 'archived');
CREATE TYPE respondent_kind AS ENUM ('person', 'club');  -- who files it

CREATE TABLE survey (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              TEXT NOT NULL,
    description        TEXT,
    status             survey_status NOT NULL DEFAULT 'draft',
    respondent         respondent_kind NOT NULL DEFAULT 'person',
    -- who is allowed/asked to respond: everyone at or below this node
    target_org_unit_id UUID NOT NULL REFERENCES org_unit(id),
    target_group_id    UUID REFERENCES org_group(id),
    opens_at           TIMESTAMPTZ,
    closes_at          TIMESTAMPTZ,
    is_recurring       BOOLEAN NOT NULL DEFAULT FALSE,
    recurrence_rule    TEXT,          -- iCal RRULE, e.g. monthly club health
    created_by         UUID REFERENCES person(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE question (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    survey_id     UUID NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    ordinal       SMALLINT NOT NULL,
    kind          question_kind NOT NULL,
    prompt        TEXT NOT NULL,
    help_text     TEXT,
    is_required   BOOLEAN NOT NULL DEFAULT FALSE,
    -- kind-specific config: {"min":1,"max":5,"labels":[...]} etc.
    config        JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (survey_id, ordinal)
);

-- One row per (respondent, survey). Carries the org tags that make
-- rollup possible — denormalised ON PURPOSE so history survives
-- someone changing clubs after they answered.
CREATE TABLE response_set (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    survey_id       UUID NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    person_id       UUID REFERENCES person(id) ON DELETE SET NULL,
    org_unit_id     UUID NOT NULL REFERENCES org_unit(id),
    org_unit_path   TEXT NOT NULL,   -- frozen copy of org_unit.path
    group_ids       UUID[] NOT NULL DEFAULT '{}',
    submitted_at    TIMESTAMPTZ,
    is_complete     BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (survey_id, person_id)
);
CREATE INDEX ON response_set (survey_id, org_unit_path text_pattern_ops);

CREATE TABLE answer (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_set_id  UUID NOT NULL REFERENCES response_set(id) ON DELETE CASCADE,
    question_id      UUID NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    value_bool       BOOLEAN,
    value_numeric    NUMERIC,
    value_text       TEXT,
    value_choice     TEXT[],
    UNIQUE (response_set_id, question_id)
);

-- ============================================================
-- ROLLUP CACHE
-- ============================================================

-- Precomputed aggregates, one row per (survey, question, org node).
-- Recomputed on survey close or nightly. Dashboards read ONLY this
-- table, never the raw answers — that is what makes them fast and
-- what enforces the confidentiality threshold in one place.
CREATE TABLE aggregate (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    survey_id      UUID NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    question_id    UUID NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    org_unit_id    UUID REFERENCES org_unit(id) ON DELETE CASCADE,
    org_group_id   UUID REFERENCES org_group(id) ON DELETE CASCADE,
    respondent_n   INTEGER NOT NULL,
    stats          JSONB NOT NULL,   -- {"mean":3.4,"distribution":{"1":2,...}}
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (survey_id, question_id, org_unit_id, org_group_id)
);

-- AI summaries of open text, one per (survey, question, node).
CREATE TABLE ai_summary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    survey_id       UUID NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    question_id     UUID REFERENCES question(id) ON DELETE CASCADE,
    org_unit_id     UUID REFERENCES org_unit(id) ON DELETE CASCADE,
    summary_text    TEXT NOT NULL,
    keywords        TEXT[] NOT NULL DEFAULT '{}',
    source_n        INTEGER NOT NULL,
    model_name      TEXT NOT NULL,
    is_recursive    BOOLEAN NOT NULL DEFAULT FALSE, -- summary-of-summaries
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ACCESS CONTROL
-- ============================================================

CREATE TYPE app_role AS ENUM ('member', 'club_admin', 'county_admin',
                              'state_admin', 'national_admin', 'superuser');

CREATE TABLE role_grant (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id    UUID NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    role         app_role NOT NULL,
    org_unit_id  UUID REFERENCES org_unit(id) ON DELETE CASCADE,
    org_group_id UUID REFERENCES org_group(id) ON DELETE CASCADE,
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by   UUID REFERENCES person(id)
);
```

### 3.3 The two queries that matter

Everything in the dashboard reduces to these. Get them working on day one of Phase 1.

**Subtree — "every org unit at or below this node":**

```sql
WITH RECURSIVE subtree AS (
    SELECT id, parent_id, level, name, path
      FROM org_unit WHERE id = $1
    UNION ALL
    SELECT o.id, o.parent_id, o.level, o.name, o.path
      FROM org_unit o JOIN subtree s ON o.parent_id = s.id
)
SELECT * FROM subtree;
```

Or, with the `path` column, the same result as one indexed scan:

```sql
SELECT * FROM org_unit
 WHERE path = $1 OR path LIKE $1 || '.%';
```

**Rollup — "distribution of answers to an ordinal question, for a node and everything under it":**

```sql
SELECT a.value_numeric AS score, COUNT(*) AS n
  FROM answer a
  JOIN response_set rs ON rs.id = a.response_set_id
 WHERE a.question_id = $1
   AND (rs.org_unit_path = $2 OR rs.org_unit_path LIKE $2 || '.%')
   AND rs.is_complete
 GROUP BY 1 ORDER BY 1;
```

Note that this uses the *frozen* `org_unit_path` on the response, not a live join to `org_unit`. That's intentional: a response filed by the Goleta club in March should stay attributed to Goleta even if the club is later reorganized into a different county.

---

## 4. System architecture

Five layers, each with a clean boundary. Build them in this order.

```
┌──────────────────────────────────────────────────┐
│  5. Dashboard (React/Next.js or Streamlit)       │
│     role-gated views, charts, maps               │
└───────────────────┬──────────────────────────────┘
                    │ REST/JSON
┌───────────────────┴──────────────────────────────┐
│  4. API (FastAPI)                                │
│     auth, RBAC scope resolution, CRUD, reports   │
└───────────────────┬──────────────────────────────┘
                    │
┌───────────────────┴──────────────────────────────┐
│  3. Background workers (Celery / APScheduler)    │
│     rollup jobs, survey open/close, AI summaries │
└───────────────────┬──────────────────────────────┘
                    │
┌───────────────────┴──────────────────────────────┐
│  2. Domain layer (SQLAlchemy models + services)  │
│     hierarchy ops, aggregation, permission rules │
└───────────────────┬──────────────────────────────┘
                    │
┌───────────────────┴──────────────────────────────┐
│  1. PostgreSQL                                   │
│     relational core + JSONB for flexible fields  │
└──────────────────────────────────────────────────┘
```

**Recommended stack for your skill level:**

| Layer | Choice | Why this one |
|---|---|---|
| Database | PostgreSQL 16 | JSONB, arrays, CTEs, `ltree`, partial indexes — you need all of them. SQLite for local dev only. |
| ORM | SQLAlchemy 2.0 + Alembic | The 2.0 typed API is a real improvement. Alembic gives you versioned migrations, which you will need the first time you change the schema in production. |
| API | FastAPI + Pydantic v2 | Async, auto-generated OpenAPI docs, validation for free. The docs page alone is worth it when you're demoing to a committee. |
| Auth | `fastapi-users` or Authlib + JWT | Don't hand-roll password hashing. Keycloak is the "correct" answer at scale but is a heavy lift solo. |
| Background jobs | APScheduler (v1) → Celery + Redis (v2) | APScheduler is in-process and takes ten minutes to set up. Move to Celery only when jobs get long or need retries. |
| Dashboard | Streamlit (v1) → Next.js + Recharts (v2) | See §8. |
| Hosting | Railway / Render / Fly.io | Managed Postgres + container deploy, roughly $10–25/month. Cheaper than your time. |
| Testing | pytest + `pytest-postgresql` or testcontainers | Test the rollup logic against a real Postgres, not SQLite — the SQL differs. |

---

## 5. Phase plan overview

| Phase | Focus | Duration | Exit criterion |
|---|---|---|---|
| 0 | Environment, repo, needs assessment | 1–2 weeks | 3+ clubs confirm what reports they'd actually file |
| 1 | Data model + hierarchy | 2–3 weeks | Can import a real county's clubs and query any subtree |
| 2 | API and auth | 2–3 weeks | Authenticated CRUD, RBAC enforced in tests |
| 3 | Surveys and responses | 3–4 weeks | A real club completes a real monthly report |
| 4 | Aggregation and rollup | 2–3 weeks | County chair sees correct numbers across 5 clubs |
| 5 | Dashboard | 3–4 weeks | Non-technical chair uses it without you present |
| 6 | AI summarization | 1–2 weeks | Open-text summaries at club, county, state level |
| 7 | Pilot | 6–8 weeks | One full monthly cycle with 5–10 clubs |

Total to pilot-ready: roughly **4–6 months part-time**. Treat any estimate under three months as optimistic.

---

## 6. Phase-by-phase detail

### Phase 0 — Foundation and needs assessment (1–2 weeks)

The most common failure mode for this kind of project is building the survey system nobody fills in. Spend two weeks preventing that.

**Steps**

1. Interview 3–5 club officers. Ask specifically: *what do you already report to the county, how, and how long does it take?* You are looking to replace existing pain, not add a new obligation.
2. Collect the actual artifacts — the emails, the spreadsheets, the paper forms. Your v1 monthly report should be a near-copy of what they already fill in.
3. Write down the **10–15 questions** for the monthly club health report. Membership count, meetings held, attendance, officer vacancies, funds raised, volunteer hours, one open-text "anything leadership should know."
4. Confirm your test hierarchy: one state → one county → 5–10 real clubs, with real names and real people counts.

**Technical setup**

```bash
mkdir demosense && cd demosense
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn[standard] sqlalchemy alembic psycopg[binary] \
            pydantic-settings python-dotenv pytest ruff
git init
docker run --name demosense-db -e POSTGRES_PASSWORD=dev \
       -p 5432:5432 -d postgres:16
```

Repository layout — adopt this now, not later:

```
demosense/
├── alembic/                  # migrations
├── src/demosense/
│   ├── models/               # SQLAlchemy ORM classes
│   ├── schemas/              # Pydantic request/response models
│   ├── services/             # business logic (hierarchy, rollup, rbac)
│   ├── api/routers/          # FastAPI route modules
│   ├── workers/              # scheduled jobs
│   ├── config.py
│   └── db.py
├── tests/
├── scripts/                  # data import, seeding
└── pyproject.toml
```

The `services/` directory is the one that matters. Business logic goes there, never in the route handlers. When you later swap Streamlit for React, or add a mobile client, the services are what you reuse.

**Deliverable:** repo, running local Postgres, a written one-page spec of the monthly report questions.

---

### Phase 1 — Data model and hierarchy (2–3 weeks)

**Steps**

1. Write the SQLAlchemy models for §3.2. Start with `org_unit`, `org_group`, `person`, `position_type`, `membership`. Leave surveys for Phase 3.
2. `alembic init alembic`, configure it against your models, generate and apply the first migration. Verify you can roll back.
3. Write a trigger or a service-layer hook that maintains `org_unit.path` on insert and on parent change. Test the reparenting case explicitly — it's the one that breaks.
4. Implement `services/hierarchy.py`:
   - `get_subtree(org_unit_id) -> list[OrgUnit]`
   - `get_ancestors(org_unit_id) -> list[OrgUnit]`
   - `get_active_members(org_unit_id, include_descendants: bool)`
   - `move_unit(unit_id, new_parent_id)` — must rewrite paths for the whole subtree
5. Write a seed script that loads your real test county from a CSV. Real data, not `foo`/`bar`.
6. Write tests for: subtree correctness, the "no two active memberships" constraint, the "club XOR group" check constraint, and reparenting path rewrites.

**Common mistakes to avoid**

- Storing `position` as free text. Use `position_type`.
- Deleting memberships when someone leaves. Set `end_date`.
- Making `parent_id` nullable everywhere without the `CHECK` that only the national node is a root — you'll silently end up with orphan trees.
- Forgetting that a person's *home* club and their *memberships* are different facts.

**Deliverable:** you can run `get_subtree(county_id)` on real data and get the right clubs back, and `get_active_members(county_id, include_descendants=True)` returns the right people.

---

### Phase 2 — API and access control (2–3 weeks)

**Steps**

1. Scaffold FastAPI with routers for `/org-units`, `/groups`, `/people`, `/memberships`.
2. Add authentication. `fastapi-users` gives you registration, login, password reset, and JWT in an afternoon. Do not write your own.
3. Build `services/rbac.py`. The central function is a **scope resolver**:

```python
def visible_org_units(person: Person, session: Session) -> set[UUID]:
    """Every org unit this person may read data for."""
    scope: set[UUID] = set()
    for grant in active_role_grants(person, session):
        if grant.role == AppRole.SUPERUSER:
            return ALL_UNITS
        if grant.org_unit_id:
            scope |= {u.id for u in get_subtree(grant.org_unit_id, session)}
    return scope
```

Every read endpoint filters against this set. Every one. Make it a FastAPI dependency so it is impossible to forget:

```python
@router.get("/org-units/{unit_id}/members")
def list_members(
    unit_id: UUID,
    scope: set[UUID] = Depends(require_read_scope),
    session: Session = Depends(get_session),
):
    if unit_id not in scope:
        raise HTTPException(403)
    ...
```

4. Write RBAC tests as the *first* tests, not the last. Specifically: a county admin in County A must get a 403 on County B's members. If that test doesn't exist, assume the bug exists.
5. Add audit logging on writes — who changed what membership, when. Political organizations will ask.

**Deliverable:** OpenAPI docs at `/docs` where a logged-in county admin can browse their county and is blocked from every other.

---

### Phase 3 — Surveys and responses (3–4 weeks)

**Steps**

1. Add the survey tables from §3.2.
2. Build the survey definition API. A survey is a title, a target org node, a window, and an ordered list of questions with a `kind` and a JSONB `config`.
3. Build response capture. Two rules:
   - **Save partial responses.** A club secretary filling a 15-question report on a phone will be interrupted. `is_complete` exists for this.
   - **Freeze the org tags at submission time** into `response_set.org_unit_path`.
4. Validate answers against `question.kind` server-side. An ordinal question with `config = {"min":1,"max":5}` must reject a 7. Pydantic discriminated unions handle this cleanly.
5. Build the recurring monthly report: a survey with `is_recurring = true` and an RRULE, plus a scheduler job that instantiates a new cycle each month and notifies club officers.
6. **Build the response form itself last and cheaply.** A plain server-rendered HTML form (Jinja2) is fine for the pilot. Do not build a drag-and-drop survey builder — you have 15 questions and you control them.

**Deliverable:** a real club officer completes a real monthly report end-to-end, on a phone, without you talking them through it.

---

### Phase 4 — Aggregation and rollup (2–3 weeks)

This is the heart of the system and the part that most resembles real engineering.

**Steps**

1. Write `services/rollup.py` with one function per question kind:
   - boolean → yes/no counts and percentage
   - ordinal / numeric → n, mean, median, full distribution
   - choice → counts per option
   - text → deferred to Phase 6
2. Compute **bottom-up**. For each survey, walk the org tree depth-first from the leaves; each node's aggregate is the combination of its own responses plus its children's aggregates. For means, store the sum and the count in `stats` so parents can combine children correctly — you cannot average averages of unequal groups.
3. Compute cross-cutting group aggregates in a second, independent pass keyed on `response_set.group_ids`.
4. **Enforce the confidentiality threshold in the rollup, not the UI.** If `respondent_n < 5`, write the aggregate row but flag it; the API refuses to return open text or fine-grained distributions below threshold. Doing this in the UI means the raw data is still one API call away.
5. Trigger the job on survey close and nightly for continuous reports.
6. Test with a hand-built fixture: 3 clubs, 12 responses, numbers you computed by hand. Assert the county total exactly.

**Deliverable:** a county chair's aggregate row is provably equal to the sum of the club rows beneath it.

---

### Phase 5 — Dashboard (3–4 weeks)

**Steps**

1. Decide the reader. County and club chairs are volunteers, often not young, often on a phone. Design for one screen, big type, no training required.
2. Build the four views that cover 90% of use:
   - **Org browser** — tree navigation, click into any unit you're scoped to
   - **Club health** — this month's numbers, plus a 12-month trend line
   - **Survey results** — per-question charts, filterable by level, with the response rate shown prominently
   - **Roster** — members and officers, with vacant offices highlighted
3. Show **response rate everywhere**. A 40% response rate changes how you read the number, and hiding it is how dashboards mislead.
4. Add the map only after the charts work. Color-coded county maps are the most requested and least important feature; a choropleth over 5 pilot clubs communicates nothing.
5. Every view reads from `aggregate`, never from `answer`.

**Streamlit vs. a real frontend.** Streamlit gets you a working, chart-rich dashboard in Python in a few days, with no JavaScript. Its limits are real: awkward multi-user auth, full-script reruns, and a look that says "internal tool." For a pilot with 10 clubs, that is a fine trade. Plan to rewrite in Next.js if the pilot succeeds — and because your logic lives in `services/`, that rewrite touches only the presentation layer.

**Deliverable:** a chair you have never met logs in and finds their club's numbers without a phone call.

---

### Phase 6 — AI summarization (1–2 weeks)

Deliberately last. It is the flashiest part and the least load-bearing; if the hierarchy and rollups are wrong, good summaries of wrong data are worse than nothing.

**Steps**

1. Batch open-text answers per (survey, question, org node).
2. Summarize the leaves first, then generate **summaries-of-summaries** upward. A county summary takes the club summaries as input, not the raw text. This is what keeps the token cost linear rather than quadratic as you scale.
3. Extract keywords and a coarse sentiment or theme label in the same call, returned as JSON, so you get charts from text.
4. Store everything in `ai_summary` with the model name and generation timestamp — you will change models and need to know which output came from where.
5. Enforce the same minimum-respondent threshold. Never summarize open text from two people; the summary de-anonymizes them.
6. Always link the summary to the raw responses *for users authorized to see them*. Unverifiable AI summaries erode trust fast in a political organization.

The overview document's guidance here is sound: use a hosted API during pilot when volume is trivial, and revisit self-hosting only if monthly token spend becomes a real line item. At 10 clubs it will be a few dollars a month. Don't stand up GPU infrastructure to solve a $5 problem.

---

### Phase 7 — Pilot (6–8 weeks)

1. Recruit 5–10 clubs in one county. One county, not several — you want the rollup exercised, not spread thin.
2. Run **one full monthly cycle** before changing anything. Resist mid-cycle fixes unless something is broken.
3. Instrument: response rate per club, time-to-complete, drop-off point per question, dashboard logins per chair.
4. Close the loop visibly. Publish what leadership did with the reports. The DemoSense overview is right that this is the single biggest driver of sustained response rates — participation has to visibly pay off.
5. Debrief every club officer individually. The ones who *didn't* file are the important interviews.

---

## 7. Where Lovable and AI-assisted coding fit

You mentioned Lovable and learning new tools. Be strategic about it — these tools have a sharp competence boundary.

**Good uses**

- **Dashboard and form UI.** Lovable, v0, or Bolt are genuinely fast at React + Tailwind screens. Point them at your OpenAPI spec and let them build the client. This is the single highest-leverage use.
- **Prototype throwaways** for a committee demo, three weeks before the real thing exists.
- **Boilerplate** — Pydantic schemas from your SQLAlchemy models, CRUD routers, seed scripts.
- **Test generation** from a written specification of the rollup rules.

**Bad uses**

- **The schema.** Generated schemas tend toward flat tables, free-text enums, and no history. Your sketch is already better than what a prompt will produce.
- **The rollup logic.** Combining aggregates correctly across a tree, with confidentiality thresholds, is subtle and quietly wrong when generated. Write and test it yourself.
- **Permissions.** Never generate authorization code you don't fully understand. This system holds political affiliation data on real people.
- **Migrations.** Alembic files touch production data. Read every line.

**The rule of thumb:** generate the parts where being wrong is *visible* (UI, boilerplate). Hand-write the parts where being wrong is *invisible* (aggregation, access control, schema). A misaligned button is obvious; a county rollup that double-counts members who belong to two clubs will go unnoticed for months and then destroy your credibility in a single meeting.

A pragmatic split: build the FastAPI backend by hand as your learning project, and use Lovable for the dashboard frontend against your documented API.

---

## 8. Skills roadmap

Sequenced against the phases, so you learn each thing just before you need it.

| When | Skill | Concretely |
|---|---|---|
| Phase 0–1 | SQL beyond `SELECT` | CTEs, window functions, `GROUP BY` with `FILTER`, partial indexes |
| Phase 1 | SQLAlchemy 2.0 ORM | Typed `Mapped[]` declarative style, relationships, `selectinload` to avoid N+1 |
| Phase 1 | Alembic | Autogenerate, review, downgrade. Practice a rollback before you need one. |
| Phase 2 | FastAPI dependencies | `Depends`, dependency overrides in tests, `Annotated` types |
| Phase 2 | Auth fundamentals | JWT structure, refresh tokens, password hashing, why not to roll your own |
| Phase 2–4 | pytest | Fixtures, factories (`factory_boy` / `polyfactory`), parametrization |
| Phase 4 | Data aggregation | Combining means and variances across groups; streaming aggregation |
| Phase 5 | Streamlit, then React | Streamlit for the pilot; React + Recharts (or Lovable) for v2 |
| Phase 6 | LLM API basics | Structured JSON output, batching, token budgeting, prompt versioning |
| Throughout | Docker + CI | `docker-compose` for local Postgres; GitHub Actions running `pytest` on push |

Two habits worth forming now: **write the test before the rollup function**, and **never merge a schema change without a migration**. Both will save you weeks.

---

## 9. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Nobody fills in the reports | High | Fatal | Phase 0 needs assessment; replace an existing chore rather than adding one; close the loop visibly |
| Scope creep into wiki/CMS/social layer | Very high | Severe | The scope table in §1 is a contract. Everything else is v2. |
| Schema rewrite mid-build | Medium | Severe | Spend the full 2–3 weeks on Phase 1. Model the hierarchy properly the first time. |
| Data sensitivity incident | Low | Severe | Party affiliation is sensitive personal data. Encrypt at rest, TLS everywhere, minimum-respondent thresholds, audit logs, documented retention policy. |
| Volunteer burnout (yours) | High | Severe | Phased plan with shippable milestones; recruit one collaborator by Phase 3 |
| Chairs won't use a dashboard | Medium | Moderate | Email/PDF digest as the fallback delivery channel — meet them where they are |
| AI summaries distrusted | Medium | Moderate | Always show source count and link to raw responses; publish your prompts |
| Bus factor of one | High | Severe | Public repo, written docs, standard stack, no clever tricks |

---

## 10. Definition of done for v1

The system is pilot-complete when all of the following are true:

1. A real county's clubs, members, and officers are loaded and queryable.
2. A club secretary can file the monthly report on a phone in under five minutes.
3. A county chair sees an accurate aggregate across all their clubs and can drill into any one.
4. A county chair provably cannot see another county's data — enforced in the API and covered by a test.
5. Open-text responses are summarized at club, county, and state level, with thresholds enforced.
6. One complete monthly cycle has run with ≥5 clubs and ≥50% response rate.
7. Another developer can clone the repo, follow the README, and have it running in under 30 minutes.

---

## Appendix A — Immediate next actions

1. **This week:** create the repo, stand up Postgres in Docker, write the `org_unit` and `membership` models from §3.2, and load your own county as real seed data.
2. **This week:** email three club officers and ask what they currently report and how long it takes.
3. **Next week:** get `get_subtree()` and `get_active_members()` working with tests.
4. **Week 3:** draft the 15-question monthly report from what those three officers tell you.
5. **Week 4:** first FastAPI endpoints and `fastapi-users` auth.

Build the spine. Everything else in the overview document hangs off it.
