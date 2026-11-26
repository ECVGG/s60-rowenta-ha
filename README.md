# Rowenta X-Plorer Series 60 (Cloud) for Home Assistant

Custom integration for **Rowenta X-Plorer Series 60** using the **Groupe SEB Cloud (AWS IoT MQTT)**.

**Author:** ECVGG (unofficial, not affiliated with Rowenta/Groupe SEB)

## Features

- [x] Full vacuum control: start, pause, stop, return to base, spot clean, locate
- [x] Suction power: Silent / Normal / Strong
- [x] Cleaning modes: Smart, Random, Edges, Small Room, Mop, Spiral
- [x] **Live map** rendered from gyro data (256x256 grid)
- [x] Cleaning history with area, duration, mode, power, battery
- [x] Accessory wear sensors: side brush, main brush, filter
- [x] Battery, status, error code, MQTT connectivity sensors
- [x] **Schedule management** via AWS Device Shadow (create/edit/delete/enable/disable)
- [x] MQTT push updates (real-time, no polling for state)
- [x] Multi-robot support
- [x] Spanish & English translations

## Installation

### HACS (Recommended)

1. Open **HACS** -> **Integrations**
2. Click **...** -> **Custom repositories**
3. Add: `https://github.com/ECVGG/s60-rowenta-ha` (Category: **Integration**)
4. Search **"Rowenta X-Plorer Series 60"** -> **Download**
5. **Restart Home Assistant**

### Manual

Copy the `custom_components/s60_rowenta` folder of this repository into `/config/custom_components/`, then restart Home Assistant.

Requires Home Assistant 2025.10 or newer.

## Configuration

1. **Settings** -> **Devices & Services** -> **Add Integration**
2. Search **"Rowenta X-Plorer Series 60"**
3. Enter your **Rowenta Robots app credentials** (email/password)
4. Select your **country** (must match app setting)
5. Submit -> Your robot(s) will be discovered automatically

## Entities Created

| Entity | Description |
|--------|-------------|
| `vacuum.s60_rowenta_*` | Main control (all vacuum features) |
| `image.s60_rowenta_*_map` | Live cleaning map |
| `sensor.s60_rowenta_*_battery` | Battery % |
| `sensor.s60_rowenta_*_status` | Current status |
| `sensor.s60_rowenta_*_mode` | Current cleaning mode |
| `sensor.s60_rowenta_*_area` | Area cleaned this session |
| `sensor.s60_rowenta_*_duration` | Time cleaning this session |
| `sensor.s60_rowenta_*_side_brush_wear` | Side brush wear % |
| `sensor.s60_rowenta_*_main_brush_wear` | Main brush wear % |
| `sensor.s60_rowenta_*_filter_wear` | Filter wear % |
| `sensor.s60_rowenta_*_total_area` | Lifetime area |
| `sensor.s60_rowenta_*_total_time` | Lifetime time |
| `sensor.s60_rowenta_*_total_jobs` | Lifetime cleanings |
| `sensor.s60_rowenta_*_last_job` | Last cleaning timestamp |
| `sensor.s60_rowenta_*_sched_count` | Active schedules |
| `sensor.s60_rowenta_*_mqtt` | MQTT connectivity |
| `binary_sensor.s60_rowenta_*_cloud_up` | Cloud connectivity |
| `select.s60_rowenta_*_start_mode` | Default cleaning mode |
| `select.s60_rowenta_*_map_pick` | Which cleaning to show on map |
| `switch.s60_rowenta_*_sched_*` | Enable/disable schedules |

## Services

| Service | Description |
|---------|-------------|
| `s60_rowenta.get_schedules` | List all schedules |
| `s60_rowenta.set_schedule` | Create or update schedule |
| `s60_rowenta.delete_schedule` | Delete a schedule |
| `vacuum.send_command` | Raw command (advanced) |

## Schedule Management

Go to **Settings** -> **Devices & Services** -> **Rowenta X-Plorer Series 60** -> **Configure** to manage schedules via UI.

## Supported Models

- **Rowenta X-Plorer Series 60** (VAC001) Tested
- Other Groupe SEB VAC001 platform robots (untested)

## Technical Details

- **Protocol**: Salesforce RCU -> AWS Cognito -> AWS IoT MQTT (WebSocket, SigV4)
- **Map**: Gyro points (256x256 grid) rendered locally with Pillow
- **Schedules**: AWS Device Shadow (desired/reported state)
- **Updates**: MQTT push (status, history, shadow) + periodic polls

## Map card

Added automatically with the integration. Add a **Manual** card to a dashboard:

```yaml
type: custom:s60-rowenta-map-card
entity: vacuum.your_robot
```

Views: live (animated), replay, heat map and comparison of two cleanings. Drag to move; use the wheel, pinch or buttons to zoom.

- Maps are stored from version 0.4.0 on (up to 30), as they are downloaded. Older cleanings appear once selected in "Show on map".
- Heat map and comparison assume the robot uses the same coordinates in every cleaning (dock not moved, same starting point).
- "Live" depends on how often the cloud publishes new points.

## Blueprints

Import from **Settings** -> **Automations** -> **Blueprints** -> **Import blueprint**:

- `https://github.com/ECVGG/s60-rowenta-ha/blob/main/blueprints/automation/s60_rowenta/smart_cleaning.yaml`
- `https://github.com/ECVGG/s60-rowenta-ha/blob/main/blueprints/automation/s60_rowenta/weekly_report.yaml`

## Diagnostics

**Settings** -> **Devices & Services** -> the integration -> menu (...) -> **Download diagnostics**.
Tokens, identifiers and names are redacted, but review the file before sharing it: it includes your cleaning map, history and schedule times.

## License

MIT License - see [LICENSE](LICENSE)

## Disclaimer

This is an **unofficial** integration. Not affiliated with Rowenta or Groupe SEB.
Use at your own risk. The integration uses public cloud APIs discovered through traffic analysis.