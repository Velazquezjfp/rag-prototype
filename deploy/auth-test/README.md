# auth-test

Zwei Werkzeuge für die Anmeldung vor dem Chat (OAM → oauth2-proxy → App, siehe ADR-0008).

| Datei | Frage | Wo ausführen |
|---|---|---|
| `compose.yaml` + `run-test.sh` | Welche Header bekommt eine App hinter oauth2-proxy 7.15.5? | jeder Rechner mit Docker oder Podman |
| `inspect-auth-chart.sh` | Wie stellt das Chart `cc-r444-core-auth` den oauth2-proxy ein (Header, Claims, Regeln im Service Mesh, Vault)? | die VM im Firmennetz (braucht die Registry in Artifactory) |

## Header-Test

Dex spielt OAM (Benutzer `max.muster@example.org` / `password`, Benutzer-ID `u1234567`). `whoami` spielt die App
und gibt die Header aus, die bei ihr ankommen.

```bash
./run-test.sh          # startet alles, meldet sich mit curl an, zeigt die Header
docker compose down
```

Im Browser statt mit curl: `docker compose up -d`, dann http://localhost:4180. Hinter einem Registry-Spiegel
`DEX_IMAGE`, `OAUTH2_PROXY_IMAGE` und `WHOAMI_IMAGE` setzen; mit SELinux `SELINUX_LABEL=,Z`.

Ergebnis vom 2026-11-05 (oauth2-proxy mit Standard-Einstellungen):

| Header | Wert | Herkunft |
|---|---|---|
| `X-Forwarded-User` | `Cgh1MTIzNDU2NxIFbG9jYWw` | Claim `sub` des ID-Tokens (Dex kodiert darin die Benutzer-ID `u1234567` und den Connector) |
| `X-Forwarded-Email` | `max.muster@example.org` | Claim `email` |
| `X-Forwarded-Groups` | fehlt | das Token hat keinen Claim `groups` |
| `Cookie: _oauth2_proxy=…` | Sitzungs-Cookie | wird an die App durchgereicht |

Schickt ein Client eigene `X-Forwarded-User` oder `-Email`, überschreibt der Proxy sie. Ohne Sitzung leitet der
Proxy zur Anmeldung um (302); die App wird nicht erreicht.

Für den Chat: `USERS__HEADER_USER` legt fest, welcher Header die Benutzerkennung trägt. Welcher es im Zielsystem
ist, steht noch offen ([`docs/OFFENE-PUNKTE.md`](../../docs/OFFENE-PUNKTE.md), Punkt 6).

## Chart ansehen (VM im Firmennetz)

```bash
REG_USER=<benutzer> ./inspect-auth-chart.sh oci://<artifactory>/<pfad>/cc-r444-core-auth <version>
# ohne helm auf dem Rechner: das Skript startet helm in einem Container;
# hinter dem Spiegel dazu HELM_IMAGE=<artifactory-spiegel>/alpine/helm:3.19.0 setzen
```

Das Skript ändert nichts. Es lädt das Chart nach `./auth-chart/`, rendert es mit den Standardwerten und schreibt
`auth-chart/summary.txt`: Chart.yaml, Arten der Objekte und alle Zeilen zu Headern, Claims, Upstream, Callback,
Mesh-Regeln, Vault und Images.
