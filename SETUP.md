# Family Dashboard — Setup & Configuration Guide

> **v0.9.0-beta.1** · One wizard. No YAML. No restart.  
> Calendar · Lists · Chores & Rewards · Settings/Roster

---

## Overview

Family Dashboard is a custom Home Assistant integration that replaces the older `ha-family-hub` and `ha-family-hub-setup` packages. It installs via HACS, provisions every entity it needs live through a single setup wizard, and generates its own dashboard automatically — no YAML to hand-edit, no restart required.

### Modules

| Module | What it does | Can be disabled? |
|---|---|---|
| **Settings / Roster** | Name, color, avatar, birthdate per family member. Always-on core. | No |
| **Calendar** | Maps each member to their own HA calendar. Adds shared Family calendar, computed Birthdays (no external integration needed), and US/Philippines Holidays auto-provisioned on first setup. Reminder notifications route to the linked phone. | Yes — per member |
| **Lists** | Per-member isolated to-do lists: To-Do, Shopping, Packing, Gift Ideas, Custom. | Yes — per member |
| **Chores & Rewards** | Points economy with claim → approve/deny flow. PIN-gated Parent Review. Shared "Unassigned" bucket for household chores with no single owner. | Yes — per member |
| **Dashboard** | Auto-generated and registered. Four tabs: Calendar / Lists / Chores / Settings. Kiosk sees all members with toggle-filter pills; individual HA users see only their own view. | No — always generated |

> **Note:** Settings/Roster is always-on core. Calendar, Lists, and Chores & Rewards are toggled per family member during the wizard — a member who does not need Chores simply never gets those entities.

---

## Prerequisites

### Home Assistant
- Home Assistant OS, Container, or Supervised — any install type
- Version 2024.8 or later recommended (`action:` syntax required)
- HACS installed — see [hacs.xyz](https://hacs.xyz) if not already set up

### Before running the wizard
- At least one calendar integration connected and producing a `calendar.*` entity (Google Calendar, CalDAV, iCloud, etc.)
- One HA user account per family member who will have their own view (optional but recommended — the Kiosk user sees everyone regardless)
- Mobile app installed on any phone that should receive calendar reminders

> ⚠️ **Holiday calendars:** The integration auto-provisions US and Philippines holiday calendars on first setup via HA's built-in Holiday integration. If you are in a different region, add your country's holiday calendar manually after setup and map it via Reconfigure.

---

## Installation

### Step 1 — Add via HACS

1. In your HA sidebar, click **HACS**
2. Click the three-dot menu (top right) → **Custom repositories**
3. Repository: `https://github.com/PhilTheITGuy-USA/ha-family-dashboard`  
   Category: **Integration** → click **Add**
4. Search for **Family Dashboard** in HACS → click it → **Install**
5. Hard-refresh your browser (`Ctrl+Shift+R` / `Cmd+Shift+R`) — do **not** restart HA

### Step 2 — Add the integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Family Dashboard** and click it
3. The setup wizard launches immediately — no restart needed

---

## Setup Wizard

The wizard runs once at installation and covers ten screens in sequence. Every field can be changed later via **Reconfigure** — you are not locked into any choice made here.

| # | Screen | What to do |
|---|---|---|
| 1 | **Roster** | Add each family member by name. Members can be added, renamed, or removed any time via Reconfigure. |
| 2 | **Colors** | Assign a display color to each member from 16 preset choices. Used in calendar event color-coding and the dashboard UI. |
| 3 | **Avatars** | Set an avatar image per member. Drop PNG files into the avatars folder (created automatically) — the picker updates live without a code change. |
| 4 | **Birthdates** | Enter each member's birthdate. The integration computes a Birthdays calendar from this — no external Birthdays integration needed. |
| 5 | **Features** | Toggle Calendar, Lists, and Chores & Rewards on or off per member. Members with a feature disabled never get those entities. |
| 6 | **Link HA users** | Map each family member to their HA user account. This drives whose data appears when that person logs into the dashboard. The Kiosk user sees everyone. |
| 7 | **Calendar** | Map each member to their personal calendar entity (e.g. `calendar.phil`). The shared Family calendar and Birthdays are added automatically. |
| 8 | **Lists** | Choose which list types each member gets: To-Do, Shopping, Packing, Gift Ideas, Custom (or all five). |
| 9 | **Chores & Rewards** | Set point values for chore completion and configure the Parent Review PIN. The Unassigned bucket for shared household chores is created automatically. |
| 10 | **Confirm** | Review the summary and click **Submit**. All entities are created live — the dashboard appears in your sidebar immediately. |

> 💡 The wizard provisions everything without restarting HA. If anything looks wrong after finishing, go to **Settings → Devices & Services → Family Dashboard → Configure** to re-run the Options Flow.

---

## Post-Installation

### Navigating to the dashboard

Family Dashboard registers its own dashboard automatically. Find it in the HA sidebar labeled **Family Dashboard**. The base URL path is `/family-dashboard`.

Per-member views are at:
```
/family-dashboard/calendar-{member_id}
```
`{member_id}` is the member's stable internal id (set once when they're added to the roster,
not their display name) — check **Settings → Devices & Services → Family Dashboard** or a
member's entity IDs (e.g. `select.family_dashboard_<member_id>_color`) if you need to look it
up.

