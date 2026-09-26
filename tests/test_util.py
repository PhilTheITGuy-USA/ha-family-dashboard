"""Pure-Python tests for util.slugify_unique - no HA runtime needed, fastest tests here."""
from custom_components.family_dashboard.util import slugify_unique


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
