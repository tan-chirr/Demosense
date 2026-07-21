# DemoSense — Lovable Build Guide

**Exact steps and copy-paste prompts for building the pilot on Lovable**

Companion to the DemoSense Strategic Development Plan. Read that first for the data model; this document is the keyboard-level procedure.

---

## 0. What changes when you build on Lovable

Lovable generates a **React + TypeScript + Tailwind** frontend on a **Supabase (PostgreSQL)** backend. Lovable Cloud is that backend, enabled by default on new projects, so you don't need a separate Supabase account to start.

That means most of the Python stack in the strategic plan disappears:

| Strategic plan | On Lovable |
|---|---|
| FastAPI | Supabase auto-generated REST/JS client |
| SQLAlchemy models | SQL tables you define directly |
| Alembic migrations | Supabase migrations, run by Lovable |
| `services/rbac.py` scope resolver | Postgres Row Level Security policies |
| APScheduler rollup job | Supabase Edge Function + pg_cron |
| Streamlit dashboard | React components Lovable generates |
| pytest | Manual test protocol (§7) — this is a real loss |

**What does not change:** the schema in §3.2 of the strategic plan. Supabase is Postgres. Every table, constraint, partial index, and recursive CTE transfers verbatim. That work was not wasted.

**The one thing you must internalize.** On Lovable, there is no server-side code between the browser and the database. The React app talks to Postgres directly using a public key. The *only* thing stopping a logged-in club member from reading every other county's data is a Row Level Security policy. In the Python plan, forgetting a permission check meant one endpoint leaked. Here, a missing or wrong RLS policy means the whole table is readable by anyone with an account.

Lovable will generate RLS policies for you. **You must read and test every one of them.** Section 7 is not optional.

---

## 1. Before you open Lovable

Do not start prompting until all five of these exist. Every hour here saves five later.

- [ ] **A written scope.** The v1 scope table from the strategic plan. You will paste it into the Knowledge file and it will stop you drifting into building a wiki.
- [ ] **Your 15 monthly-report questions**, final, in a text file. Each with its type (yes/no, 1–5, number, text) and exact wording.
- [ ] **Real seed data as CSV.** One county, 5–10 real clubs, ~20 real people. Columns: club name, parent county, member first/last/email, position. Real names beat `Club A` — you'll spot wrong output instantly.
- [ ] **A free Lovable account**, and decide now: use Lovable Cloud (simpler, default) or connect your own Supabase project (more control, and you keep the database if you ever leave Lovable). **Recommendation: your own Supabase project.** This is a system that may outlive the tool that built it, and connecting your own project means the data is yours from day one. Note that remixing a Lovable project requires disconnecting Supabase first.
- [ ] **A GitHub account**, connected to the project at creation. Non-negotiable. It is your escape hatch and your real version history.

---

## 2. Step 1 — Create the project and write the Knowledge file

The Knowledge file is sent with every prompt. It is the single highest-leverage thing you will write. Do it before your first build prompt.

Create a new Lovable project. Go to **Project Settings → Knowledge** and paste this, edited for your actual county:

```
# DemoSense — Project Knowledge

## What this is
A membership and reporting system for Democratic Party clubs. Clubs file a
structured monthly report; county and state officers read aggregated results.

## Users and roles
- member       — reads only their own club's data
- club_admin   — files their club's monthly report, manages their club roster
- county_admin — reads their own county and every club beneath it
- state_admin  — reads their own state and everything beneath it
- superuser    — full access

## Non-negotiable rules
1. Access is hierarchical. A user may read data for their assigned org unit
   and everything BELOW it in the tree. Never anything above, never a sibling.
2. Enforce all access in Postgres Row Level Security, never in React.
   Never rely on hiding a UI element for security.
3. Open-text responses must not be displayed when fewer than 5 people answered
   that question at that org level. Enforce in the database, not the UI.
4. Never delete a membership row. Set end_date instead. History matters.
5. Mobile-first. Club secretaries file reports on phones.

## Tech
React + TypeScript + Tailwind + shadcn/ui, Supabase (Postgres, Auth, RLS,
Edge Functions). Charts: Recharts.

## In scope for v1
Org hierarchy, cross-cutting groups, people, memberships and positions,
monthly club report, rollup aggregation, role-gated dashboard.

## Explicitly OUT of scope — do not build these
Club websites, CMS, wiki, video library, social feed, direct messaging,
canvassing app, opposition monitoring, payments, email campaigns.
If I ask for something in this list, tell me it is out of scope and ask
me to confirm before building it.

## Design
Clean, high-contrast, large tap targets. Users are volunteers, often 50+,
often on phones. No dense data tables on mobile. Always show response rate
alongside any aggregate number.
```

