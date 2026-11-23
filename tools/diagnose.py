#!/usr/bin/env python3
"""Test the PRIMAGAS login outside Home Assistant.

Usage:  pip3 install aiohttp
        python3 tools/diagnose.py

The script asks for e-mail, password and customer number in the terminal.
Nothing is stored and the password is never printed.
"""

from __future__ import annotations

import asyncio
import getpass
import importlib.util
import logging
import sys
import types
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "primagas"


def _load_api():
    # Load const.py and api.py without the Home Assistant parts of the package.
    pkg = types.ModuleType("primagas_standalone")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["primagas_standalone"] = pkg
    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(
            f"primagas_standalone.{name}", PKG_DIR / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules["primagas_standalone.api"]


async def main() -> int:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    for noisy in ("asyncio",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    api = _load_api()

    username = input("E-Mail: ").strip()
    password = getpass.getpass("Passwort (wird nicht angezeigt): ")
    customer = input("Kundennummer (leer = automatisch suchen): ").strip()

    async with api.create_session() as session:
        client = api.PrimagasClient(session, username, password, customer)
        try:
            await client.async_login()
            print("\n✓ Anmeldung erfolgreich, Kundennummer:", client.customer_number)
            tanks = await client.async_get_tanks()
        except api.PrimagasError as err:
            print(f"\n✗ Fehler: {type(err).__name__}: {err}")
            return 1
    print(f"✓ {len(tanks)} Tank(s) gefunden")
    for tank in tanks.values():
        raw, fc = tank.raw, tank.forecast
        print(
            f"  Füllstand {raw.get('assetCurrentLevelPercentage')} %, "
            f"{raw.get('assetCurrentFillingVolume')} l von {raw.get('assetCapacity')} l, "
            f"Reichweite {fc.get('stockLeftInDays')} Tage"
        )
        print(f"  Vorhandene Felder: {', '.join(sorted(raw))}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
