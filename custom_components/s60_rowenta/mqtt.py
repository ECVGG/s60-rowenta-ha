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

from aiomqtt import Client as AsyncMQTT, MqttError
from homeassistant.core import callback
from homeassistant.util.ssl import get_default_context

from .const import (
    AWS_REGION,
    CREDENTIALS_FALLBACK_LIFETIME,
    CREDENTIALS_REFRESH_MARGIN,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_SERVICE,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    AUTH_RETRY_DELAY,
)
from .exceptions import AuthFailed, CloudUnreachable
from .models import AWSCreds, DeviceInfo

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
        self._stopping = False
        self._retry = 0

    @property
    def can_pub(self) -> bool:
        return self._client is not None

    @callback
    def stop(self) -> None:
        """Flag shutdown; Home Assistant cancels the background task on unload."""
        self._stopping = True

    async def run(self) -> None:
        while not self._stopping:
            try:
                # Returns normally when credentials are due for renewal
                await self._connect_and_run()
            except AuthFailed:
                _LOGGER.warning("MQTT auth failed, triggering re-auth")
                self._on_conn(False)
                self._on_auth_fail()
                await asyncio.sleep(AUTH_RETRY_DELAY)
            except (CloudUnreachable, MqttError) as err:
                _LOGGER.debug("MQTT connection error: %s", err)
                await self._backoff("connection_error")
            except Exception:
                _LOGGER.exception("Unexpected MQTT error")
                await self._backoff("unexpected")

    async def _connect_and_run(self) -> None:
        creds = await self._cloud.async_get_aws_creds()
        if self._stopping:
            return

        self._client_id = f"s60-{uuid.uuid4().hex[:16]}"
        lifetime = (
            creds.expiration - time.time()
            if creds.expiration
            else CREDENTIALS_FALLBACK_LIFETIME.total_seconds()
        )
        renew_in = max(60.0, lifetime - CREDENTIALS_REFRESH_MARGIN.total_seconds())

        try:
            async with AsyncMQTT(
                hostname=MQTT_HOST,
                port=MQTT_PORT,
                identifier=self._client_id,
                transport="websockets",
                websocket_path=sigv4_sign(creds),
                tls_context=get_default_context(),
                keepalive=60,
                clean_session=True,
            ) as client:
                for dev in self._devices.values():
                    for topic in (
                        f"{dev.mqtt_base}/status",
                        f"{dev.mqtt_base}/history",
                        f"{dev.shadow_base}/get/accepted",
                        f"{dev.shadow_base}/update/documents",
                    ):
                        await client.subscribe(topic, qos=0)

                self._client = client
                self._retry = 0
                self._on_conn(True)

                for dev in self._devices.values():
                    await self._get_shadow(dev)
                    await self._get_status(dev, listening=True)
                    await self._get_history(dev)

                try:
                    async with asyncio.timeout(renew_in):
                        async for msg in client.messages:
                            self._route_msg(str(msg.topic), msg.payload)
                except TimeoutError:
                    _LOGGER.debug("MQTT credentials expiring, reconnecting")
        finally:
            self._client = None

    async def _backoff(self, reason: str) -> None:
        if self._stopping:
            return
        self._on_conn(False)

        delay = min(RECONNECT_BASE_DELAY * (2 ** self._retry), RECONNECT_MAX_DELAY)
        self._retry += 1
        _LOGGER.debug("MQTT reconnect in %.0fs (%s, try %d)", delay, reason, self._retry)
        await asyncio.sleep(delay)

    def _route_msg(self, topic: str, payload: bytes) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
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
        if self._client is None:
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