That last out-of-scope block is the most valuable paragraph in this document. Scope creep is the most likely way this project dies, and this makes the tool push back on you.

---

## 3. Step 2 — Plan mode before any code

Switch to **Plan mode** (also called Chat mode). It thinks without modifying your codebase, and it costs less. Send:

```
Read the Knowledge file and tell me your understanding of this project
in your own words: the users, the hierarchy rule, and the access rules.
Do not write any code. Do not create any files.

Then tell me: what are the three hardest parts of this build, and what
would you need from me to get them right?
```

Read the answer carefully. If it has misunderstood the hierarchy rule, fix that now — everything downstream depends on it. Do not proceed until this response is correct.

---

## 4. Step 3 — Build the schema (paste, don't prompt)

**Do not ask Lovable to design your schema.** Generated schemas tend toward flat tables, free-text roles, and no history. Yours is better. Give it the exact SQL.

Take the DDL from §3.2 of the strategic plan and send it as one prompt:

```
Create the database schema exactly as written below. Use this SQL verbatim.
Do not add tables, do not rename columns, do not change types, do not drop
constraints. If something will not run, tell me what and why instead of
silently changing it.

Do NOT create RLS policies yet — I will do those in a separate step.
Do NOT build any UI yet.

[paste the full DDL from strategic plan §3.2 here]
```

Then verify — this matters, because "it said it worked" is not evidence:

```
Show me the exact CREATE TABLE statements that are now in the database,
read back from the live schema, not from your memory of my prompt.
```

Compare against your source, column by column. Specifically check that these survived:

- the `exactly_one_target` CHECK on `membership`
- both partial unique indexes (`WHERE end_date IS NULL`)
- the `national_has_no_parent` CHECK on `org_unit`
- the enum types, not TEXT columns

If any were dropped, re-add them with a follow-up prompt. These constraints are what stop bad data, and once bad data exists you will never fully clean it out.

**Pin this version.** Lovable makes every edit a commit; pinning marks a known-good state you can return to.

---

## 5. Step 4 — Write the RLS policies yourself

This is the security boundary. Lovable can draft it; you must own it.

First, the helper function. This is the RLS equivalent of the `visible_org_units()` scope resolver from the Python plan. Paste it as SQL:

```sql
-- Returns every org unit the current user may read.
CREATE OR REPLACE FUNCTION visible_org_units()
RETURNS TABLE (org_unit_id UUID)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  WITH grants AS (
    SELECT rg.org_unit_id, rg.role
      FROM role_grant rg
      JOIN person p ON p.id = rg.person_id
     WHERE p.auth_user_id = auth.uid()
  ),
  roots AS (
    SELECT o.id, o.path FROM org_unit o
     WHERE o.id IN (SELECT g.org_unit_id FROM grants g)
  )
  SELECT o.id
    FROM org_unit o
    JOIN roots r ON o.path = r.path OR o.path LIKE r.path || '.%'
   UNION
  SELECT o.id FROM org_unit o
   WHERE EXISTS (SELECT 1 FROM grants WHERE role = 'superuser');
$$;
```

Note: this assumes you add an `auth_user_id UUID REFERENCES auth.users(id)` column to `person`, linking your domain table to Supabase Auth. Add it in the same prompt.

Then apply policies to every table:

```
Enable Row Level Security on ALL tables. For each table, create policies
using the visible_org_units() function I just created:

- org_unit, person, membership, response_set: SELECT allowed only where the
  row's org_unit_id is in (SELECT org_unit_id FROM visible_org_units())
- answer: SELECT allowed only via its parent response_set passing the same test
- aggregate: SELECT allowed only where org_unit_id is in visible_org_units()
- ai_summary: same, AND only where source_n >= 5
- role_grant: SELECT own rows only; INSERT/UPDATE restricted to superuser
- survey, question: SELECT allowed to any authenticated user

INSERT and UPDATE on response_set and answer: only where the row belongs to
the acting user's own club.

Default deny. Every table must have RLS enabled with no permissive fallback
policy. Show me the full text of every policy you create.
```

Read every policy it shows you. Look specifically for `USING (true)` — that is a table with no protection at all, and it is the single most common way Lovable projects leak data.

---

## 6. Step 5 — Seed data and the rollup function

**Seed first, so every screen you build has real content in it.**

```
Create a SQL seed script that inserts my org hierarchy from the CSV I'm
pasting below. Insert the national node, one state, one county, and the
clubs, setting the path column correctly at each level
(e.g. 'usa.ca.santa_barbara.goleta'). Then insert the people and their
memberships. Do not invent any data that isn't in my CSV.

[paste your CSV]
```

