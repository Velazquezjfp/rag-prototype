# rag-users — module 4: who is asking, and what they may do (mock)

The auth/policy seam of the prototype, shaped exactly like SPEC §10.2 and ADR-0008 describe it and **mocked** where
the SPEC says the real thing comes later: one `AuthContext{user_id, email, groups}` produced by a single adapter with
two implementations (a dev adapter that returns a fixed identity from the environment, and the production adapter
that reads the headers oauth2-proxy injects at the ingress), a hardcoded user directory, and a `Policy` that turns a
user's groups into limits: the SPEC's **10 messages per user per day**, a **turn cap per conversation** (the hard cap
ADR-0011 puts in place of compaction) and — as an **addition beyond SPEC §10.2** — the **manuals a group may read**
(`allowed_doc_ids`), which flows into retrieval as the `doc_ids` filter.

The module is a pure library ("roughly one file", as ADR-0008 estimated), does no I/O and imports none of the other
modules. Usage *counting* is deliberately not here: `UsageStore` is the protocol chat-system's database implements,
so the daily cap is enforced in the backend and survives a second browser tab (SPEC §10.2).

Verified 2026-09-04: 39 unit tests green (`make test`), ruff clean; the effective document filter of the read-only
user was pushed through the live retrieval module (`rag-retrieve ask … --doc BHB-PLT-0007`) and only ZSD sources came
back — see [`REPORT.md`](REPORT.md).

## What is mocked, and what is real

| Piece | State | Swapping it later |
|---|---|---|
| `AuthContext`, `AuthAdapter` protocol | real seam (SPEC §10.2) | stays |
| `EnvAuthAdapter` | real dev adapter: identity by name from `USERS` | stays for local runs |
| `HeaderAuthAdapter` | real production adapter for oauth2-proxy headers (`X-Forwarded-User/-Email/-Groups`) | header names are settings; nothing else to change |
| `USERS` directory | **mock** — four hardcoded users | the header adapter never consults it; with a real IdP the directory simply becomes unused |
| `RULES`, `DEFAULT_LIMITS` | **mock policy data** — three groups | move to a config file or the IdP's claims; `Policy(rules=…)` takes any mapping |
| `allowed_doc_ids` | **addition beyond SPEC §10.2** (user decision 2026-09-04) | drop the field or set it to `None` everywhere to get the SPEC's behaviour back |
| `UsageStore` | protocol only; `MemoryUsageStore` for tests | chat-system implements it on its `usage(user_id, day, count)` table |

## The mock directory and rules

| user | e-mail | groups | messages/day | turns/conversation | manuals |
|---|---|---|---|---|---|
| `dev` | dev@bavd.example | bavd-ops | 10 | 10 | all |
| `otto.ops` | otto.ops@bavd.example | bavd-ops | 10 | 10 | all |
| `rita.read` | rita.read@bavd.example | bavd-readonly | 5 | 5 | `BHB-PLT-0007` (ZSD) only |
| `anna.admin` | anna.admin@bavd.example | admin, bavd-ops | 100 | 20 | all |

Group rules: `admin` (100 / 20 / all), `bavd-ops` (10 / 10 / all), `bavd-readonly` (5 / 5 / ZSD only). A user in several
groups gets the most permissive value of every field (`None` = "all manuals" wins; restricted lists are unioned).
Groups without a rule grant nothing: a user whose only groups are unknown gets `DEFAULT_LIMITS` (10 / 10 / all,
the SPEC figure), and an unknown group next to `bavd-readonly` does not widen the read-only limits.

`python -m rag_users` prints this table together with the adapter `USERS__*` currently selects and the user it
resolves to (`make show`); `--json` for machines (`chat-doctor` uses it).

## Quick start

```bash
cd users
make dev                    # standalone .venv; chat-system normally installs this package into its own venv (-e ../users)
make test && make lint      # 39 tests, no services
make show                   # directory, rules, resolved limits, current adapter/user
USERS__DEV_USER=rita.read make show
```

## Library API (what chat-system uses)

