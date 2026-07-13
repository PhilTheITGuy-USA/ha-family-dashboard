"""Small shared helpers used across Family Dashboard's modules."""
from __future__ import annotations

import re


def slugify_unique(name: str, existing: set[str]) -> str:
    """Turn a display name into a stable, unique snake_case id.

    Used once, at wizard-submit time, to generate each roster member's permanent
    `member_id`. This id does NOT change later even if the member's display name is edited
    afterward via the Settings dashboard - the editable name lives in a separate `text`
    entity's state, while `member_id` backs every entity's `unique_id` for that member
    across every module (Settings, and eventually Calendar/Lists/Chores). `unique_id` must
    stay stable for HA's entity registry to keep treating it as the same entity after a
    rename - regenerating it from the (now-changed) name would silently orphan the old
    entity and create a new one.

    `existing` is mutated in place (the caller's dedup set) so repeated calls in a loop
    correctly avoid collisions across the whole roster.
    """
    base = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "member"
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}_{n}"
        n += 1
    existing.add(slug)
    return slug