**Then the rollup — write this yourself.** Aggregation across a tree with a confidentiality threshold is exactly the kind of quietly-wrong logic that AI generation produces and nobody notices for six months. Paste it as SQL:

```sql
CREATE OR REPLACE FUNCTION compute_aggregates(p_survey_id UUID)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  DELETE FROM aggregate WHERE survey_id = p_survey_id;

  INSERT INTO aggregate (survey_id, question_id, org_unit_id,
                         respondent_n, stats)
  SELECT
      p_survey_id,
      q.id,
      o.id,
      COUNT(a.id),
      jsonb_build_object(
        'n',    COUNT(a.id),
        'sum',  COALESCE(SUM(a.value_numeric), 0),
        'mean', ROUND(AVG(a.value_numeric)::numeric, 2),
        'yes',  COUNT(*) FILTER (WHERE a.value_bool),
        'no',   COUNT(*) FILTER (WHERE NOT a.value_bool),
        'distribution', COALESCE(
          jsonb_object_agg(a.value_numeric, 1)
            FILTER (WHERE a.value_numeric IS NOT NULL), '{}'::jsonb)
      )
    FROM question q
    CROSS JOIN org_unit o
    LEFT JOIN response_set rs
      ON rs.survey_id = p_survey_id
     AND rs.is_complete
     AND (rs.org_unit_path = o.path OR rs.org_unit_path LIKE o.path || '.%')
    LEFT JOIN answer a
      ON a.response_set_id = rs.id AND a.question_id = q.id
   WHERE q.survey_id = p_survey_id
   GROUP BY q.id, o.id
  HAVING COUNT(a.id) > 0;
END;
$$;
```

Store `sum` and `n`, never only `mean`. You cannot average the averages of unequally-sized clubs and get the county's true mean — that error is invisible and it will embarrass you in a meeting.

Verify against arithmetic you did by hand:

```
Run compute_aggregates() for the June report and show me the aggregate rows
for question 1 at club level and at county level. Do not summarize —
show me the raw rows.
```

Check the county total equals the sum of the clubs. If it doesn't, stop and fix it. Nothing above this layer is worth building on a broken rollup.

---

## 7. Step 6 — Build the UI, one screen at a time

Now Lovable does what it's genuinely excellent at. **One screen per prompt.** Never "build the whole app."

**6a. Auth**
```
Add Supabase email/password authentication with a login page and password
reset. After login, look up the person row matching auth.uid() and load
their role_grant. Redirect to /dashboard. Do not change the database schema.
```

**6b. Org browser**
```
Build a page at /org that shows the organizational hierarchy as an
expandable tree, reading from org_unit. Each node shows name, level, and
active member count. Clicking a node goes to /org/:id.
Only show nodes returned by visible_org_units().
Mobile-first. Do not modify any other page.
```

**6c. The monthly report form** — the most important screen in the product.
```
Build a page at /report/:surveyId that renders the survey's questions from
the question table, in ordinal order, one question per screen on mobile.

Requirements:
- Save every answer to the answer table as the user moves between questions,
  so a partially completed report survives closing the browser
- Show a progress bar and "question N of M"
- Render each question by its kind: boolean as two large buttons, ordinal as
  a 1-5 button row, numeric as a number input, text as a textarea
- On first open, create the response_set row with the user's org_unit_id
  and a frozen copy of their org_unit.path
- Large tap targets, one question visible at a time on mobile

Do not modify the database schema or any other page.
```

**6d. County dashboard**
```
Build a page at /dashboard showing, for the user's org unit:
- Four metric cards: total members, response rate, officer vacancies,
  total volunteer hours
- A list of child clubs with their status (filed / missing / needs attention)
- Per-question charts using Recharts

Read ONLY from the aggregate table. Never query the answer table from
this page. Always display the response rate next to any aggregate number.
Do not modify the database schema.
```

**6e. Roster**
```
Build a page at /org/:id/members listing active memberships for that org
unit — name, position, start date — with vacant officer positions
highlighted. Filter out rows where end_date is not null.
```

After each screen: check it works, then **pin the version**. If a prompt makes things worse, roll back rather than prompting your way out — trying to fix a bad generation with more generations is how projects spiral.

---

## 8. Step 7 — Test access control by hand

You have no pytest here. This procedure replaces it, and you run it after **every** session that touches RLS or the schema.

Create four real test accounts: a member in club A, a club_admin in club A, a county_admin in county 1, and a county_admin in county 2 (a different county).

