"""Constants for the PRIMAGAS integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "primagas"

CONF_CUSTOMER_NUMBER: Final = "customer_number"
CONF_SCAN_INTERVAL_HOURS: Final = "scan_interval_hours"

DEFAULT_SCAN_INTERVAL_HOURS: Final = 6
MIN_SCAN_INTERVAL_HOURS: Final = 1
MAX_SCAN_INTERVAL_HOURS: Final = 24
DEFAULT_SCAN_INTERVAL: Final = timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS)

# Azure AD B2C used by kunden.primagas.de
B2C_HOST: Final = "https://login.primagas.de"
B2C_TENANT: Final = "depgprodaadb2c.onmicrosoft.com"
B2C_POLICY: Final = "B2C_1A_SignInOrSignUp"
B2C_CLIENT_ID: Final = "15f4b687-8555-413c-bafd-acb38cff6837"
B2C_REDIRECT_URI: Final = "https://kunden.primagas.de/api/auth/callback/azureadb2c"
B2C_SCOPE: Final = " ".join(
    (
        "offline_access",
        "openid",
        "profile",
        "https://depgprodaadb2c.onmicrosoft.com/customer-portal/customer-portal-api",
        "https://depgprodaadb2c.onmicrosoft.com/customer-portal/customer-portal-identity-api",
        "https://depgprodaadb2c.onmicrosoft.com/customer-portal/customer-portal-sitecore",
    )
)
BUSINESS_UNIT: Final = "DE-PG"

# SHV Energy API used by the customer portal frontend
API_BASE: Final = "https://api.shvenergy.com"
# Public subscription key that the customer portal web app sends with each request.
API_SUBSCRIPTION_KEY: Final = "127cab3c995c46debf6ede4612576c26"

USER_AGENT: Final = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
