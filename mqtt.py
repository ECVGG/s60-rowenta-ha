"""MQTT client for AWS IoT over WebSocket with SigV4."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import quote

from asyncio_mqtt import Client as AsyncMQTT, MqttError

from .auth import AWSCreds
from .const import (
    AWS_REGION,
    CREDENTIALS_FALLBACK_LIFETIME,
    CREDENTIALS_REFRESH_MARGIN,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_SERVICE,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    STABLE_CONNECTION_THRESHOLD,
    AUTH_RETRY_DELAY,
)
from .exceptions import AuthFailed, CloudUnreachable
from .models import DeviceInfo

_LOGGER = logging.getLogger(__name__)

MsgHandler = Callable[[DeviceInfo, str, dict[str, Any]], None]
ConnHandler = Callable[[bool], None]
AuthFailHandler = Callable[[], None]


@dataclass(slots=True)
class MqttConfig:
    client_id: str
    ws_path: str


def sigv4_sign(creds: AWSCreds, host: str = MQTT_HOST, region: str = AWS_REGION, service: str = MQTT_SERVICE, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"

    query = (
        "X-Amz-Algorithm=AWS4-HMAC-SHA256"
        f"&X-Amz-Credential={quote(creds.access_key + '/' + scope, safe='')}"
        f"&X-Amz-Date={amz_date}"
        "&X-Amz-SignedHeaders=host"
    )

    canonical = "\n".join(["GET", "/mqtt", query, f"host:{host}\n", "host", hashlib.sha256(b"").hexdigest()])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])

    def hmac_sha256(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k = hmac_sha256(("AWS4" + creds.secret_key).encode(), datestamp)
    k = hmac_sha256(k, region)
    k = hmac_sha256(k, service)
    k = hmac_sha256(k, "aws4_request")
    signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()

    return (
        f"/mqtt?{query}&X-Amz-Signature={signature}"
        f"&X-Amz-Security-Token={quote(creds.session_token, safe='')}"
    )


class MqttBroker:
    """Shared MQTT connection for all devices."""

    def __init__(
        self,
        hass: Any,
        cloud: Any,
        devices: list[DeviceInfo],
        on_message: MsgHandler,
        on_connection: ConnHandler,
        on_auth_fail: AuthFailHandler,
    ) -> None:
        self._hass = hass
        self._cloud = cloud
        self._devices = {d.device_id: d for d in devices}
        self._on_msg = on_message
        self._on_conn = on_connection
        self._on_auth_fail = on_auth_fail

        self._client: AsyncMQTT | None = None
        self._client_id = ""
        self._connected = False
        self._ready = False
        self._stopping = False
        self._retry = 0
        self._renewal_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def is_up(self) -> bool:
        return self._connected

    @property
    def can_pub(self) -> bool:
        return self._client is not None and self._ready

    async def start(self) -> None:
        self._stopping = False
        await self._run_loop()

    async def stop(self) -> None:
        self._stopping = True
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
        await self._disconnect()

    async def _run_loop(self) -> None:
        while not self._stopping:
            try:
                await self._connect_and_run()
            except AuthFailed:
                if self._stopping:
                    break
                _LOGGER.warning("MQTT auth failed, triggering re-auth")
                self._on_auth_fail()
                await asyncio.sleep(AUTH_RETRY_DELAY)
            except CloudUnreachable as err:
                if self._stopping:
                    break
                _LOGGER.debug("MQTT connection error: %s", err)
                await self._backoff("connection_error")
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.exception("Unexpected MQTT error: %s", err)
                if self._stopping:
                    break
                await self._backoff("unexpected")

    async def _connect_and_run(self) -> None:
        creds = await self._cloud.async_get_aws_creds()
        if self._stopping:
            return

        client_id = f"s60-{uuid.uuid4().hex[:16]}"
        ws_path = sigv4_sign(creds)

        async with self._lock:
            await self._disconnect()
            self._client_id = client_id

            self._client = AsyncMQTT(
                hostname=MQTT_HOST,
                port=MQTT_PORT,
                client_id=client_id,
                transport="websockets",
                websocket_path=ws_path,
                tls_context=True,
                keepalive=60,
                clean_session=True,
            )

        lifetime = creds.expiration - time.time() if creds.expiration else CREDENTIALS_FALLBACK_LIFETIME.total_seconds()
        renew_in = max(60.0, lifetime - CREDENTIALS_REFRESH_MARGIN.total_seconds())
        self._renewal_task = asyncio.create_task(self._renew_later(renew_in))

        async with self._client:
            await self._client.connect()
            _LOGGER.debug("MQTT WebSocket connected")

            for dev in self._devices.values():
                topics = [
                    f"{dev.mqtt_base}/status",
                    f"{dev.mqtt_base}/history",
                    f"{dev.shadow_base}/get/accepted",
                    f"{dev.shadow_base}/update/documents",
                ]
                for t in topics:
                    await self._client.subscribe(t, qos=0)

            self._connected = True
            self._ready = True
            self._retry = 0
            self._on_conn(True)

            await asyncio.sleep(2)

            if self.can_pub:
                for dev in self._devices.values():
                    await self._get_shadow(dev)
                    await self._get_status(dev, listening=True)
                    await self._get_history(dev)

            async for msg in self._client.messages:
                if self._stopping:
                    break
                await self._route_msg(msg.topic, msg.payload)

    async def _renew_later(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if not self._stopping:
                _LOGGER.debug("MQTT creds expiring, renewing")
                await self._disconnect()
        except asyncio.CancelledError:
            pass

    async def _disconnect(self) -> None:
        self._connected = False
        self._ready = False
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
        self._client = None

    async def _backoff(self, reason: str) -> None:
        if self._stopping:
            return
        self._connected = False
        self._ready = False
        self._on_conn(False)

        delay = min(RECONNECT_BASE_DELAY * (2 ** self._retry), RECONNECT_MAX_DELAY)
        self._retry += 1
        _LOGGER.debug("MQTT reconnect in %.0fs (%s, try %d)", delay, reason, self._retry)
        await asyncio.sleep(delay)

    async def _route_msg(self, topic: str, payload: bytes) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return

        for dev in self._devices.values():
            if topic.startswith(f"{dev.mqtt_base}/"):
                kind = topic[len(dev.mqtt_base) + 1:]
                self._on_msg(dev, kind, data)
                return
            if topic.startswith(f"{dev.shadow_base}/"):
                kind = "shadow/" + topic[len(dev.shadow_base) + 1:]
                self._on_msg(dev, kind, data)
                return

    async def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not self.can_pub or self._client is None:
            raise CloudUnreachable("mqtt_not_ready")
        try:
            await self._client.publish(topic, json.dumps(payload), qos=0)
        except MqttError as err:
            raise CloudUnreachable(f"mqtt_pub_failed:{err}") from err

    async def _get_shadow(self, dev: DeviceInfo) -> None:
        await self._publish(f"{dev.shadow_base}/get", {})

    async def _get_status(self, dev: DeviceInfo, listening: bool = False) -> None:
        if listening:
            await self._publish(f"{dev.mqtt_base}/clientListening", {"clientId": self._client_id, "listening": True})
        await self._publish(f"{dev.mqtt_base}/getStatus", {})

    async def _get_history(self, dev: DeviceInfo) -> None:
        await self._publish(f"{dev.mqtt_base}/getHistory", {})

    # Public API
    async def send_cmd(self, dev: DeviceInfo, cmd: dict[str, Any]) -> None:
        await self._publish(f"{dev.mqtt_base}/command", cmd)
        await self._get_status(dev)

    async def update_shadow(self, dev: DeviceInfo, desired: dict[str, Any]) -> None:
        await self._publish(f"{dev.shadow_base}/update", {"state": {"desired": desired}})