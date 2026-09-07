# rag-users report — mock auth/policy module, built and verified 2026-09-04

What was asked (`3-modules-plan.md`, module 2): a mock auth/policy module shaped like SPEC §10.2 / ADR-0008 —
`AuthContext{user_id, email, groups}` from one adapter with two implementations, hardcoded users, a daily message cap
and a turn cap per group, and the allowed manuals per group (flagged as an addition beyond the SPEC), tested without
services. It is the second of the three Phase-3 modules; `retrieval/` is done, `chat-system/` follows and will be the
first real consumer of this package.

## What was built

```
users/
  pyproject.toml        rag-users 0.1.0, hatchling, deps pydantic + pydantic-settings only; dev pytest + ruff
  Makefile              venv dev lint test show check
  README.md             what is mocked vs real, directory + rules, API, USERS__* keys, how to swap the adapter
  .env.example          the USERS__* block for chat-system/.env (env adapter active, header block commented)
  src/rag_users/__init__.py   the whole seam (335 lines incl. docstrings): AuthContext, Unauthenticated, USERS,
                        AuthAdapter, EnvAuthAdapter, HeaderAuthAdapter, GroupLimits, DEFAULT_LIMITS, RULES,
                        REASON_TEXT_DE, UsageStore, MemoryUsageStore, Decision, Policy, UsersSettings,
                        get_settings, get_adapter
  src/rag_users/__main__.py   python -m rag_users [--json]: directory, rules, limits per user, resolved current user
  tests/test_users.py   39 tests
```

Installed standalone into `users/.venv` (`make dev`, PyPI reachable). For chat-system the package is meant to be
installed editable into `chat-system/.venv` (`-e ../users` in its requirements.txt), as the plan foresees.

## Verification

| Check | Result |
|---|---|
| `make lint` (ruff, same rule set as retrieval) | clean |
| `make test` | **39 passed** in 0.2 s, no services |
| `make show` | prints the 3 rules, the 4 users with resolved limits, `current: dev <dev@bavd.example> groups=bavd-ops` |
| `USERS__DEV_USER=rita.read make show` | `current: rita.read … groups=bavd-readonly` |
| `USERS__DEV_USER=ghost make show` | `current: NOT authenticated — unknown dev user 'ghost' (known: anna.admin, dev, otto.ops, rita.read)`, exit 0 |
| cross-module smoke against the live cluster (below) | the effective filter restricts chunks, facts **and** citations to the allowed manual |

### The plan's test list, item by item

| Plan item | Tests |
|---|---|
| env adapter identity | `test_env_adapter_returns_the_fixed_identity`, `…_accepts_a_custom_directory` |
| unknown dev user raises | `test_env_adapter_unknown_user_raises_and_names_the_known_ones` |
| header adapter parsing: case-insensitive, comma groups, missing header raises | `test_header_adapter_parses_oauth2_proxy_headers`, `…_header_names_are_case_insensitive`, `…_missing_or_blank_user_header_raises`, `…_custom_header_names_and_no_groups`, `…_does_not_consult_the_mock_directory`, `…_works_with_a_mapping_like_object` (the shape of `st.context.headers`) |
| `limits_for` max over groups, None dominates | `test_limits_for_takes_the_max_across_groups_and_none_doc_filter_wins`, `…_unions_restricted_doc_lists`, `…_unknown_groups_grant_nothing`, `…_single_group` |
| daily cap and turn cap refusals with `remaining_today` | `test_daily_cap_refuses_the_eleventh_message`, `…_is_per_group_and_per_day`, `test_remaining_today_never_goes_negative`, `test_turn_cap_refuses_when_the_conversation_is_full`, `test_daily_cap_is_reported_before_the_turn_cap` |
| `effective_doc_ids` intersection and `[]` for readonly asking CaaS only | `test_effective_doc_ids_unrestricted_user`, `…_readonly_intersection`, `…_empty_means_forbidden`, `test_check_message_forbidden_when_only_unreadable_manuals_requested`, `…_carries_the_effective_doc_filter` |
| `get_adapter` honours `USERS__ADAPTER` | `test_get_adapter_honours_users_adapter`, `…_without_settings_reads_the_environment` |
| settings (not in the plan's list, added) | defaults, `USERS__` prefix with other prefixes ignored, unknown adapter rejected, `.env` of the CWD read |
| extras | frozen models + JSON round trip, `MemoryUsageStore` incl. refund, `USERS`/`RULES` consistency, a full read-only day (5 messages then cap, refund re-opens a slot), `python -m rag_users` text and `--json` |

### Cross-module smoke: the document filter reaches retrieval

Run from `retrieval/.venv` with `PYTHONPATH=../users/src` against the live OpenSearch (both manuals indexed) and
LiteLLM (bge-m3 embeddings), question "Was war bei ZSDSUP-0247?" in slow mode. `Policy.check_message(…,
requested_doc_ids=…)` → `Decision.doc_ids` → `Retriever.retrieve(question, doc_ids=…)`:

| user | requested manuals | decision | `doc_ids` sent | chunks (top 10) | facts | citations |
|---|---|---|---|---|---|---|
| rita.read (bavd-readonly) | none | ok | `[BHB-PLT-0007]` | ZSD 10 | ZSD 40 | ZSD 15 |
| rita.read | CaaS + ZSD | ok | `[BHB-PLT-0007]` | ZSD 10 | ZSD 40 | ZSD 15 |
| rita.read | CaaS only | **forbidden** | `()` | not called | — | "Für die gewählten Handbücher besteht keine Leseberechtigung." |
| otto.ops (bavd-ops) | none | ok | `None` | CaaS 3 · ZSD 7 | CaaS 13 · ZSD 27 | CaaS 8 · ZSD 9 |
| anna.admin (admin) | CaaS only | ok | `[BHB-PLT-0001]` | CaaS 10 | CaaS 26 | CaaS 16 |

Two things this confirms beyond the unit tests: the filter placement in `retrieval/` (knn clause + bool filter)
works with the list this module produces, and the graph channel honours the filter too — the read-only user gets
no CaaS facts although the union graph holds both books' edges for this incident (the PARTNER_TICKET chain is in
both). Unfiltered, the same question returns the cross-book mix REPORT.md of `retrieval/` documents.

