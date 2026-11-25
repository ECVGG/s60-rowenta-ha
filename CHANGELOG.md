# Changelog

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
