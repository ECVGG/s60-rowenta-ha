"""Authentication: Salesforce RCU → Cognito → AWS Credentials."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import aiohttp

from .const import (
    APP_VERSION,
    COGNITO_ENDPOINT,
    COGNITO_LOGIN_KEY,
    COGNITO_POOL_ID,
    IOT_API_BASE,
    LOGIN_URL,
    RCU_BASE,
    RCU_CLIENT_ID,
    SEB_API,
    SEB_API_KEY,
    _BROWSER_UA,
    _MAX_LOGIN_STEPS,
    _TRANSPORT_ERRORS,
    AUTH_ERRORS,
)
from .exceptions import AuthFailed, CloudUnreachable, ProtocolMismatch
from .models import AWSCreds, Market

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)

_REDIRECT_RE = re.compile(r"gsmoduser://tokens[#?]([^\s'\"<>]+)")
_JS_LOCATION_RE = re.compile(
    r"(?:window\.location(?:\.href\s*=\s*|\.replace\(\s*)|handleRedirect\(\s*)[\"']([^\"']+)[\"']"
)
_FORM_RE = re.compile(r'<form id="([^"]+)"[^>]*action="([^"]+)"')
_VIEWSTATE_RE = re.compile(
    r'<input type="hidden"\s+id="(com\.salesforce\.visualforce\.[A-Za-z]+)" name="[^"]+" value="([^"]*)"'
)
_A4J_RE = re.compile(r"A4J\.AJAX\.Submit\('([^']+)',null,\{'similarityGroupingId':'([^']+)'}")
_LOGIN_ACTION_RE = re.compile(
    r"loginAF=function\(userEmail,password\)\{A4J\.AJAX\.Submit\('([^']+)',null,"
    r"\{'similarityGroupingId':'([^']+)'"
)
_META_LOCATION_RE = re.compile(r'<meta name="Location" content="([^"]+)"')
_META_REFRESH_RE = re.compile(
    r"<meta[^>]+http-equiv=[\"']refresh[\"'][^>]+url=([^\"'<>]+)", re.IGNORECASE
)
# Auto-submitting pages (e.g. /apex/LoginFlow); handling adapted from
# BlackPavilion/rowxplorer-hacs (MIT License)
_AUTOSUBMIT_RE = re.compile(r"A4J\.AJAX\.Submit\(\s*['\"]([^'\"]+)['\"]\s*,\s*null\s*,")
_PARAMETERS_RE = re.compile(r"['\"]parameters['\"]\s*:\s*\{([^{}]*)\}")
_PAIR_RE = re.compile(r"['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]*)['\"]")
_FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf"\s{name}=([\"'])(.*?)\1", tag, re.IGNORECASE)
    return unescape(match.group(2)) if match else None


def next_location(text: str) -> str | None:
    """Next hop announced by a page (JavaScript or meta tags)."""
    for pattern in (_JS_LOCATION_RE, _META_REFRESH_RE, _META_LOCATION_RE):
        if match := pattern.search(text):
            return unescape(match.group(1).replace("\\/", "/"))
    return None


def parse_autosubmit(page: str, page_url: str) -> tuple[str, dict[str, str]] | None:
    """Return (url, data) for a form the page submits by itself on load."""
    submit = _AUTOSUBMIT_RE.search(page)
    if not submit:
        return None
    forms = _FORM_TAG_RE.findall(page)
    form = next((f for f in forms if _attr(f, "id") == submit.group(1)), None)
    form = form or (forms[0] if forms else None)
    if form is None:
        return None
    data = {"AJAXREQUEST": "_viewRoot"}
    for tag in _INPUT_RE.findall(page):
        if name := _attr(tag, "name"):
            data[name] = _attr(tag, "value") or ""
    if params := _PARAMETERS_RE.search(page, submit.end()):
        data.update({k: unescape(v) for k, v in _PAIR_RE.findall(params.group(1))})
    return urljoin(page_url, _attr(form, "action") or page_url), data


def parse_redirect(text: str) -> dict[str, str]:
    match = _REDIRECT_RE.search(text.strip())
    if not match:
        raise ProtocolMismatch("no_redirect")
    params = {k: v[0] for k, v in parse_qs(match.group(1)).items()}
    if "refresh_token" not in params:
        raise ProtocolMismatch("no_refresh_token")
    return params


def user_id_from_tokens(tokens: dict[str, Any]) -> str | None:
    ident = tokens.get("id")
    if not ident:
        return None
    return urlsplit(ident).path.rstrip("/").rsplit("/", 1)[-1] or None


def find_redirect(text: str) -> str | None:
    clean = text.replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")
    match = _REDIRECT_RE.search(clean)
    return match.group(0) if match else None


async def a4j_submit(
    session: aiohttp.ClientSession,
    page: str,
    page_url: str,
    form_id: str,
    action_id: str,
    extra: dict[str, str] | None = None,
) -> str | None:
    form = next((m for m in _FORM_RE.finditer(page) if m.group(1) == form_id), None)
    if form is None:
        raise ProtocolMismatch(f"form_missing:{form_id}")
    data = {
        "AJAXREQUEST": "_viewRoot",
        form_id: form_id,
        **{m.group(1): unescape(m.group(2)) for m in _VIEWSTATE_RE.finditer(page)},
        **(extra or {}),
        action_id: action_id,
    }
    async with session.post(
        urljoin(page_url, unescape(form.group(2))),
        data=data,
        allow_redirects=False,
        headers={"Referer": page_url, "Origin": RCU_BASE},
    ) as resp:
        if resp.status >= 400:
            raise CloudUnreachable(f"login_http_{resp.status}")
        body = await resp.text()
        nxt = resp.headers.get("Ajax-Location") or resp.headers.get("Location")
    if not nxt and (meta := _META_LOCATION_RE.search(body)):
        nxt = unescape(meta.group(1))
    return urljoin(page_url, nxt) if nxt else None


async def async_login(email: str, password: str) -> dict[str, str]:
    """Full Salesforce Visualforce login flow."""
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
        headers={"User-Agent": _BROWSER_UA},
        timeout=TIMEOUT,
    ) as session:
        try:
            async with session.get(LOGIN_URL) as resp:
                text = await resp.text()
            match = _JS_LOCATION_RE.search(text)
            if not match:
                raise ProtocolMismatch("authorize_redirect_missing")

            async with session.get(unescape(match.group(1))) as resp:
                page = await resp.text()
                page_url = str(resp.url)

            action = _LOGIN_ACTION_RE.search(page)
            if not action:
                raise ProtocolMismatch("login_form_changed")

            url = await a4j_submit(
                session, page, page_url,
                action.group(1), action.group(2),
                {"userEmail": email, "password": password},
            )
            if not url:
                raise AuthFailed("invalid_credentials")

            # Paths and status codes only: queries carry session secrets
            trail: list[str] = []
            for _ in range(_MAX_LOGIN_STEPS):
                if url.startswith("gsmoduser://"):
                    return parse_redirect(url)

                async with session.get(url, allow_redirects=False) as resp:
                    trail.append(f"GET {urlsplit(url).path} {resp.status}")
                    if resp.status in (301, 302, 303, 307, 308):
                        url = urljoin(url, resp.headers["Location"])
                        continue
                    text = await resp.text()

                if redirect := find_redirect(text):
                    return parse_redirect(redirect)

                if nxt := next_location(text):
                    url = urljoin(url, nxt)
                    continue

                if auto := parse_autosubmit(text, url):
                    post_url, data = auto
                    async with session.post(
                        post_url,
                        data=data,
                        allow_redirects=False,
                        headers={
                            "Referer": url,
                            "Origin": RCU_BASE,
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    ) as resp:
                        trail.append(f"POST {urlsplit(post_url).path} {resp.status}")
                        body = await resp.text()
                        nxt = resp.headers.get("Ajax-Location") or resp.headers.get("Location")
                    if redirect := find_redirect(body):
                        return parse_redirect(redirect)
                    if nxt := nxt or next_location(body):
                        url = urljoin(post_url, nxt)
                        continue
                break

        except _TRANSPORT_ERRORS as err:
            raise CloudUnreachable(f"login_network:{err!r}") from err

    raise ProtocolMismatch(f"login_no_tokens: {' > '.join(trail)}")


async def async_get_market(session: aiohttp.ClientSession, country: str) -> Market:
    url = f"{SEB_API}/common-api/v3/configurations/{SEB_API_KEY}"
    params = {"version": APP_VERSION, "country": country.upper(), "lang": "en"}
    headers = {"apiKey": SEB_API_KEY}

    try:
        async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise CloudUnreachable(f"market_http_{resp.status}")
            data = await resp.json(content_type=None)
    except _TRANSPORT_ERRORS as err:
        raise CloudUnreachable(f"market_network:{err!r}") from err

    markets = data.get("markets") or []
    wanted = country.upper()
    for market in markets:
        if not isinstance(market, dict):
            continue
        rcu = market.get("rcuMarket")
        name = market.get("name")
        perimeter = market.get("profilePerimeter")
        if not isinstance(name, str) or not isinstance(perimeter, str):
            continue
        if (isinstance(rcu, str) and rcu.upper() == wanted) or name.endswith(f"_{wanted}"):
            return Market(name, perimeter)

    raise ProtocolMismatch(f"unsupported_country:{country}")


def parse_expiration(value: Any) -> float:
    """Epoch seconds from a number or ISO-8601 string; 0 if unknown."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class SebCloud:
    """Authenticated client for Groupe SEB cloud."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str,
        perimeter: str,
    ) -> None:
        self._session = session
        self._refresh_token = refresh_token
        self._perimeter = perimeter
        self._access_token: str | None = None
        self._id_token: str | None = None
        self._token_time = 0.0
        self._user_id: str | None = None
        self._on_refresh: callable | None = None

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    @property
    def user_id(self) -> str | None:
        return self._user_id

    def set_refresh_callback(self, callback: callable) -> None:
        self._on_refresh = callback

    async def async_refresh_tokens(self) -> None:
        form = {
            "grant_type": "refresh_token",
            "client_id": RCU_CLIENT_ID,
            "refresh_token": self._refresh_token,
        }
        try:
            async with self._session.post(
                f"{RCU_BASE}/services/oauth2/token", data=form, timeout=TIMEOUT
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status in (400, 401) and data.get("error") in AUTH_ERRORS:
                    raise AuthFailed(data.get("error_description") or data["error"])
                if resp.status != 200:
                    raise CloudUnreachable(f"oauth_http_{resp.status}")
            access_token = data["access_token"]
        except _TRANSPORT_ERRORS as err:
            raise CloudUnreachable(f"oauth_network:{err!r}") from err

        self._access_token = access_token
        self._id_token = data.get("id_token")
        self._token_time = time.monotonic()
        self._user_id = user_id_from_tokens(data) or self._user_id

        new_token = data.get("refresh_token")
        if new_token and new_token != self._refresh_token:
            self._refresh_token = new_token
            if self._on_refresh:
                self._on_refresh(new_token)

    async def _valid_token(self) -> str:
        if self._access_token is None or time.monotonic() - self._token_time > 600:
            await self.async_refresh_tokens()
        assert self._access_token
        return self._access_token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "ApiKey": SEB_API_KEY,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Gseb-App-Version": APP_VERSION,
            "X-Consumer-Channel": "MOBILE_APP_ANDROID",
            "Authorization": f"Bearer {token}",
            "Grant-Type": "RCUToken",
            "DCP-Context": self._perimeter,
        }

    async def _get(
        self, name: str, url: str, params: dict[str, str] | None = None, allow_404: bool = False
    ) -> dict[str, Any]:
        token = await self._valid_token()
        for attempt in (1, 2):
            try:
                async with self._session.get(
                    url, params=params, headers=self._headers(token), timeout=TIMEOUT
                ) as resp:
                    status = resp.status
                    data = await resp.json(content_type=None) if status == 200 else None
            except _TRANSPORT_ERRORS as err:
                raise CloudUnreachable(f"{name}_network:{err!r}") from err

            if status in (401, 403) and attempt == 1:
                await self.async_refresh_tokens()
                token = self._access_token or ""
                continue
            if status == 404 and allow_404:
                return {}
            if status != 200:
                raise CloudUnreachable(f"{name}_http_{status}")
            if not isinstance(data, dict):
                raise ProtocolMismatch(f"{name}_unexpected")
            return data
        raise CloudUnreachable(f"{name}_rejected")

    async def async_get_profile(self) -> dict[str, Any]:
        return await self._get("profile", f"{SEB_API}/common-api/profiles/me")

    async def async_get_devices(self) -> list[dict[str, Any]]:
        profile = await self.async_get_profile()
        result = []
        for product in (profile.get("household") or {}).get("products") or []:
            iot = product.get("iot") or {}
            did, ttype = iot.get("functionalId"), iot.get("thingType")
            if not did or not ttype or not ttype.startswith("VAC"):
                continue
            result.append({
                "device_id": did,
                "thing_type": ttype,
                "name": product.get("name") or ttype,
                "model_code": product.get("appliance"),
            })
        return result

    async def async_get_map(self, thing_type: str, device_id: str, map_id: str) -> dict[str, Any]:
        url = f"{IOT_API_BASE}/vacuum/v1/map/{thing_type}/{device_id}"
        params = {"mapId": str(map_id), "pageSize": "-1", "index": "1"}
        return await self._get("map", url, params=params, allow_404=True)

    async def _cognito(self, target: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": f"AWSCognitoIdentityService.{target}",
        }
        try:
            async with self._session.post(
                COGNITO_ENDPOINT, data=json.dumps(body), headers=headers, timeout=TIMEOUT
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status in (400, 401, 403):
                    kind = str(data.get("__type", ""))
                    raise CloudUnreachable(f"cognito_{target}:{kind or resp.status}")
                if resp.status != 200:
                    raise CloudUnreachable(f"cognito_{target}_http_{resp.status}")
        except _TRANSPORT_ERRORS as err:
            raise CloudUnreachable(f"cognito_{target}_network:{err!r}") from err
        if not isinstance(data, dict):
            raise ProtocolMismatch(f"cognito_{target}_unexpected")
        return data

    async def async_get_aws_creds(self) -> AWSCreds:
        await self.async_refresh_tokens()
        if not self._id_token:
            raise AuthFailed("id_token_missing")
        logins = {COGNITO_LOGIN_KEY: self._id_token}
        ident = await self._cognito("GetId", {"IdentityPoolId": COGNITO_POOL_ID, "Logins": logins})
        identity = ident["IdentityId"]
        open_id = await self._cognito("GetOpenIdToken", {"IdentityId": identity, "Logins": logins})
        creds = await self._cognito(
            "GetCredentialsForIdentity",
            {"IdentityId": identity, "Logins": {"cognito-identity.amazonaws.com": open_id["Token"]}},
        )
        c = creds["Credentials"]
        return AWSCreds(
            access_key=c["AccessKeyId"],
            secret_key=c["SecretKey"],
            session_token=c["SessionToken"],
            expiration=parse_expiration(c.get("Expiration")),
        )
