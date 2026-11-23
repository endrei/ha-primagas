"""Async client for the PRIMAGAS customer portal (kunden.primagas.de).

The portal signs users in through Azure AD B2C (OAuth2 authorization code
flow with PKCE) and reads its data from the SHV Energy JSON API. This client
performs the same steps as the portal's login page. It never logs the
password or any token.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

try:  # inside Home Assistant
    from homeassistant.util.ssl import get_default_context
except ImportError:  # standalone use (diagnose script)
    import ssl

    def get_default_context() -> ssl.SSLContext:
        return ssl.create_default_context()


from .const import (
    API_BASE,
    API_SUBSCRIPTION_KEY,
    B2C_CLIENT_ID,
    B2C_HOST,
    B2C_POLICY,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
    B2C_TENANT,
    BUSINESS_UNIT,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
_CSRF_RE = re.compile(r'"csrf"\s*:\s*"(?P<v>[^"]+)"')
_TRANS_RE = re.compile(r'"transId"\s*:\s*"(?P<v>StateProperties=[^"]+)"')
_CODE_RE = re.compile(r"[?&#]code=(?P<v>[^&\"'#\s]+)")


class PrimagasError(Exception):
    """Base error."""


class PrimagasAuthError(PrimagasError):
    """Credentials were rejected or the session cannot be renewed."""


class PrimagasConnectionError(PrimagasError):
    """Network problem or unexpected answer from the portal."""


class PrimagasPortalError(PrimagasConnectionError):
    """The PRIMAGAS login answered with an error or an unexpected page."""


class PrimagasCustomerNumberError(PrimagasError):
    """The customer number could not be found automatically."""


class PrimagasApiError(PrimagasError):
    """Login worked, but the data API refused the request."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def _snippet(text: str, limit: int = 300) -> str:
    """Shorten a server answer for logging (answers never contain the password)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", "<jwt>", text)
    return text[:limit]


@dataclass
class TokenSet:
    """OAuth tokens as returned by Azure AD B2C."""

    access_token: str
    refresh_token: str | None
    expires_at: float
    id_token: str | None = None

    @property
    def valid(self) -> bool:
        return time.time() < self.expires_at - 120

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> TokenSet:
        if "access_token" not in data:
            raise PrimagasAuthError("Token response without access_token")
        if "expires_on" in data:
            expires_at = float(data["expires_on"])
        else:
            expires_at = time.time() + float(data.get("expires_in", 3600))
        return cls(
            data["access_token"],
            data.get("refresh_token"),
            expires_at,
            data.get("id_token"),
        )


@dataclass
class Tank:
    """One gas tank of a delivery point."""

    asset_id: str
    delivery_point_id: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def forecast(self) -> dict[str, Any]:
        return self.raw.get("tankForecast") or {}


def create_session() -> aiohttp.ClientSession:
    """Create a dedicated HTTP session with its own cookie jar.

    The B2C login sets cookies, so the client must not use Home Assistant's
    shared session. The caller closes the session when done.
    """
    return aiohttp.ClientSession(
        # B2C cookie values contain "+", "/" and "=". aiohttp would wrap such
        # values in quotes, which B2C rejects with HTTP 400.
        cookie_jar=aiohttp.CookieJar(quote_cookie=False),
        connector=aiohttp.TCPConnector(ssl=get_default_context()),
    )


def jwt_claims(token: str | None) -> dict[str, Any]:
    """Decode the payload of a JWT without checking the signature."""
    if not token or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return claims if isinstance(claims, dict) else {}


_CUSTOMER_CLAIM_RE = re.compile(r"customer|account|kunde|debitor", re.IGNORECASE)
_CUSTOMER_VALUE_RE = re.compile(r"^\d{5,12}$")


_ACCOUNT_SCOPE_RE = re.compile(
    rf"/business-units/{BUSINESS_UNIT}/accounts/(?P<v>[A-Za-z0-9]+)"
)


def find_customer_number(claims: dict[str, Any]) -> str | None:
    """Pick the customer number out of the token claims.

    PRIMAGAS puts it into ``group_scopes``, for example
    ``owner:/business-units/DE-PG/accounts/123456``.
    """
    for value in claims.values():
        for item in value if isinstance(value, list) else [value]:
            match = _ACCOUNT_SCOPE_RE.search(str(item))
            if match:
                return match.group("v")
    for key, value in claims.items():
        if not _CUSTOMER_CLAIM_RE.search(key):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item).strip()
            if _CUSTOMER_VALUE_RE.match(text):
                return text
    return None


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class PrimagasClient:
    """Minimal client for the data the integration needs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        customer_number: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self.customer_number = customer_number.strip()
        self._tokens: TokenSet | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ auth

    @property
    def _b2c_base(self) -> str:
        return f"{B2C_HOST}/{B2C_TENANT}"

    async def async_login(self) -> None:
        """Run the complete B2C sign-in and store fresh tokens."""
        self._session.cookie_jar.clear()
        verifier, challenge = _pkce_pair()
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"}

        # 1. Authorize: returns the login page with csrf token and transaction id
        params = {
            "client_id": B2C_CLIENT_ID,
            "scope": B2C_SCOPE,
            "response_type": "code",
            "redirect_uri": B2C_REDIRECT_URI,
            "business_unit": BUSINESS_UNIT,
            "ui_locales": "de-DE",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        page = await self._request_text(
            "GET",
            f"{self._b2c_base}/{B2C_POLICY.lower()}/oauth2/v2.0/authorize",
            params=params,
            headers=headers,
        )
        csrf_match = _CSRF_RE.search(page)
        trans_match = _TRANS_RE.search(page)
        if not csrf_match or not trans_match:
            _LOGGER.warning(
                "PRIMAGAS login step 1 (authorize): login page has an unexpected "
                "format (csrf found: %s, transId found: %s)",
                bool(csrf_match),
                bool(trans_match),
            )
            raise PrimagasPortalError("Login page has an unexpected format")
        _LOGGER.debug("PRIMAGAS login step 1 (authorize) ok")
        # The login page's own script sends these with every request.
        headers = {**headers, "Origin": B2C_HOST, "Referer": f"{B2C_HOST}/"}
        csrf = csrf_match.group("v")
        trans_id = trans_match.group("v")

        # 2. SelfAsserted: submit the credentials like the login form does
        body = await self._request_text(
            "POST",
            f"{self._b2c_base}/{B2C_POLICY}/SelfAsserted",
            params={"tx": trans_id, "p": B2C_POLICY},
            data={
                "request_type": "RESPONSE",
                "signInName": self._username,
                "password": self._password,
            },
            headers={
                **headers,
                "X-CSRF-TOKEN": csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        try:
            answer = json.loads(body)
            status = str(answer.get("status"))
        except (ValueError, AttributeError) as err:
            _LOGGER.warning(
                "PRIMAGAS login step 2 (credentials): unexpected answer: %s",
                _snippet(body),
            )
            raise PrimagasPortalError("Unexpected sign-in answer") from err
        if status != "200":
            _LOGGER.warning(
                "PRIMAGAS login step 2 (credentials) rejected: status=%s "
                "errorCode=%s message=%s",
                status,
                answer.get("errorCode"),
                _snippet(str(answer.get("message", ""))),
            )
            raise PrimagasAuthError(
                f"Login rejected: {answer.get('message') or status}"
            )
        _LOGGER.debug("PRIMAGAS login step 2 (credentials) ok")

        # 3. Confirmed: B2C redirects to the portal with the authorization code
        try:
            async with self._session.get(
                f"{self._b2c_base}/{B2C_POLICY}/api/CombinedSigninAndSignup/confirmed",
                params={
                    "rememberMe": "false",
                    "csrf_token": csrf,
                    "tx": trans_id,
                    "p": B2C_POLICY,
                },
                headers=headers,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                location = resp.headers.get("Location", "")
                text = await resp.text() if not location else ""
                confirm_status = resp.status
        except (TimeoutError, aiohttp.ClientError) as err:
            raise PrimagasConnectionError("Cannot reach PRIMAGAS login") from err

        code = parse_qs(urlparse(location).query).get("code", [None])[0]
        if not code:
            match = _CODE_RE.search(location or text)
            code = match.group("v") if match else None
        if not code:
            _LOGGER.warning(
                "PRIMAGAS login step 3 (confirm): no authorization code "
                "(HTTP %s, redirect to %s, answer: %s)",
                confirm_status,
                urlparse(location).netloc + urlparse(location).path
                if location
                else "-",
                _snippet(text),
            )
            raise PrimagasPortalError("No authorization code received")
        _LOGGER.debug("PRIMAGAS login step 3 (confirm) ok")

        # 4. Token: exchange the code
        data = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": B2C_REDIRECT_URI,
                "code_verifier": verifier,
                "scope": B2C_SCOPE,
            }
        )
        self._tokens = TokenSet.from_response(data)
        self._session.cookie_jar.clear()
        self._detect_customer_number()
        _LOGGER.debug("Signed in to PRIMAGAS customer portal")

    def _detect_customer_number(self) -> None:
        assert self._tokens is not None
        claims = {
            **jwt_claims(self._tokens.access_token),
            **jwt_claims(self._tokens.id_token),
        }
        number = find_customer_number(claims)
        if number:
            if self.customer_number and self.customer_number != number:
                _LOGGER.warning(
                    "PRIMAGAS: the entered customer number differs from the "
                    "account in the login token, using the account from the token"
                )
            _LOGGER.debug("PRIMAGAS customer number found in the login token")
            self.customer_number = number
            return
        if self.customer_number:
            _LOGGER.debug("PRIMAGAS: no account in token, using entered number")
            return
        # Only the claim names are logged, never their values.
        _LOGGER.warning(
            "PRIMAGAS: customer number not found in the login token. Claim names: %s",
            ", ".join(sorted(claims)),
        )
        raise PrimagasCustomerNumberError("Customer number not found in token")

    async def _request_text(self, method: str, url: str, **kwargs: Any) -> str:
        try:
            async with self._session.request(
                method, url, timeout=REQUEST_TIMEOUT, **kwargs
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    _LOGGER.warning(
                        "PRIMAGAS login request %s %s answered HTTP %s "
                        "(cookies sent: %s): %s",
                        method,
                        urlparse(url).path,
                        resp.status,
                        ", ".join(c.key for c in self._session.cookie_jar) or "-",
                        _snippet(text),
                    )
                    raise PrimagasPortalError(f"PRIMAGAS login answered {resp.status}")
                return text
        except PrimagasError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning(
                "PRIMAGAS login request %s %s failed: %r",
                method,
                urlparse(url).path,
                err,
            )
            raise PrimagasConnectionError("Cannot reach PRIMAGAS login") from err

    async def _async_refresh(self) -> bool:
        if not self._tokens or not self._tokens.refresh_token:
            return False
        try:
            data = await self._token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self._tokens.refresh_token,
                    "scope": B2C_SCOPE,
                }
            )
            self._tokens = TokenSet.from_response(data)
        except PrimagasError:
            _LOGGER.debug("Token refresh failed, signing in again")
            return False
        return True

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        basic = base64.b64encode(f"{B2C_CLIENT_ID}:".encode()).decode()
        try:
            async with self._session.post(
                f"{self._b2c_base}/{B2C_POLICY.lower()}/oauth2/v2.0/token",
                data=form,
                headers={"Authorization": f"Basic {basic}", "User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    _LOGGER.warning(
                        "PRIMAGAS token request (%s) answered HTTP %s: %s",
                        form.get("grant_type"),
                        resp.status,
                        _snippet(body),
                    )
                    if resp.status in (400, 401):
                        raise PrimagasAuthError(
                            f"Token endpoint answered {resp.status}"
                        )
                    raise PrimagasPortalError(f"Token endpoint answered {resp.status}")
                return await resp.json(content_type=None)
        except PrimagasError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            _LOGGER.warning("PRIMAGAS token request failed: %r", err)
            raise PrimagasConnectionError("Token request failed") from err

    async def _async_ensure_token(self, force: bool = False) -> str:
        async with self._lock:
            if force or not self._tokens or not self._tokens.valid:
                if not await self._async_refresh():
                    await self.async_login()
            assert self._tokens is not None
            return self._tokens.access_token

    # ------------------------------------------------------------------ data

    async def _api_get(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        for attempt in (1, 2):
            token = await self._async_ensure_token(force=attempt == 2)
            try:
                async with self._session.get(
                    f"{API_BASE}{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Ocp-Apim-Subscription-Key": API_SUBSCRIPTION_KEY,
                        "Accept": "application/json",
                        "User-Agent": USER_AGENT,
                    },
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        _LOGGER.debug("PRIMAGAS API answered 401, renewing token")
                        continue
                    if resp.status >= 400:
                        body = await resp.text()
                        safe_path = self._mask(path)
                        _LOGGER.warning(
                            "PRIMAGAS API GET %s answered HTTP %s: %s",
                            safe_path,
                            resp.status,
                            self._mask(_snippet(body)),
                        )
                        raise PrimagasApiError(
                            f"API answered {resp.status} for {safe_path}", resp.status
                        )
                    return await resp.json(content_type=None)
            except PrimagasError:
                raise
            except (TimeoutError, aiohttp.ClientError, ValueError) as err:
                _LOGGER.warning("PRIMAGAS API request failed: %r", err)
                raise PrimagasConnectionError("API request failed") from err
        raise PrimagasConnectionError("unreachable")

    def _mask(self, text: str) -> str:
        if not self.customer_number:
            return text
        return text.replace(self.customer_number, "<kdnr>")

    async def async_get_delivery_points(self) -> list[dict[str, Any]]:
        data = await self._api_get(
            f"/customer-portals-api/v1/business-units/{BUSINESS_UNIT}"
            f"/accounts/{self.customer_number}/delivery-points"
        )
        return list(data.get("results") or [])

    async def async_get_tanks(self) -> dict[str, Tank]:
        """Return all tanks of the account, keyed by asset id."""
        try:
            points = await self.async_get_delivery_points()
            point_ids = [
                p["deliveryAddressId"] for p in points if p.get("deliveryAddressId")
            ]
        except PrimagasAuthError:
            raise
        except PrimagasError as err:
            _LOGGER.debug("Delivery points not available (%s), using default id", err)
            point_ids = []
        if not point_ids:
            # Pattern used by the portal for single-tank customers
            point_ids = [f"{self.customer_number}_T_1"]

        tanks: dict[str, Tank] = {}
        for point_id in point_ids:
            data = await self._api_get(
                f"/assets-api/v1/business-units/{BUSINESS_UNIT}/accounts/"
                f"{self.customer_number}/delivery-points/{point_id}/assets",
                params={"$filter": "(assetType eq 'tank')"},
            )
            for asset in data.get("assets") or []:
                asset_id = str(asset.get("assetId") or point_id)
                tanks[asset_id] = Tank(asset_id, point_id, asset)
        return tanks

    async def async_validate(self) -> None:
        """Sign in and read the account once (used by the config flow)."""
        await self.async_login()
        await self.async_get_tanks()