The Kiosk user lands at the full household view with toggle-filter pills.

### Wiring into an existing kiosk or remote dashboard

If you have a separate kiosk or remote dashboard with navigation chips, point the Family chip at the Family Dashboard URL.

**Kiosk dashboard** (always the same user — hardcode the member path):
```yaml
tap_action:
  action: navigate
  navigation_path: /family-dashboard/calendar-kiosk
```

**Remote / phone dashboard** (different users log in — let HA redirect to their view):
```yaml
tap_action:
  action: navigate
  navigation_path: /family-dashboard
```

> ⚠️ Always use `action: navigate`, not `action: url`. The `navigate` action keeps users inside the HA session. The `url` action opens a new browser tab and prompts for credentials.

---

## Migrating from ha-family-hub

If you are migrating from the old `ha-family-hub` package, clean up these leftovers after installing Family Dashboard. Family Dashboard creates and manages its own helpers — do not recreate any of the items below.

### configuration.yaml

Remove these two blocks and reload HA core configuration (Developer Tools → YAML → Reload Core Configuration):

```yaml
# Remove this entry under homeassistant: allowlist_external_dirs:
- /config/www/family-hub/avatars

# Remove this entire block:
sensor:
  - platform: folder
    folder: /config/www/family-hub/avatars
    filter: "*.png"
```

### Orphaned automations and scripts

Delete via **Settings → Automations & Scenes** or Developer Tools:

- `automation.family_hub_auto_lock_parent_mode`
- `automation.family_hub_reset_pin_change_authorization`
- `script.pin_change_cancel`

### Orphaned helpers

Delete via **Settings → Devices & Services → Helpers**:

**input_boolean**
- `input_boolean.parent_mode`
- `input_boolean.pin_change_authorized`
- `input_boolean.parent_review_denying`
- `input_boolean.calendar_all_day_event`
- `input_boolean.calendar_event_reminder`

**input_text**
- `input_text.pin_entry` / `input_text.parent_pin`
- `input_text.parent_review_selected_kid` / `_claim` / `_deny_reason`
- `input_text.personal_calendar_filter` (and `family_`, `birthdays_`, `holidays_`, `lhen_` variants)
- `input_text.personal_display_name` / `personal_avatar` (and `family_`, `lhen_` variants)
- `input_text.calendar_event_title` / `calendar_event_description` / `shopping_item_name`

**input_select**
- `input_select.calendar_view` / `calendar_select`
- `input_select.personal_color` (and `family_`, `lhen_`, `birthdays_`, `holidays_` variants)

**input_number**
- `input_number.calendar_event_reminder_days` / `_hours` / `_minutes`

**input_datetime**
- `input_datetime.calendar_event_start` / `_end`
- `input_datetime.calendar_day_event_start` / `_end`

---

## Reconfiguring After Setup

All settings are editable post-install — no need to reinstall.

**Settings → Devices & Services → Family Dashboard → Configure**

From the Options Flow you can:
- Add a new family member
- Change any member's name, color, avatar, or birthdate
- Toggle Calendar, Lists, or Chores on or off for any member
- Re-link a member to a different HA user account
- Change calendar mappings
- Update list type selections
- Change the Parent Review PIN
- Permanently delete a member — their chores fall back to Unassigned rather than disappearing

> 💡 Disabling a feature for a member is reversible — re-enable it any time and the entities come back. Deleting a member is permanent but their chores are preserved under Unassigned.

---

## Chores & Rewards — How It Works

### Claim flow
1. A family member marks a chore as complete — this creates a pending claim
2. A parent opens Parent Review (PIN-gated) and approves or denies the claim
3. **Approve:** points are awarded. **Deny:** a reason is required — the member sees why

### Unassigned chores
- Household chores with no single owner live in the **Unassigned** bucket
- Any family member can claim an Unassigned chore
- Useful for shared tasks: taking out bins, cleaning common areas, etc.

### Parent Review PIN
- Set during wizard Step 9
- Change it any time via Reconfigure
- The PIN gates the approve/deny interface — not the member-facing claim button

---

## Known Issues & Beta Notes

Family Dashboard is feature-complete against the v1 plan and live-validated end-to-end, but is still in beta (`v0.9.0-beta.1`).

- **ha-family-hub import:** Import from the old package is stubbed but not yet implemented. Manual cleanup of old helpers is required (see [Migrating from ha-family-hub](#migrating-from-ha-family-hub) above).
- **Meals module:** Intentionally deferred — the feature registry is shaped for it but no UI or entities are created yet.
- **Holiday regions:** Non-US / non-Philippines regions require manually adding a holiday calendar in HA and mapping it via Reconfigure.

Report issues at: [github.com/PhilTheITGuy-USA/ha-family-dashboard/issues](https://github.com/PhilTheITGuy-USA/ha-family-dashboard/issues)

---

*Family Dashboard for Home Assistant · Phil The IT Guy · [philtheitguy.pro](https://philtheitguy.pro)*  
*Circuit Hound Consulting LLC · Winter Springs, FL*
