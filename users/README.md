# rag-users

Kleine Bibliothek für den Chat: **wer fragt** und **was gilt für ihn**. Kein eigener Dienst, kein I/O.

## Wer fragt

Zwei Wege, gewählt mit `USERS__ADAPTER`:

| Wert | Wofür | Woher kommt der Benutzer |
|---|---|---|
| `env` | lokal | ein fester Test-Benutzer: `USERS__DEV_USER` (Standard `dev`) |
| `header` | hinter dem Anmelde-Proxy (PAG, oauth2-proxy) | aus den Headern der Anfrage |

Mit `header` gilt: fehlt der Benutzer-Header, wird die Anfrage abgelehnt. Es gibt keinen Ersatz-Benutzer.
Gespräche werden pro Benutzerkennung gespeichert; ein neuer Benutzer beginnt leer.

## Was gilt

Für alle Benutzer gleich: alle Handbücher, kein Tageslimit, ein Gespräch endet nach `USERS__MAX_TURNS` Runden
(Standard 10). Gruppen aus dem Header werden gelesen, haben aber keine Wirkung.

## Einstellungen (`USERS__*`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `USERS__ADAPTER` | `env` | `env` oder `header` |
| `USERS__DEV_USER` | `dev` | Name des Test-Benutzers bei `env` |
| `USERS__HEADER_USER` | `X-Forwarded-User` | Header mit der Benutzerkennung |
| `USERS__HEADER_EMAIL` | `X-Forwarded-Email` | Header mit der E-Mail (optional) |
| `USERS__HEADER_GROUPS` | `X-Forwarded-Groups` | Header mit den Gruppen (optional, ohne Wirkung) |
| `USERS__MAX_TURNS` | `10` | Runden pro Gespräch |
| `USERS__DAILY_MESSAGES` | nicht gesetzt | Tageslimit pro Benutzer; nicht gesetzt = kein Limit |

## Benutzung

```python
from rag_users import get_adapter, get_policy, get_settings

ctx = get_adapter(get_settings(), headers=request_headers).current()   # AuthContext(user_id, email, groups)
policy = get_policy()                                                  # Grenzen aus USERS__*
```

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m rag_users        # zeigt Adapter, Benutzer und Grenzen
.venv/bin/pytest -q                  # 40 Tests
```

Die Klasse `Policy` kann weiterhin Regeln pro Gruppe (Tageslimit, erlaubte Handbücher) auswerten, wenn man ihr
welche übergibt. Die Anwendung nutzt das nicht.
