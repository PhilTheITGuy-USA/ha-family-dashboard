# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local Home Assistant test bench: a single `homeassistant/home-assistant:stable` container run via
Docker Compose, with its entire state (config, database, logs, onboarding) bind-mounted from
`./config`. It's a sandbox for testing Home Assistant configuration — automations, scripts, scenes,
blueprints, integrations — not an application codebase. Changes here are almost always edits to YAML
files that Home Assistant loads at startup or reloads live.

## Running it

```bash
docker compose up -d        # start (or restart after config changes that need a full reload)
docker compose logs -f      # tail Home Assistant logs
docker compose restart      # restart to pick up configuration.yaml changes
docker compose down         # stop
```

The UI is at http://localhost:8123. Config is edited on the host at `./config` and is live-mounted
into the container at `/config`.

There is no build, lint, or test suite in this repo — validation happens by restarting/reloading
Home Assistant and checking `config/home-assistant.log` for errors, or via the HA UI's
Developer Tools > YAML "Check Configuration" action.

## Structure

- `docker-compose.yml` — the single service definition (container name `ha-test-bench`, port 8123,
  timezone `America/New_York`).
- `config/configuration.yaml` — entry point. Pulls in `automations.yaml`, `scripts.yaml`,
  `scenes.yaml`, and merges theme files from `config/themes/` (directory doesn't exist yet — create
  it if adding themes).
- `config/automations.yaml`, `config/scripts.yaml`, `config/scenes.yaml` — currently empty. Home
  Assistant's UI-based editors (Settings > Automations/Scenes) write back to these files directly,
  so hand edits and UI edits share the same source of truth.
- `config/blueprints/` — reusable automation/script templates (currently the stock
  `homeassistant/motion_light`, `homeassistant/notify_leaving_zone`, and
  `homeassistant/confirmable_notification` blueprints).
- `config/secrets.yaml` — referenced via `!secret` from other YAML files; holds placeholder/test
  credentials only (this is a local test bench, not a production HA install).
- `config/.storage/` — Home Assistant's internal state (auth, entity/device/area registries,
  onboarding, config entries for integrations added through the UI). Treat as generated/managed by
  HA itself, not hand-edited.
- `config/home-assistant.log*`, `config/home-assistant_v2.db*` — runtime logs and the recorder
  database; useful for debugging but not source-controlled config.

Only default, built-in integrations are configured (sun, met weather, google_translate TTS,
shopping_list, radio_browser, go2rtc, backup, analytics) — there are no custom_components or
account-specific integrations set up yet.

## Working with YAML config

- After editing `automations.yaml`, `scripts.yaml`, or `scenes.yaml`, these can be hot-reloaded from
  the HA UI (Developer Tools > YAML) or via `docker compose restart` — a full container restart is
  only required for `configuration.yaml` changes or new integrations.
- `!include`, `!include_dir_merge_named`, and `!secret` are standard Home Assistant YAML tags used
  throughout `configuration.yaml`; follow existing patterns when adding new includes.
