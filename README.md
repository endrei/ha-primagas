<img src="icon.png" alt="" width="96" align="right">

# PRIMAGAS für Home Assistant

Inoffizielle Custom Integration, die sich im PRIMAGAS-Kundenportal
([kunden.primagas.de](https://kunden.primagas.de)) anmeldet und den Füllstand
deines Flüssiggastanks als Sensoren in Home Assistant bereitstellt.

> Diese Integration ist kein Produkt von PRIMAGAS und steht in keiner Verbindung zu
> PRIMAGAS oder SHV Energy. „PRIMAGAS“ ist eine Marke ihres Inhabers und wird hier
> nur genannt, um den Dienst zu bezeichnen. Sie nutzt dieselbe
> Schnittstelle wie das Kundenportal. PRIMAGAS kann diese Schnittstelle jederzeit
> ändern.

## Sensoren (pro Tank)

| Sensor | Einheit |
|---|---|
| Füllstand | % |
| Füllmenge | l |
| Geschätzter Füllstand (Prognose) | % |
| Reichweite | Tage |
| Voraussichtlich leer am | Datum |
| Nächste Bestellung | Datum |
| Voraussichtliche Liefermenge (Prognose von PRIMAGAS für die nächste Befüllung) | l |
| Stand der Prognose, Tankvolumen, Maximale Füllmenge | Diagnose |

## Installation

### HACS (benutzerdefiniertes Repository)
1. HACS → ⋮ → *Benutzerdefinierte Repositories* → URL dieses Repositories, Typ *Integration*.
2. „PRIMAGAS“ installieren und Home Assistant neu starten.

### Manuell
Den Ordner `custom_components/primagas` nach `<config>/custom_components/primagas`
kopieren und Home Assistant neu starten.

## Einrichtung
*Einstellungen → Geräte & Dienste → Integration hinzufügen → PRIMAGAS*

- **E-Mail-Adresse** und **Passwort** vom Kundenportal
- **Kundennummer** (optional): Lass sie leer, dann sucht die Integration sie nach der Anmeldung selbst. Klappt das nicht, fragt HA danach. Sie steht auf der Rechnung und im Portal.

Das Abfrageintervall (Standard 6 Stunden) lässt sich unter *Konfigurieren* ändern.
PRIMAGAS aktualisiert die Daten ohnehin nur ein- bis zweimal am Tag.

## Sicherheit
- Die Zugangsdaten werden nur in der Konfiguration von Home Assistant gespeichert
  (`.storage/core.config_entries`), nicht in YAML.
- Sie werden ausschließlich per HTTPS an `login.primagas.de` (Azure AD B2C von
  PRIMAGAS/SHV Energy) gesendet. Danach arbeitet die Integration mit dem
  Zugriffstoken und erneuert es über das Refresh-Token.
- Passwort, Token und Kundennummer erscheinen nicht im Log. In den
  Diagnosedaten sind sie geschwärzt.
- Die Integration nutzt eine eigene HTTP-Sitzung, damit die Login-Cookies nicht
  mit anderen Integrationen geteilt werden.
- Wird das Passwort im Portal geändert, fordert Home Assistant zur erneuten
  Anmeldung auf.

Tipp: Sichere dein Home Assistant selbst ab (Backups verschlüsseln, Zugriff
auf das `config`-Verzeichnis beschränken), denn dort liegen alle Zugangsdaten
deiner Integrationen.

## Technik
- Login: OAuth2 Authorization Code Flow mit PKCE gegen Azure AD B2C
  (`login.primagas.de`, Policy `B2C_1A_SignInOrSignUp`).
- Daten: `api.shvenergy.com` (`assets-api`, Business Unit `DE-PG`).
- Danke an [Trickfilm400/primagas-api](https://github.com/Trickfilm400/primagas-api)
  (MIT) für die Dokumentation des Login-Ablaufs.

## Fehlersuche
```yaml
logger:
  logs:
    custom_components.primagas: debug
```

## Lizenz
MIT, siehe [LICENSE](LICENSE).
