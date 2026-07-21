# DemoSense — Lovable Knowledge File

Paste this into your Lovable project's **Project Settings → Knowledge**.
This project talks to a real, already-built, already-tested backend — it is
**not** a Supabase-native Lovable project. There is no Supabase anywhere in
this stack. Do not generate Supabase client code, do not generate SQL/RLS
policies, do not add a Supabase integration. Every read and write goes
through the REST API below.

## What this is

A membership and reporting dashboard for Democratic Party clubs. County and
state officers browse their org hierarchy and see aggregated survey results
(the raw survey-response-capture flow already exists and isn't part of this
build — this is the read-side dashboard).

## Backend

Base URL: `https://web-production-ec400.up.railway.app`

Full interactive API docs (every endpoint, every schema, try-it-out) are
live at `https://web-production-ec400.up.railway.app/docs` — read that first, it is the source of truth over
this document if they ever disagree.

## Auth

JWT bearer tokens, not cookies, not Supabase Auth, not sessions.

```
POST /auth/jwt/login
Content-Type: application/x-www-form-urlencoded
Body: username=<email>&password=<password>

-> 200 { "access_token": "...", "token_type": "bearer" }
```

Store the token (localStorage is fine — this API has no CSRF surface since
it's a pure bearer-token API, not cookie-based). Attach it to every
subsequent request:

```
Authorization: Bearer <access_token>
```

Token lifetime is 8 hours. On a 401, send the user back to login — do not
try to silently refresh, there is no refresh endpoint yet.

Registration: `POST /auth/register` with
`{email, password, first_name, last_name}`. New accounts get no roles and
can see nothing until a superuser grants one — that's expected, not a bug
to route around.

**Discovering the logged-in user's home node(s):** there is no
`home_org_unit` field on the user object — access comes from role grants,
not one fixed node. After login, call `GET /role-grants/me` (bearer auth,
returns only the caller's own grants) to get a list of
`{role, org_unit_id, org_group_id}`. Usually one row. Use its `org_unit_id`
as the root for the org tree browser. A superuser has zero rows in this
list but `is_superuser: true` on `GET /users/me` — treat that combination
as "start from any node, they can see everything."

**Test accounts** (already granted real roles, safe to build against):
- `demo_county_admin@democlub.dev` / `CountyDemo123!` — county_admin, scoped
  to Santa Barbara county (sees that county + its 2 clubs)
- `demo_state_admin@democlub.dev` / `StateDemo123!` — state_admin, scoped to
  California (sees the whole state, including Santa Barbara county and below)
- `rbac-test-superuser@democlub.dev` / `RbacTestSuper123!` — superuser, sees
  everything everywhere (use this to sanity-check the "no role grants but
  is_superuser" case)

## Non-negotiable rules

1. **Access control is entirely server-side.** A 403 means the logged-in
   user genuinely cannot see that data — render an appropriate empty/error
   state, never try to work around it client-side, never cache or
   reconstruct data the API refused to return.
2. **Confidentiality suppression is server-side too.** Aggregate endpoints
   return `{"stats": null, "suppressed": true, "respondent_n": <n>}` when
   fewer than 5 people answered a question at that org level. Render this
   as "not enough responses yet to show" (using `respondent_n` if you want
   to show progress toward that), and never attempt to fetch or infer the
   underlying individual answers — there is no endpoint that returns them,
   by design.
3. **Never hardcode or guess IDs.** Org units, surveys, and questions are
   all real UUIDs from the API — always fetch and pass through, never
   invent placeholder IDs during development that might leak into the
   final build.

## Endpoints this build needs

```
POST /auth/jwt/login                                # see Auth above
GET  /role-grants/me                                 # discover your own accessible org unit(s)
GET  /org-units/{unit_id}                            # one org unit
GET  /org-units/{unit_id}/subtree                     # it + every descendant (tree view)
GET  /org-units/{unit_id}/members                     # active members at/below this node
GET  /surveys                                         # list of open surveys
GET  /surveys/{survey_id}                              # full definition incl. all questions
GET  /org-units/{unit_id}/aggregates?survey_id=...     # rollup results, one row per question
```

`GET .../aggregates` response shape (one array element per question):

```json
{
  "question_id": "uuid",
  "respondent_n": 5,
  "stats": {
    "n": 5, "sum": 18.0, "mean": 3.6, "median": 4.0,
    "distribution": {"2.0": 1, "3.0": 1, "4.0": 2, "5.0": 1}
  },
  "suppressed": false,
  "computed_at": "2026-07-21T18:08:39Z"
}
```

`stats` shape depends on the matching question's `kind` (from
`GET /surveys/{id}`):
- `ordinal` / `numeric` → `{n, sum, mean, median, distribution}` (distribution
  keys are stringified numbers — good for a bar/histogram chart)
- `boolean` → `{n, true_n, false_n, true_pct}`
- `single_choice` / `multi_choice` → `{n, counts: {"option": count, ...}}`
- `text` questions never have an aggregate row (free-text rollup isn't built
  yet) — skip them when rendering survey results

## Scope for this build

Two views only. Don't build more than this — a smaller number of clean
screens beats a partial fourth one.

1. **Org tree browser** — after login, call `GET /role-grants/me` to find the
   user's accessible org unit(s), then `GET /org-units/{id}/subtree` from
   there to render the hierarchy. Click into a node to see its members
   (`GET /org-units/{id}/members`) and jump to survey results for that node.
2. **Survey results** — pick an open survey (`GET /surveys`), pick an org
   node, show one chart per question using `GET /org-units/{id}/aggregates`:
   bar/histogram for ordinal & numeric, pie/bar for choice questions,
   simple stat tiles for boolean. Show `respondent_n` prominently everywhere
   — a low response count changes how a number should be read.

Explicitly **not** in scope for this build: a club-health trend line (no
historical rollup snapshots exist yet to trend against), a roster
create/edit UI, maps, and anything from the org overview beyond these two
survey/org views (wiki, social layer, opposition monitoring, etc. — deferred
by the project's own plan).

## Tech

React + TypeScript + Tailwind + shadcn/ui, Recharts for charts — Lovable's
normal default stack minus the Supabase pieces. Mobile-first: club and
county officers read this on their phones.