## Decisions and deltas to the plan

1. **`check_message` takes `requested_doc_ids` and `Decision` carries `doc_ids`.** The plan listed `"forbidden"`
   among the decision reasons but only `effective_doc_ids()` could produce it (as `[]`). One call now returns the
   verdict *and* the effective filter (`None` = all, `()` exactly when forbidden), so chat-system's `ask()` phase 1
   is a single policy call. `effective_doc_ids()` stays public as specified.
2. **Check order forbidden → daily_cap → turn_cap.** A request for manuals the user may not read is refused
   regardless of quota; nothing is counted on any refusal (the caller increments after an `ok`).
3. **`remaining_today` = cap − used *before* the checked message** (≥ 1 when allowed). The service shows "used/cap"
   from its own counter after the increment; the decision's number is what the refusal message needs.
4. **Unknown groups grant nothing.** Not specified in the plan: a user whose only groups are unknown gets
   `DEFAULT_LIMITS` (the SPEC's 10/day), but an unknown group next to `bavd-readonly` does not widen the read-only
   limits to the defaults. Restricted lists of several groups are unioned; `None` from any group wins.
5. **The header adapter trusts the ingress and never consults `USERS`.** With a real IdP the mock directory is
   simply unused; groups arrive comma separated (oauth2-proxy), trimmed and deduplicated, header names matched
   case-insensitively over any Mapping-like object (`st.context.headers`, a dict). Blank user header = missing.
6. **Small additions for the consumers:** `REASON_TEXT_DE` + `Decision.message_de` (German refusal wording lives
   next to the reasons it depends on), `MemoryUsageStore` (tests and single-process demos), `Policy(rules,
   default=)` and `EnvAuthAdapter(users=)` constructor args, `get_adapter(settings=None)`, `python -m rag_users`
   for `chat-doctor` and for checking a `.env`. `get_settings()` is not cached (construction is microseconds and
   tests change the environment).
7. **Size.** 335 lines instead of the plan's ~150: the delta is docstrings and the two protocols being
   `runtime_checkable` (so tests and chat-system can `isinstance` their fakes).
8. **`allowed_doc_ids` remains flagged as an addition beyond SPEC §10.2** (README, docstrings). Setting every rule
   to `None` restores the SPEC's behaviour without touching call sites.

## Contract points for chat-system (module 3)

- `pip install -e ../users`; keys `USERS__ADAPTER`, `USERS__DEV_USER`, `USERS__HEADER_*` in `chat-system/.env`
  (pydantic-settings reads the `.env` of the CWD; tested).
- Sidebar user switch = `EnvAuthAdapter(uid)` / `USERS[uid]` for the choices; production =
  `get_adapter(settings, headers=st.context.headers).current()`; `Unauthenticated` → `st.error` + `st.stop()`.
- `UsageRepo` implements `count(user_id, day) -> int` and `increment(user_id, day, by=1) -> int` (negative `by` for
  the refund after an LLM error) — that is all `UsageStore` requires.
- `Policy().check_message(ctx, usage, today=<UTC date>, turns_in_conversation=conv.turn_count,
  requested_doc_ids=selected)` → refuse with `decision.reason`, `decision.message_de`, `decision.remaining_today`
  when not allowed; otherwise `usage.increment(...)` then `retrieve(..., doc_ids=list(decision.doc_ids) or None)`.
- `svc.documents(ctx)` = catalog ∩ `policy.limits_for(ctx).allowed_doc_ids` (None = all).
- Everything is frozen pydantic: `decision.model_dump()` / `limits.model_dump()` go straight into diagnostics JSON.

## Not covered

- No real IdP, no session, no token check; the identity is what the environment or the ingress says (by design,
  SPEC §10.2 defers real auth). No integration with an actual oauth2-proxy was run.
- `allowed_doc_ids` is a retrieval filter, not row-level security in OpenSearch.
- The header adapter was tested against a Mapping-like stand-in for `st.context.headers`, not against a running
  Streamlit (not installed until chat-system's venv exists).
