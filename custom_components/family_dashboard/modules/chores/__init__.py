"""Chores & Rewards module - STUB, not yet implemented.

To build (in-house, NOT a ChoreOps/KidsChores dependency - see
`project_choreops_kidschores_successor` memory / the rebuild plan's positioning section for
why: this is intentionally simpler than ChoreOps, individual + shared chores, points,
approve/deny with a required reason, no rotation logic/badges/XP/ranks/quests):
- `sensor` entities: one per roster member for points total, plus per-chore state.
- `button` entities: Claim (per chore) / Redeem (per reward) for kids, Approve / Deny for
  the parent-facing flow - port the good ideas from `ha-family-hub`'s Parent Review tab
  (per-kid picker, required deny reason logged to the Logbook) but as entities/services
  this integration owns directly, not YAML scripts + input_booleans.
- Parent PIN / parent-mode gating: same UI-lock concept as v1's `family_hub_parent.yaml`,
  but as this module's own `binary_sensor`/`text`/`button` entities with RestoreEntity for
  the PIN, not an `input_boolean`/`input_text` YAML package.
- Add top-level `sensor.py`/`button.py` shims once real entities exist, replacing the stubs
  at `custom_components/family_dashboard/sensor.py` / `button.py` today (see
  modules/settings/ for the shim pattern).
"""