| # | Log in as | Attempt | Required result |
|---|---|---|---|
| 1 | member, club A | Open own club dashboard | Works |
| 2 | member, club A | Open club B's dashboard by editing the URL | Blocked / empty |
| 3 | club_admin, club A | File a report for club B | Rejected |
| 4 | county_admin, county 1 | View all clubs in county 1 | Works |
| 5 | county_admin, county 1 | Open county 2 by URL | Blocked / empty |
| 6 | county_admin, county 1 | View state-level dashboard | Blocked |
| 7 | any user | Open an open-text summary where only 2 people responded | Hidden |
| 8 | member | Browser console: `supabase.from('person').select('*')` | Returns only permitted rows |

**Test 8 is the one that matters most.** The URL tests only prove the UI hides things. Test 8 goes straight to the database past your entire frontend, which is exactly what a curious member will eventually do. If it returns the full table, your RLS is not working regardless of how the app looks.

Run this in an incognito window with a real second account. Do not use Lovable's preview-as-user shortcut as your only check.

---

## 9. Step 8 — AI summarization (Edge Function)

Last, as in the strategic plan.

```
Create a Supabase Edge Function called summarize-responses that:
1. Takes a survey_id and org_unit_id
2. Fetches open-text answers for that node and everything beneath it
3. If fewer than 5 responses, exits without writing anything
4. Calls the Anthropic API to produce a 3-sentence summary plus 4 keywords,
   returned as JSON
5. Writes the result to ai_summary with source_n and model_name

The API key must be stored as a Supabase secret and read only inside the
Edge Function. It must never appear in frontend code or in any table.

For county and state level, summarize the child summaries rather than the
raw text.
```

Then a scheduled trigger:
```
Add a pg_cron job that runs compute_aggregates() and then
summarize-responses nightly at 2am for every open survey.
```

The API key rule is absolute. Anything in your React bundle is public — Lovable's own security model splits exactly here, with the frontend holding only the anon key and secrets living in Edge Functions.

---

## 10. Working habits that save you

**Modes.** Plan mode to think and debug; Agent mode to build; Visual Edits for cosmetic tweaks. Using Agent mode to ask a question burns credits and risks unwanted edits.

**Say what not to touch.** Every build prompt should end with "do not modify the database schema or any other page." In a normal chat you describe what you want; in Lovable, every prompt edits a living codebase, so naming the off-limits parts is half the prompt.

**Pin after every working feature.** Roll back rather than debug-by-prompting. Many builders find redoing a step from a pinned version is faster than un-breaking it.

**Debug in Plan mode first:**
```
The county dashboard shows 0 members. Do not change any code yet.
Explain what query is running, what it returns, and what you think is wrong.
```

**Keep the Knowledge file current.** When a rule changes, update it there, not just in a chat message. It's the only thing that persists across every prompt.

**Never let it "clean up" the schema.** If Lovable proposes simplifying tables, consolidating enums, or dropping constraints — refuse. It is optimizing for generated-code tidiness, not for your data integrity.

---

## 11. Realistic expectations

| Part | How Lovable does |
|---|---|
| Auth, login, password reset | Excellent — an afternoon |
| Forms and mobile layout | Excellent |
| Dashboard charts | Very good |
| Roster and list screens | Very good |
| CRUD against your schema | Good |
| RLS policies | Drafts well, needs your review — trust nothing |
| Recursive rollup SQL | Poor. Write it yourself. |
| Schema design | Poor. You already did it better. |
| Automated tests | Not really. Use §8 manually. |

A realistic target: **auth, org browser, report form, and dashboard working on real seed data in 2–4 weekends.** That is genuinely faster than the Python route. The trade is that you own less understanding of what was built, which is why §8 exists.

---

## 12. When to leave Lovable

Sync to GitHub from day one, so this is always a real option rather than a rescue. Consider moving to a hand-maintained codebase when any of these become true:

- You're spending more time correcting generated code than describing features
- You need real automated tests (you will, once more than one county depends on this)
- You need scheduled jobs more complex than a nightly cron
- More than one developer is working on it
- The pilot succeeded and this is now infrastructure a real organization depends on

Because you own the Supabase project and the GitHub repo, that transition is a change of editor, not a rewrite. Which is the whole reason for choosing your own Supabase project back in §1.

---

## Appendix — Build order at a glance

1. Prep: scope, 15 questions, seed CSV, accounts
2. Knowledge file
3. Plan mode: confirm understanding
4. Paste schema DDL → verify it read back correctly → pin
5. `visible_org_units()` + RLS on every table → read every policy → pin
6. Seed data
7. `compute_aggregates()` → verify against hand arithmetic → pin
8. Auth → pin
9. Org browser → pin
10. Monthly report form → pin
11. Dashboard → pin
12. Roster → pin
13. Run the §8 access-control test protocol
14. Edge Function for AI summaries
15. Nightly cron
16. Re-run §8. Then pilot.
