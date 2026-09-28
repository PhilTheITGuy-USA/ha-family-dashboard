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

CRITICAL, live-verified via a genuinely fresh install (not assumed): HA's own `/local` static
route (serving `/config/www/`) is only registered if `hass.config.path("www")` already exists
at the moment `frontend`'s own `async_setup` runs - see that component's own source, which
does `if await hass.async_add_executor_job(os.path.isdir, local): static_paths_configs.append(
StaticPathConfig("/local", local, ...))`, checked exactly once at HA startup. On a fresh
install, `www/` doesn't exist yet at that point - THIS module creates it, but only later
(during the config flow's `avatars` step or this entry's own setup, both well after HA has
already booted). Without a fix, every `/local/family_dashboard/*` URL (avatars, background,
and critically the dashboard strategy JS - `dashboard/register.py`'s
`async_register_strategy_resource`) 404s for the rest of that HA process's life, no matter how
many files get seeded, until a manual restart - exactly the "silently needs a restart" failure
mode this whole project was rebuilt to avoid. `_ensure_local_static_path` below registers our
own dedicated static path directly instead of relying on that boot-time check, so assets are
servable immediately regardless of whether `www/` existed before HA started.

2026-07-26: this module used to ALSO vendor five third-party Lovelace cards (button-card,
bubble-card, card-mod, config-template-card, week-planner-card) here and in
`dashboard/register.py`'s resource registration, on the reasoning that bundling them avoided
requiring a separate manual HACS install. Reversed on a live-reported real risk: none of the
five vendored files guard their own `customElements.define(...)` call with an existence check
first (confirmed by reading each one directly) - a user who ALREADY has any of these five
installed separately (for their own other dashboards) would end up with both copies loaded
globally, racing to define the same custom element name, with the loser throwing an uncaught
console error and silently never taking effect. For `week-planner-card` specifically, this
integration's own calendar behavior is documented as depending on the *exact* pinned version's
internals - a user's own differently-versioned copy silently winning that race could break the
calendar in a way that has nothing to do with this integration's own code. Vendoring can't
detect or prevent that collision from our side without either modifying the third-party files
(renaming their registered tag - a real, ongoing-maintenance modification to code this project
otherwise ships unmodified) or accepting the risk. SETUP.md's Prerequisites section now lists
all five as required manual HACS installs instead - see `dashboard/register.py`'s
`async_register_strategy_resource` for what's still auto-registered (just this integration's
own strategy script).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_PACKAGE_DIR = Path(__file__).parent
_STATIC_PATH_REGISTERED_KEY = f"{DOMAIN}_local_static_path_registered"


async def _ensure_local_static_path(hass: HomeAssistant, target_dir: Path) -> None:
    """Registers `/local/family_dashboard` -> `target_dir` directly via `hass.http`, bypassing
    HA's own boot-time-only `/local` registration (see this module's docstring). Guarded by a
    `hass.data` flag to run only once per HA process - `async_register_static_paths` has no
    idempotency of its own (calling it again would just pile up a redundant duplicate route),
    and this is called on every `async_seed_assets` pass (initial wizard AND every entry
    setup/reload), not just the first.
    """
    if hass.data.get(_STATIC_PATH_REGISTERED_KEY):
        return
    hass.data[_STATIC_PATH_REGISTERED_KEY] = True
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/local/family_dashboard", str(target_dir), True)]
    )


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
    avatar_files = await hass.async_add_executor_job(_seed_sync, hass)
    target_dir = Path(hass.config.config_dir) / "www" / "family_dashboard"
    await _ensure_local_static_path(hass, target_dir)
    return avatar_files
