# auth-test

Two tools for the login in front of the chat (OAM → oauth2-proxy → app, see ADR-0008).

| File | What it answers | Where to run |
|---|---|---|
| `compose.yaml` + `run-test.sh` | Which headers does an app behind oauth2-proxy 7.15.5 receive? | any machine with Docker/Podman |
| `inspect-auth-chart.sh` | How does the org chart `cc-r444-core-auth` configure oauth2-proxy (headers, claims, mesh authz, Vault)? | the org VM (needs the Artifactory registry) |

## Header test

Dex plays OAM (user `max.muster@example.org` / `password`, user ID `u1234567`), `whoami` plays the app and prints the
headers it receives.

```bash
./run-test.sh          # starts the stack, logs in with curl, prints the headers
docker compose down
```

Browser instead of curl: `docker compose up -d`, open http://localhost:4180. Behind a registry mirror, set
`DEX_IMAGE`, `OAUTH2_PROXY_IMAGE`, `WHOAMI_IMAGE`; with SELinux enforcing, `SELINUX_LABEL=,Z`.

Result 2026-11-05 (default oauth2-proxy flags):

| Header | Value | Source |
|---|---|---|
| `X-Forwarded-User` | `Cgh1MTIzNDU2NxIFbG9jYWw` | the ID token's `sub` claim (Dex encodes user ID `u1234567` + connector in it) |
| `X-Forwarded-Email` | `max.muster@example.org` | `email` claim |
| `X-Forwarded-Groups` | absent | the token has no `groups` claim |
| `Cookie: _oauth2_proxy=…` | session cookie | passed through to the app |

A client sending its own `X-Forwarded-User`/`-Email` gets them overwritten. Without a session the proxy redirects to
the login (302) and the app is never reached.

## Chart inspection (org VM)

```bash
REG_USER=<your user> ./inspect-auth-chart.sh oci://<artifactory>/<path>/cc-r444-core-auth <version>
# no helm installed: runs helm from a container; behind the mirror add HELM_IMAGE=<artifactory mirror>/alpine/helm:3.19.0
```

Read-only: it pulls the chart into `./auth-chart/`, renders it with default values and writes `auth-chart/summary.txt`
(Chart.yaml, rendered object kinds, every line about headers, claims, upstream, callback, mesh authz, Vault, images).
