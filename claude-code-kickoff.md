# Family Dashboard — Claude Code Kickoff

Paste this whole file as your first message to Claude Code in `C:\ha-test-bench` (or tell it
to read this file first). It has no memory of the planning conversation that produced this
project, so treat it as a stranger who needs full context, not a reminder.

## Read first, in this order

All four live in `C:\Users\philt\CLAUDE_FOLDER\Family Dashboard Mockups`:

1. `family-dashboard-claude-code-brief.md` — the concrete build order. Start here for "what
   to do."
2. `family-hub-v2-rebuild-plan.md` — full architecture and the reasoning behind every
   decision in the brief. Read this before questioning or second-guessing anything the brief
   says — the "why" is almost always already answered in here.
3. `family-dashboard-setup-flow.mermaid` — the setup wizard's exact step sequence as a
   flowchart, including the per-member features screen, the optional HA-user-link step, and
   the calendar/lists/chores sub-flows.
4. The mockup screenshots (`Calendar.png`, `Lists.png`, `Chores - 1.png`, `Settings - 1.png`,
   `Settings - Change parent PIN.png`, `Add Member.png`, `Parent Review - 1.png`,
   `Parent Review - 2.png`, `Parent view is unlocked.png`,
   `Switch to Parent View(Parent Unlock).png`) and the `Code Mockup/` folder (a Figma-exported
   React/Vite/Tailwind/shadcn app implementing the dashboard UI) are reference material for
   the **later** Lovelace-card port of the dashboard. They are not part of the build order
   below — don't start on the dashboard's visual design yet, just be aware they exist for
   when that work comes up.

## Where the code lives

The scaffolded integration (Settings/Roster module fully implemented, Calendar/Lists/Chores
stubbed out, tests, manifest, HACS metadata) is at:
`C:\Users\philt\CLAUDE_FOLDER\REPO\family-dashboard`

Copy it into this working folder (`C:\ha-test-bench`) as the real repo you'll build in from
here on — keep its git history if it has any, initialize a repo if it doesn't. Do this
before writing any new code.

## Your build order

Follow `family-dashboard-claude-code-brief.md`'s "Build order" section exactly, step 0
through step 8, in sequence. A few things worth restating up front because they're hard-won
lessons from this project's first attempt (a prior installer wizard shipped 13/13 passing
automated tests and still failed its actual first real-world install — nothing got created,
the dashboard never registered):

- **Step 0 first, don't skip it.** The scaffolded config flow and `const.py` are
  HOUSEHOLD-WIDE — one shared Calendar/Lists/Chores toggle for the whole family. That's the
  wrong shape now: Calendar, Lists, and Chores & Rewards all need to be selected PER ROSTER
  MEMBER (reason: siblings shouldn't be able to touch each other's lists). Don't build steps
  2-5 on top of the current scaffold as-is — rework it first.
- Write step 0's config-flow step handlers as shared functions or a mixin from the start, not
  methods only `FamilyDashboardConfigFlow` can call. Step 6b's real Options Flow reuses them
  — building the same forms twice is wasted work.
- **A real Options Flow (step 6b) is required for v1, not deferred.** Today's scaffold has a
  placeholder whose own docstring admits it doesn't support reconfiguring anything after
  initial setup. That's the same "pointless wizard" failure that started this whole rebuild —
  don't let it slip through again.
- Disabling a feature for someone through the Options Flow must HIDE that person's entities
  (`hidden_by` in the entity registry), never delete them. Actually removing someone's data
  is a separate, deliberately not-yet-built action — don't make it an accidental side effect
  of unchecking a box.
- Step 5's dashboard generation produces MULTIPLE views: one unrestricted "Everyone" view
  (for the wall-mounted Kiosk, which isn't logged in as any one person) plus one
  Visibility-restricted view per roster member who's linked to an HA user account — not one
  flat view for the whole household.
- No static YAML packages, no assuming a restart makes anything appear. Every entity the
  wizard creates must be a real, live entity created by this integration's own entity
  platforms inside `async_setup_entry`.

Commit at each step boundary as you go, same as last time.

## Mandatory: live-instance validation

Passing the automated pytest suite is necessary but explicitly NOT sufficient — the brief's
"Mandatory: live-instance validation" section is a hard requirement before ANY module gets
called done. There's a live Home Assistant Demo container already running via Docker Desktop
for exactly this purpose — use it for real, don't just simulate it in pytest fixtures.

You'll need two things from me before you can drive it via the API:

1. The container's local URL (its Docker Desktop port mapping — ask me if you can't work it
   out yourself).
2. A Long-Lived Access Token. I have to log into that instance's web UI myself (Profile ->
   Long-Lived Access Tokens -> Create Token) since that step can't be done headlessly. Ask me
   for it and I'll generate one and hand it to you, or tell me exactly where to save it (e.g.
   a gitignored `dev.env` at the repo root) and I'll do that myself.

You'll also want a second, non-admin HA user created in that same instance (Settings ->
People -> Users) to actually validate per-person dashboard view visibility — the brief calls
this out explicitly, since "the config saved successfully" is not the same as "a non-admin
user genuinely only sees their own view."

## What to flag back to me — don't guess

- How deep the Chores & Rewards module should go beyond individual chores/points/repeat-add
  entry/approve-deny-with-reason (full parity with the old `ha-family-hub`'s Parent Review
  flow, or trimmed further). The brief calls this out as an open decision — surface it when
  you get there instead of picking one silently.
- Anything where the brief and the rebuild plan seem to disagree with each other, or where
  the scaffold doesn't match either doc — tell me rather than resolving it yourself.

## One standing preference

If you ever need me to run something in Windows Terminal myself, give it to me as a single
line — I type these by hand, and multi-line or continuation-character commands don't work
well for me there. Doesn't apply to anything you run in your own shell.
