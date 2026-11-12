# ADR-0008: oauth2-proxy at the ingress, behind a single AuthContext seam

## Context
Enterprise auth is required for later versions but not for the demo, and had not been done
before by the team. Streamlit offers native OIDC via `st.login()` since 1.42.

## Decision
Production auth is **oauth2-proxy at the ingress**, with identity read from the injected header
in the application's own middleware. One seam, `AuthContext{user_id, email, groups}`, produced
by a single adapter with two implementations: a dev adapter returning a fixed identity from
env, and a production adapter parsing the header. The local deploy script **simulates the
ingress with dev credentials**.

## Rationale
`st.login()` is genuinely easy but has two disqualifying properties here: it cannot customise
scopes, audience, prompt mode or PKCE parameters, which enterprise IDPs frequently require; and
it places identity inside the layer explicitly designated as disposable, while the backend is
what needs identity for rate limiting. oauth2-proxy is also the standard Kubernetes pattern the
platform team likely already runs.

**Important caveat:** `st.user` does not read proxy headers, so with oauth2-proxy the identity
is read in own middleware, not through Streamlit's API.

## Consequences
- Usage limits hang off `user_id`: `usage(user_id, day, count)`, enforced in backend
  middleware and not in the UI, so the cap survives a second browser tab.
- Secrets follow the same pattern: `pydantic-settings` over env vars, no vault client. Swapping
  to a vault later replaces one loader and touches no call site.
- Total cost of designing all three seams now: roughly one file. Each still gets its own
  deep-dive session; this decision only fixes the interfaces so those cannot conflict.
