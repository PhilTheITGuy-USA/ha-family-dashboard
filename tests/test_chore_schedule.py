"""Pure tests for `modules/chores/schedule.py` - the date rules and picker-token format every
other part of chore scheduling builds on. No `hass` fixture needed."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.family_dashboard.modules.chores import schedule as s


def W(*days):
    return {"repeat": "days_of_week", "schedule_days": list(days)}


def M(*days):
    return {"repeat": "monthly", "month_days": list(days)}


ONE = {"repeat": "one_time"}


def test_days_of_week_empty_means_every_day():
    assert all(s.is_due(W(), date(2026, 9, d)) for d in range(21, 28))


def test_days_of_week_only_picked_days():
    c = W("monday", "thursday")
    assert s.is_due(c, date(2026, 9, 21))  # Monday
    assert s.is_due(c, date(2026, 9, 24))  # Thursday
    assert not s.is_due(c, date(2026, 9, 22))


def test_monthly_31st_falls_on_last_day():
    c = M(31)
    assert s.is_due(c, date(2026, 4, 30))
    assert not s.is_due(c, date(2026, 4, 29))
    assert s.is_due(c, date(2026, 2, 28))
    assert s.is_due(c, date(2028, 2, 29))
    assert not s.is_due(c, date(2028, 2, 28))


def test_monthly_30_and_31_one_instance_in_short_month():
    c = M(30, 31)
    assert [d for d in range(1, 31) if s.is_due(c, date(2026, 4, d))] == [30]


def test_one_time_always_due_never_restarts():
    assert s.is_due(ONE, date(2026, 1, 1))
    assert not s.due_day_started_since(ONE, date(2026, 1, 1), date(2027, 1, 1))


def test_due_day_started_since():
    c = W("monday", "thursday")
    mon, tue, thu = date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 24)
    assert not s.due_day_started_since(c, mon, mon)
    assert not s.due_day_started_since(c, mon, tue)
    assert s.due_day_started_since(c, mon, thu)
    # A 31+ day gap always contains a due day for a recurring chore.
    assert s.due_day_started_since(M(15), date(2026, 1, 16), date(2026, 3, 1))


def test_due_day_started_since_monthly_short_gap():
    c = M(1, 15)
    assert not s.due_day_started_since(c, date(2026, 9, 1), date(2026, 9, 14))
    assert s.due_day_started_since(c, date(2026, 9, 1), date(2026, 9, 15))


def test_describe():
    assert s.describe(W()) == "Every day"
    assert s.describe(W("monday", "thursday")) == "Mon, Thu"
    assert s.describe(M(1, 15)) == "Monthly: 1, 15"
    assert s.describe(ONE) == "One-time"


def test_toggle_token_sorts_and_dedupes():
    assert s.toggle_token("days_of_week", "thu", "mon") == "mon,thu"
    assert s.toggle_token("days_of_week", "mon,thu", "mon") == "thu"
    assert s.toggle_token("monthly", "15", "1") == "1,15"
    assert s.toggle_token("monthly", "1,15", "15") == "1"


def test_toggle_token_rejects_wrong_kind():
    with pytest.raises(ValueError):
        s.toggle_token("monthly", "", "mon")
    with pytest.raises(ValueError):
        s.toggle_token("days_of_week", "", "32")
    with pytest.raises(ValueError):
        s.toggle_token("one_time", "", "mon")


def test_tokens_to_schedule_round_trip():
    assert s.tokens_to_schedule("days_of_week", "mon,thu") == {
        "repeat": "days_of_week",
        "schedule_days": ["monday", "thursday"],
    }
    assert s.tokens_to_schedule("days_of_week", "") == {"repeat": "days_of_week"}
    assert s.tokens_to_schedule("monthly", "15,1") == {"repeat": "monthly", "month_days": [1, 15]}
    assert s.tokens_to_schedule("one_time", "mon") == {"repeat": "one_time"}
    assert s.chore_to_tokens(M(1, 15)) == "1,15"
    assert s.chore_to_tokens(W("monday", "thursday")) == "mon,thu"
    assert s.chore_to_tokens(ONE) == ""


def test_tokens_to_schedule_ignores_tokens_of_the_other_kind():
    # Leftovers from before a Repeat switch must never be saved as the wrong kind.
    assert s.tokens_to_schedule("days_of_week", "mon,15") == {
        "repeat": "days_of_week",
        "schedule_days": ["monday"],
    }
    assert s.tokens_to_schedule("monthly", "mon,15") == {"repeat": "monthly", "month_days": [15]}


def test_tokens_to_schedule_monthly_needs_a_day():
    with pytest.raises(ValueError, match="at least one day"):
        s.tokens_to_schedule("monthly", "")


def test_upgrade_chore_table():
    base = {"chore_id": "t", "name": "T", "points": 1, "assigned_to": None}

    def up(**kw):
        return s.upgrade_chore({**base, **kw})

    assert up(frequency="daily") == {**base, "repeat": "days_of_week"}
    assert up(frequency="daily", schedule_days=["monday"]) == {
        **base,
        "repeat": "days_of_week",
        "schedule_days": ["monday"],
    }
    assert up(frequency="one_time") == {**base, "repeat": "one_time"}
    assert up(frequency="weekly", schedule_days=["friday"]) == {
        **base,
        "repeat": "days_of_week",
        "schedule_days": ["friday"],
    }
    assert up(frequency="weekly") == {**base, "repeat": "days_of_week", "schedule_days": ["sunday"]}
    assert up() == {**base, "repeat": "days_of_week"}
    already = {**base, "repeat": "monthly", "month_days": [3]}
    assert s.upgrade_chore(already) is already
