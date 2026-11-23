"""Offline tests for the PRIMAGAS client against a fake B2C + API server."""

from __future__ import annotations

import base64
import hashlib
import json

import aiohttp
import pytest
from aiohttp import web

from custom_components.primagas import api as api_mod
from custom_components.primagas.api import PrimagasAuthError, PrimagasClient

CSRF = "csrf-token-123"
TRANS = "StateProperties=eyJUSUQiOiJ4In0"
USER = "kunde@example.org"
PASSWORD = "geheim&pass"
CUSTOMER = "1234567"

ASSET = {
    "assetType": "Tank",
    "assetId": f"{CUSTOMER}_T_1",
    "assetNumber": "T-99",
    "assetDescription": "Tank",
    "assetCapacity": 2750,
    "assetCurrentLevelPercentage": 61,
    "assetCurrentFillingVolume": 1677,
    "assetMaximumFillingVolume": 2330,
    "tankForecast": {
        "forecastDateTime": "2026-11-22T00:00:00Z",
        "estimatedCurrentFillingLevelPercentage": 60,
        "stockLeftInDays": 210,
        "predictedRunoutDate": "2027-06-20T00:00:00Z",
    },
}


def make_app(state: dict) -> web.Application:
    routes = web.RouteTableDef()
    base = "/depgprodaadb2c.onmicrosoft.com"

    @routes.get(base + "/b2c_1a_signinorsignup/oauth2/v2.0/authorize")
    async def authorize(request: web.Request) -> web.Response:
        state["challenge"] = request.query["code_challenge"]
        assert request.query["business_unit"] == "DE-PG"
        html = (
            f'<script>var SETTINGS = {{"csrf":"{CSRF}","transId":"{TRANS}"}};</script>'
        )
        resp = web.Response(text=html, content_type="text/html")
        resp.set_cookie("x-ms-cpim-trans", "t1", secure=False)
        resp.headers.add("Set-Cookie", "x-ms-cpim-csrf=ab+c/d==; path=/")
        return resp

    @routes.post(base + "/B2C_1A_SignInOrSignUp/SelfAsserted")
    async def self_asserted(request: web.Request) -> web.Response:
        form = await request.post()
        assert request.headers["X-CSRF-TOKEN"] == CSRF
        assert request.query["tx"] == TRANS
        assert request.cookies.get("x-ms-cpim-trans") == "t1"
        # B2C rejects quoted cookie values with HTTP 400
        assert "x-ms-cpim-csrf=ab+c/d==" in request.headers["Cookie"]
        ok = form["signInName"] == USER and form["password"] == PASSWORD
        return web.Response(text=json.dumps({"status": "200" if ok else "400"}))

    @routes.get(base + "/B2C_1A_SignInOrSignUp/api/CombinedSigninAndSignup/confirmed")
    async def confirmed(request: web.Request) -> web.Response:
        raise web.HTTPFound(
            "https://kunden.primagas.de/api/auth/callback/azureadb2c?code=AUTHCODE&state=x"
        )

    @routes.post(base + "/b2c_1a_signinorsignup/oauth2/v2.0/token")
    async def token(request: web.Request) -> web.Response:
        form = await request.post()
        state.setdefault("grants", []).append(form["grant_type"])
        if form["grant_type"] == "authorization_code":
            assert form["code"] == "AUTHCODE"
            digest = hashlib.sha256(form["code_verifier"].encode()).digest()
            assert (
                base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                == state["challenge"]
            )
        elif form["refresh_token"] != "RT":
            return web.json_response({"error": "invalid_grant"}, status=400)
        claims = {"sub": "abc", "name": "Kunde"}
        if state.get("claim"):
            claims["group_scopes"] = [
                f"owner:/business-units/DE-PG/accounts/{CUSTOMER}"
            ]
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
        id_token = f"eyJhbGciOiJub25lIn0.{payload.decode()}.sig"
        return web.json_response(
            {
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "id_token": id_token,
            }
        )

    @routes.get(
        f"/customer-portals-api/v1/business-units/DE-PG/accounts/{CUSTOMER}/delivery-points"
    )
    async def points(request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer AT"
        assert request.headers["Ocp-Apim-Subscription-Key"]
        return web.json_response(
            {"results": [{"deliveryAddressId": f"{CUSTOMER}_T_1"}]}
        )

    @routes.get(
        f"/assets-api/v1/business-units/DE-PG/accounts/{CUSTOMER}/delivery-points/{CUSTOMER}_T_1/assets"
    )
    async def assets(request: web.Request) -> web.Response:
        if state.pop("expire_once", False):
            return web.Response(status=401)
        return web.json_response({"assets": [ASSET]})

    app = web.Application()
    app.add_routes(routes)
    return app


@pytest.fixture
async def fake(socket_enabled, aiohttp_server, monkeypatch):
    state: dict = {}
    server = await aiohttp_server(make_app(state))
    url = str(server.make_url("")).rstrip("/")
    monkeypatch.setattr(api_mod, "B2C_HOST", url)
    monkeypatch.setattr(api_mod, "API_BASE", url)
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True, quote_cookie=False)
    ) as session:
        yield state, session


async def test_login_and_tanks(fake) -> None:
    state, session = fake
    client = PrimagasClient(session, USER, PASSWORD, CUSTOMER)
    tanks = await client.async_get_tanks()
    tank = tanks[f"{CUSTOMER}_T_1"]
    assert tank.raw["assetCurrentLevelPercentage"] == 61
    assert tank.forecast["stockLeftInDays"] == 210
    assert state["grants"] == ["authorization_code"]
    # second call reuses the token
    await client.async_get_tanks()
    assert state["grants"] == ["authorization_code"]


async def test_expired_token_is_refreshed(fake) -> None:
    state, session = fake
    client = PrimagasClient(session, USER, PASSWORD, CUSTOMER)
    await client.async_get_tanks()
    state["expire_once"] = True
    await client.async_get_tanks()
    assert state["grants"] == ["authorization_code", "refresh_token"]


async def test_wrong_password(fake) -> None:
    _, session = fake
    client = PrimagasClient(session, USER, "falsch", CUSTOMER)
    with pytest.raises(PrimagasAuthError):
        await client.async_login()


async def test_api_error_is_not_auth_error(fake, monkeypatch) -> None:
    _, session = fake
    client = PrimagasClient(session, USER, PASSWORD, "9999999")
    with pytest.raises(api_mod.PrimagasApiError) as err:
        await client.async_get_tanks()
    assert err.value.status == 404
    assert "9999999" not in str(err.value)


async def test_customer_number_from_token(fake) -> None:
    state, session = fake
    state["claim"] = True
    client = PrimagasClient(session, USER, PASSWORD, "")
    tanks = await client.async_get_tanks()
    assert client.customer_number == CUSTOMER
    assert f"{CUSTOMER}_T_1" in tanks


async def test_customer_number_missing_in_token(fake) -> None:
    _, session = fake
    client = PrimagasClient(session, USER, PASSWORD, "")
    with pytest.raises(api_mod.PrimagasCustomerNumberError):
        await client.async_login()


def test_find_customer_number_from_group_scopes() -> None:
    claims = {"group_scopes": ["owner:/business-units/DE-PG/accounts/123456"]}
    assert api_mod.find_customer_number(claims) == "123456"
    assert api_mod.find_customer_number({"sub": "x"}) is None


async def test_token_account_wins_over_entered_number(fake) -> None:
    state, session = fake
    state["claim"] = True
    client = PrimagasClient(session, USER, PASSWORD, "00000000")
    await client.async_login()
    assert client.customer_number == CUSTOMER
