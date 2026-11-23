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
| Status, Letzte erfolgreiche Abfrage | Diagnose, siehe unten |

Außerdem gibt es pro Tank den Button **Jetzt abrufen**. Er holt die Daten sofort,
unabhängig vom Intervall, und funktioniert auch, wenn die letzte Abfrage
fehlgeschlagen ist. Zum Schutz des Portals ist höchstens eine Abfrage pro Minute
möglich.

## Status-Entität (Fehlersuche)

Unter *Diagnose* zeigt **Status**, wie die letzte Abfrage ausgegangen ist. Die
Entität bleibt auch bei Störungen verfügbar. Die übrigen Sensoren werden dann
„nicht verfügbar“, **Letzte erfolgreiche Abfrage** zeigt, wie alt die Werte sind.

| Status | Bedeutung | Was tun? |
|---|---|---|
| OK | Daten wurden abgerufen. | – |
| Anmeldung abgelehnt | PRIMAGAS hat E-Mail oder Passwort abgelehnt. | HA fordert zur erneuten Anmeldung auf. Passwort prüfen, z. B. nach einer Änderung im Portal. |
| Störung beim PRIMAGAS-Login | Die Login-Seite hat einen Fehler oder eine unerwartete Antwort geliefert. | Meist eine Störung bei PRIMAGAS. Geht es auch auf kunden.primagas.de nicht, abwarten. Bleibt der Fehler, hat sich vermutlich der Login geändert: Issue anlegen. |
| PRIMAGAS-Daten nicht verfügbar | Die Daten-API von PRIMAGAS antwortet mit HTTP 5xx oder 429. | Störung oder Wartung bei PRIMAGAS. Abwarten, die Integration versucht es beim nächsten Intervall erneut. |
| Datenabruf abgelehnt | Login ok, aber die Daten-API lehnt die Anfrage ab (HTTP 4xx). | Kundennummer prüfen. Bleibt der Fehler, hat sich vermutlich die Schnittstelle geändert: Issue anlegen. |
| Keine Verbindung | Netzwerkfehler oder Zeitüberschreitung. | Internetverbindung und DNS von Home Assistant prüfen. |
| Keine Tanks gefunden | Das Konto enthält keinen Tank. | Im Portal prüfen, ob der Tank dort angezeigt wird. |
| Fehler in der Integration | Ein unerwarteter Fehler in dieser Integration. | Debug-Log einschalten (siehe unten) und ein Issue mit dem Log anlegen. |

Attribute der Status-Entität:

| Attribut | Inhalt |
|---|---|
| Fehlermeldung | Kurzer Fehlertext (ohne Zugangsdaten, Kundennummer ausgeblendet) |
| HTTP-Status | HTTP-Code der Fehlerantwort, falls vorhanden |
| Letzter Versuch / Letzter Erfolg / Nächste Abfrage | Zeitpunkte der Abfragen |
| Fehlversuche in Folge | Wird nach einer erfolgreichen Abfrage auf 0 gesetzt |
| Abfrageintervall (h) | Eingestelltes Intervall |

Beispiel für eine Benachrichtigung, wenn die Abfrage seit drei Versuchen scheitert:

```yaml
automation:
  - alias: PRIMAGAS Abfrage gestört
    triggers:
      - trigger: numeric_state
        entity_id: sensor.gastank_status
        attribute: consecutive_failures
        above: 2
    actions:
      - action: notify.notify
        data:
          message: "PRIMAGAS: {{ states('sensor.gastank_status') }} – {{ state_attr('sensor.gastank_status', 'error') }}"
```

Die Entitäts-ID hängt vom Namen deines Tanks ab.

## Installation

### HACS
[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=endrei&repository=ha-primagas&category=integration)

Bis die Integration im HACS-Standardkatalog ist, als benutzerdefiniertes Repository:
1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/endrei/ha-primagas`, Typ *Integration*.
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
