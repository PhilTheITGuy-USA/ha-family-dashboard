"""Seeds static assets (default avatar images, the background image, the theme YAML) from
this integration's own package directory into `/config/` on entry setup - the "ship it with
the integration, copy on first run" pattern the 2026-07-13 feature audit calls for (avatars/
theme/background all need real files under `/config/www/`|`/config/themes/` to be usable,
since neither HA's frontend nor `folder`-style file scanning can read files bundled inside a
custom component's own package directory directly).

Idempotent per-file, not per-run: the theme is integration-owned styling, so it's always
re-copied (keeps it in sync if the shipped theme changes between versions); avatars and the
background image are user-customizable content once seeded (Phillip might add/replace photos),
so those are only copied if the destination doesn't exist yet - never overwritten.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

_PACKAGE_DIR = Path(__file__).parent


def _seed_sync(hass: HomeAssistant) -> list[str]:
    config_dir = Path(hass.config.config_dir)

    avatars_dest = config_dir / "www" / "family_dashboard" / "avatars"
    avatars_dest.mkdir(parents=True, exist_ok=True)
    for src in (_PACKAGE_DIR / "www" / "avatars").glob("*.png"):
        dest = avatars_dest / src.name
        if not dest.exists():
            shutil.copyfile(src, dest)

    background_dest = config_dir / "www" / "family_dashboard" / "background.png"
    background_src = _PACKAGE_DIR / "www" / "background.png"
    if background_src.is_file() and not background_dest.exists():
        background_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(background_src, background_dest)

    theme_dest = config_dir / "themes" / "family_dashboard.yaml"
    theme_src = _PACKAGE_DIR / "themes" / "family_dashboard.yaml"
    if theme_src.is_file():
        theme_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(theme_src, theme_dest)

    # Integration-owned code, not user content - always re-copied (like the theme) so a
    # shipped fix/update to the strategy's filtering logic actually takes effect on the next
    # restart rather than being silently stuck on whatever copy happened to exist already.
    strategy_dest = config_dir / "www" / "family_dashboard" / "family-dashboard-strategy.js"
    strategy_src = _PACKAGE_DIR / "www" / "family-dashboard-strategy.js"
    if strategy_src.is_file():
        strategy_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(strategy_src, strategy_dest)

    return [f"/local/family_dashboard/avatars/{f.name}" for f in sorted(avatars_dest.glob("*.png"))]


async def async_seed_assets(hass: HomeAssistant) -> list[str]:
    """Returns the avatar file list computed during THIS seeding pass, synchronously
    available before any platform is forwarded - a deterministic fallback for
    `modules/settings/select.py`'s `RosterAvatarSelect`, which otherwise has no guaranteed-safe
    way to read `sensor.family_dashboard_avatars`' live state at entity-construction time
    (platform setup order/concurrency between "select" and "sensor" isn't guaranteed, so a
    freshly-constructed select entity could race the avatars sensor's own first poll - found
    live, not assumed, via a real `pytest` run that flaked between passing and failing
    depending on that race).
    """
    return await hass.async_add_executor_job(_seed_sync, hass)
