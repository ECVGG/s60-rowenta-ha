# Changelog

## 0.4.0 (pending release)

- Map card: animated live view, replay, heat map, comparison, zoom and controls.
- Map image: path line, dock and robot heading.
- Maps and incidents are stored and survive restarts.
- New sensors: area in 7 days, days since last cleaning, recorded incidents.
- Blueprints: smart cleaning and weekly report.
- Map refresh while cleaning every 15 s (was 30 s).

## 0.3.0

- Downloadable diagnostics with personal data redacted.
- Tests and GitHub Actions (pytest, hassfest, HACS).

## 0.2.1

- Login: follow more redirect types and self-submitting pages (`login_no_tokens`).
- AWS credentials: add the `GetOpenIdToken` step.
- Failed logins now log the steps taken, without tokens or query strings.
- Login and credential handling partly adapted from BlackPavilion/rowxplorer-hacs (MIT).

## 0.2.0

### Fixed
- Integration failed to load: missing constants and imports.
- Network errors raised `TypeError` instead of a connection error.
- MQTT: migrated from `asyncio-mqtt` to `aiomqtt`; the connection now runs in the background and reconnects before credentials expire.
- Spot clean and return to base sent enum names instead of command values.
- Schedules: mode/power validation, saving from the options dialog, translated errors.
- Cleaning history sensors and map selector.
- Manifest, HACS metadata, translations and install instructions.

### Changed
- Minimum Home Assistant version is 2025.10.
- Removed the unused on-disk map cache.

Not yet tested against the real Rowenta cloud or a physical robot.
