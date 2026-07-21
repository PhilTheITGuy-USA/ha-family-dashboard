"""Pure-Python tests for util.slugify_unique - no HA runtime needed, fastest tests here."""
import pytest

from custom_components.family_dashboard.util import (
    InvalidScheduleDaysText,
    format_schedule_days,
    parse_schedule_days_text,
    slugify_unique,
)


def test_basic_slug():
    existing: set[str] = set()
    assert slugify_unique("Ada", existing) == "ada"


def test_dedup_on_collision():
    existing: set[str] = set()
    assert slugify_unique("Sam", existing) == "sam"
    assert slugify_unique("sam!", existing) == "sam_2"
    assert slugify_unique("SAM", existing) == "sam_3"


def test_empty_name_falls_back_to_member():
    existing: set[str] = set()
    assert slugify_unique("   ", existing) == "member"


def test_parse_schedule_days_blank_means_every_day():
    assert parse_schedule_days_text("") is None
    assert parse_schedule_days_text("   ") is None
    assert parse_schedule_days_text(None) is None


def test_parse_schedule_days_full_names_and_abbreviations():
    assert parse_schedule_days_text("Monday, Wednesday, Friday") == [
        "monday",
        "wednesday",
        "friday",
    ]
    assert parse_schedule_days_text("tue, thu, sat") == ["tuesday", "thursday", "saturday"]


def test_parse_schedule_days_normalizes_order_and_dedupes():
    assert parse_schedule_days_text("Fri Mon Wed Mon") == ["monday", "wednesday", "friday"]


def test_parse_schedule_days_invalid_token_raises():
    with pytest.raises(InvalidScheduleDaysText):
        parse_schedule_days_text("Funday")


def test_format_schedule_days():
    assert format_schedule_days(None) == "Every day"
    assert format_schedule_days([]) == "Every day"
    assert format_schedule_days(["monday", "wednesday", "friday"]) == "Mon, Wed, Fri"
