"""Chores & Rewards module - Family Dashboard's own `sensor`/`button`/`text`/`binary_sensor`
platforms.

Entity classes: `modules/chores/sensor.py` (`FamilyDashboardPointsSensor` per chores-opted
roster member, `FamilyDashboardTaskSensor` per chore/reward - status idle -> claimed ->
approved/denied), `modules/chores/button.py` (Claim/Approve per chore/reward, plus Lock
Parent Mode), `modules/chores/text.py` (the parent PIN), `modules/chores/binary_sensor.py`
(parent-mode gating). Deny (needs a reason), point adjustment (needs a delta), and parent-mode
unlock (needs a PIN) are entity-registered custom services
(`family_dashboard.deny_task`/`adjust_points`/`unlock_parent_mode`), not buttons - buttons
carry no parameters.

Top-level shims: `sensor.py`/`button.py`/`binary_sensor.py` are plain 1:1 re-exports.
`text.py` is NOT - it's a small aggregator, since Settings (roster names, always-on) and
Chores (parent PIN, conditional) both need the `text` platform for the same config entry,
and HA only calls one `async_setup_entry` per (entry, platform) pair. See the top-level
`text.py`'s own docstring.

The repeat-add wizard steps are `config_flow.py`'s `async_step_add_chore`/`async_step_add_reward`,
chained in after `lists` and only shown if at least one roster member selected "chores" in
`async_step_features` (Rewards has no separate feature toggle). `entry.data["chores"]`/
`["rewards"]` are top-level lists (not per-roster-member fields, unlike Calendar/Lists) -
see const.py's `CONF_CHORES`/`CONF_REWARDS` docstring for why.

`frequency` is a display label only in v1 - no once-per-day/week claim-locking scheduling,
per the rebuild plan's positioning (deliberately simpler than ChoreOps/KidsChores).
"""
