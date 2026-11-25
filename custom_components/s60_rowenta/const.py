"""Constants for Rowenta X-Plorer Series 60 Cloud integration."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Final

DOMAIN: Final = "s60_rowenta"
INTEGRATION_NAME: Final = "Rowenta X-Plorer Series 60"
AUTHOR: Final = "ECVGG"

# Public endpoints (discoverable from app traffic)
APP_VERSION: Final = "10.0.0"
SEB_API: Final = "https://sebplatform.api.groupe-seb.com"
SEB_API_BASE: Final = "https://sebplatform.api.groupe-seb.com"
IOT_API_BASE: Final = "https://iot.api.groupe-seb.com"
SEB_API_KEY: Final = "19UfOfJmK6365857UYNzjn427R6q1XFA"

# Salesforce RCU (Identity Provider)
RCU_BASE: Final = "https://account.groupeseb.com"
RCU_CLIENT_ID: Final = (
    "3MVG99qusVZJwhskrTckKb5cJcZ6TRAFaBT4BFiKrzcUhle5GnfyASjYwMxTEEZruROQUz_lAj8HnLFbES7nv"
)
REDIRECT_URI: Final = "gsmoduser://tokens"

# AWS Cognito
COGNITO_ENDPOINT: Final = "https://consumers.api.groupe-seb.com/"
COGNITO_POOL_ID: Final = "eu-west-1:f25c4598-48da-4fda-9c1a-27fe30bd2ffe"
COGNITO_LOGIN_KEY: Final = "account.groupeseb.com"

# AWS IoT MQTT over WebSocket
MQTT_HOST: Final = "prod-new.iot.mqtt.groupe-seb.com"
MQTT_PORT: Final = 443
AWS_REGION: Final = "eu-west-1"
MQTT_SERVICE: Final = "iotdevicegateway"

# Login URL (Salesforce Visualforce flow)
LOGIN_URL: Final = (
    f"{RCU_BASE}/ContinuationForExpId?apikey={SEB_API_KEY}&redirect_uri={REDIRECT_URI}"
    "&state=STATE&response_type=token+id_token+refresh_token&nonce=NONCE"
    f"&isUserName=false&version={APP_VERSION}"
)

# Config entry keys
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_PERIMETER: Final = "profile_perimeter"
CONF_MARKET: Final = "market_name"
CONF_COUNTRY: Final = "country_code"
CONF_EMAIL: Final = "email"

# Polling intervals
STATUS_POLL_IDLE: Final = timedelta(seconds=60)
STATUS_POLL_ACTIVE: Final = timedelta(seconds=15)
MAP_REFRESH_INTERVAL: Final = timedelta(seconds=30)
HISTORY_POLL_INTERVAL: Final = timedelta(minutes=30)
SHADOW_POLL_INTERVAL: Final = timedelta(minutes=10)

# Credential lifetime (Cognito ~1 hour)
CREDENTIALS_REFRESH_MARGIN: Final = timedelta(minutes=5)
CREDENTIALS_FALLBACK_LIFETIME: Final = timedelta(minutes=55)

# MQTT reconnection
RECONNECT_BASE_DELAY: Final = 5
RECONNECT_MAX_DELAY: Final = 300
STABLE_CONNECTION_THRESHOLD: Final = 60
AUTH_RETRY_DELAY: Final = 1800

# User-Agent for web login
_BROWSER_UA: Final = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Mobile Safari/537.36"
)
_MAX_LOGIN_STEPS: Final = 12

# Transport errors that should surface as connection errors
_TRANSPORT_ERRORS = (
    "aiohttp.ClientError",
    "TimeoutError",
    "ValueError",
    "KeyError",
    "TypeError",
    "AttributeError",
)

# OAuth errors that mean the refresh token is no longer valid
AUTH_ERRORS: Final = frozenset({"invalid_grant", "invalid_client", "unauthorized_client"})


class RobotState(StrEnum):
    """Robot status values from cloud."""
    CLEANING = "CLEANING"
    STANDBY = "STANDBY"
    CHARGING = "CHARGING"
    DOCKING = "DOCKING"
    STOP = "STOP"
    UPGRADING = "UPGRADING"
    ERROR = "ERROR"


class RobotError(StrEnum):
    """Robot error codes."""
    NORMAL = "NORMAL"
    LEFT_SIDE_BRUSH = "LEFT_SIDE_BRUSH_ERROR"
    RIGHT_SIDE_BRUSH = "RIGHT_SIDE_BRUSH_ERROR"
    MAIN_BRUSH = "MAIN_BRUSH_ERROR"
    LEFT_WHEEL = "LEFT_WHEEL_ERROR"
    RIGHT_WHEEL = "RIGHT_WHEEL_ERROR"
    FAN_MOTOR = "FAN_MOTOR_ERROR"
    CLIFF_SENSOR = "CLIFF_SENSOR_ERROR"
    OFF_GROUND = "OFF_GROUND_ERROR"
    BUMPER = "BUMPER_ERROR"
    CHARGING = "CHARGING_ERROR"
    WALL_SENSOR = "WALL_SENSOR_ERROR"
    DUSTBIN = "DUSTBIN_ERROR"
    FRONT_WHEEL = "FRONT_WHEEL_ERROR"
    NO_BATTERY = "NO_BATTERY_ERROR"
    LOW_BATTERY = "LOW_BATTERY_ERROR"


class CleanMode(StrEnum):
    """Cleaning methods supported by VAC001."""
    PAUSE = "PAUSE"
    AUTO = "AUTO_CLEANING"
    EDGES = "WALL_FOLLOW"
    SMART = "SMART_CLEANING"
    SPOT = "SPIRAL"
    LEFT_SPIRAL = "LEFT_SPIRAL"
    RIGHT_SPIRAL = "RIGHT_SPIRAL"
    RIGHT_ZIGZAG = "RIGHT_BOW"
    LEFT_ZIGZAG = "LEFT_BOW"
    PARTIAL_ZIGZAG = "PARTIAL_BOW"
    RECHARGE_RESUME = "CHARGE_GO"
    MOP = "MOP"
    SMALL_ROOM = "SMALL_ROOM_CLEAN"
    RETURN_HOME = "BACK_TO_DOCK"
    SLEEP = "SLEEP"
    SCHEDULED = "SCHEDULE_CLEAN"


class SuctionPower(StrEnum):
    """Suction power levels."""
    QUIET = "SILENT"
    NORMAL = "NORMAL"
    MAX = "STRONG"


# Methods available for manual start (user-facing)
START_MODES: Final = [
    CleanMode.SMART,
    CleanMode.AUTO,
    CleanMode.EDGES,
    CleanMode.SMALL_ROOM,
    CleanMode.MOP,
    CleanMode.SPOT,
]

# Methods allowed in schedules (subset)
SCHEDULE_MODES: Final = [
    CleanMode.SMART,
    CleanMode.AUTO,
    CleanMode.EDGES,
    CleanMode.SMALL_ROOM,
]

SCHEDULE_POWERS: Final = [SuctionPower.QUIET, SuctionPower.NORMAL, SuctionPower.MAX]

# Day mapping (1=Monday ... 7=Sunday per SEB)
DAY_TO_CODE: Final = {1: "mon", 2: "tue", 3: "wed", 4: "thu", 5: "fri", 6: "sat", 7: "sun"}
CODE_TO_DAY: Final = {v: k for k, v in DAY_TO_CODE.items()}

# Accessory names (from cloud)
ACCESSORY_MAP: Final = {
    "SIDE-BRUSH": "side_brush",
    "MAIN-BRUSH": "main_brush",
    "FILTER": "filter",
}

# Map point types (gyro map 256x256 grid)
MAP_ORIGIN: Final = 128
MAP_GRID_SIZE: Final = 256
MAP_POINT_TYPES = {
    "cleaned": {1, 6, 11},
    "path": {3, 8, 12},
    "obstacle": {2, 7},
    "wall": {4, 9},
    "cliff": {5, 10},
}

# Map rendering
MAP_MIN_CELL: Final = 4
MAP_MAX_CELL: Final = 24
MAP_MAX_DIMENSION: Final = 800
MAP_PADDING: Final = 2

MAP_COLORS = {
    "cleaned": (0x82, 0xBE, 0xFF, 0xFF),
    "path": (0x3C, 0x82, 0xE6, 0xFF),
    "obstacle": (0xE6, 0x50, 0x50, 0xFF),
    "wall": (0x5A, 0x5A, 0x5A, 0xFF),
    "cliff": (0xAA, 0x3C, 0xAA, 0xFF),
    "other": (0xAA, 0xAA, 0xAA, 0xFF),
    "start": (0x28, 0xAA, 0x46, 0xFF),
    "robot": (0xFF, 0xBE, 0x00, 0xFF),
}