```python
from datetime import date
from rag_users import get_settings, get_adapter, Policy, Unauthenticated, USERS, MemoryUsageStore

settings = get_settings()                       # USERS__* from the environment / .env of the CWD
adapter = get_adapter(settings)                 # EnvAuthAdapter(settings.dev_user)  — or —
adapter = get_adapter(settings, headers=st.context.headers)   # HeaderAuthAdapter when USERS__ADAPTER=header
try:
    ctx = adapter.current()                     # AuthContext(user_id, email, groups)
except Unauthenticated as e:
    ...                                         # st.error(str(e)); st.stop()

policy = Policy()                               # RULES + DEFAULT_LIMITS; Policy(rules, default=…) for other data
limits = policy.limits_for(ctx)                 # GroupLimits(daily_messages, max_turns_per_conversation, allowed_doc_ids)

usage = repo.usage()                            # anything with count(user_id, day) / increment(user_id, day, by=1)
decision = policy.check_message(ctx, usage, today=date.today(), turns_in_conversation=conv.turn_count,
                                requested_doc_ids=selected_doc_ids)
if not decision.allowed:
    raise TurnRefused(decision.reason, decision.message_de, decision.remaining_today)   # nothing counted
usage.increment(ctx.user_id, today)             # the reservation; refund with by=-1 if the answer fails
result = retriever.retrieve(question, doc_ids=list(decision.doc_ids) if decision.doc_ids else None)

policy.effective_doc_ids(ctx, requested)        # the filter alone: None = no filter, [] = forbidden
```

`check_message` decides in this order: **forbidden** (the request names only manuals the user may not read),
**daily_cap** (`usage.count(user_id, today) >= daily_messages`), **turn_cap** (`turns_in_conversation >=
max_turns_per_conversation`), else **ok**. It never counts anything itself; `today` is passed in because the caller
owns the clock and the time zone. `Decision.remaining_today` is the number of messages still allowed *before* the
checked one is counted (≥ 1 when allowed). `Decision.doc_ids` is the effective filter for this request (`None` = all,
`()` exactly when forbidden), so one call yields everything the service needs; `Decision.message_de` maps the reason to
the German wording in `REASON_TEXT_DE`. All models are frozen pydantic — `model_dump()` them into diagnostics.

## Configuration (`USERS__*`)

| Key | Default | Meaning |
|---|---|---|
| `USERS__ADAPTER` | `env` | `env` = fixed identity from the directory; `header` = read the ingress headers |
| `USERS__DEV_USER` | `dev` | which directory entry the env adapter returns (`dev`, `otto.ops`, `rita.read`, `anna.admin`) |
| `USERS__HEADER_USER` | `X-Forwarded-User` | mandatory header; missing or blank → `Unauthenticated` |
| `USERS__HEADER_EMAIL` | `X-Forwarded-Email` | optional |
| `USERS__HEADER_GROUPS` | `X-Forwarded-Groups` | optional, comma separated (oauth2-proxy format); trimmed, deduplicated |

Read from the environment and from the `.env` of the working directory (highest precedence first), `extra` keys
ignored — so the keys live in `chat-system/.env` next to `CHAT__*` and `RAG__*` when Streamlit runs from that folder.
`.env.example` documents both blocks. There is no `config.yaml`: the policy data are code (`RULES`) in this mock.

## Swapping the adapter

Local development and the UI's user switch use `EnvAuthAdapter` (chat-system's sidebar offers `USERS` as the
"simulated ingress" of ADR-0008 when `CHAT__UI__ALLOW_USER_SWITCH=true`). Behind oauth2-proxy set
`USERS__ADAPTER=header` and pass the request headers (`st.context.headers` in Streamlit; `st.user` does **not** see
proxy headers, ADR-0008). The header adapter trusts the ingress: it does not look the user up anywhere, and groups it
receives but `RULES` does not know grant nothing. A third implementation (a real directory lookup, an IdP claim
mapping) is one class with a `current() -> AuthContext` method plus a branch in `get_adapter`.

## Tests

```bash
make test        # 39 tests: both adapters (case-insensitive headers, comma groups, missing header, mapping-like
                 # st.context.headers shape), limits_for (max across groups, None wins, unknown groups grant nothing),
                 # daily cap / turn cap / forbidden decisions with remaining_today, effective_doc_ids intersection,
                 # settings precedence (env, .env of the CWD, other prefixes ignored), get_adapter, python -m rag_users
```

## Limitations

- Mock data in code: four users, three groups. No password, no session, no token validation — the identity is
  whatever the environment or the ingress says.
- `allowed_doc_ids` is enforced as a retrieval filter (`doc_ids`), not as row-level security in OpenSearch; a
  user who can reach the cluster directly is not restricted by it. Fine for the prototype's threat model.
- The daily cap is a calendar day in whatever time zone the caller passes as `today` (chat-system uses UTC).
