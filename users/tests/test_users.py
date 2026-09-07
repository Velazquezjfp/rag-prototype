"""rag-users: adapters, limits, quota decisions, document access, settings. No services, no I/O."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from rag_users import (
    DEFAULT_LIMITS,
    REASON_TEXT_DE,
    RULES,
    USERS,
    AuthAdapter,
    AuthContext,
    Decision,
    EnvAuthAdapter,
    GroupLimits,
    HeaderAuthAdapter,
    MemoryUsageStore,
    Policy,
    Unauthenticated,
    UsageStore,
    UsersSettings,
    get_adapter,
)
from rag_users.__main__ import main as show_main

TODAY = date(2026, 9, 4)
ZSD = "BHB-PLT-0007"
CAAS = "BHB-PLT-0001"


@pytest.fixture(autouse=True)
def _clean_users_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("USERS__"):
            monkeypatch.delenv(key)


@pytest.fixture
def policy() -> Policy:
    return Policy()


@pytest.fixture
def usage() -> MemoryUsageStore:
    return MemoryUsageStore()


def ctx(user_id: str) -> AuthContext:
    return USERS[user_id]


# ------------------------------------------------------------------------------------------ directory


def test_mock_directory_is_consistent():
    assert set(USERS) == {"dev", "otto.ops", "rita.read", "anna.admin"}
    for uid, c in USERS.items():
        assert c.user_id == uid
        assert c.email.endswith("@bavd.example")
        assert c.groups and all(g in RULES for g in c.groups), f"{uid}: every group must have a rule"
    assert USERS["anna.admin"].groups == ("admin", "bavd-ops")
    assert USERS["rita.read"].groups == ("bavd-readonly",)


def test_auth_context_is_frozen_and_validated():
    c = AuthContext(user_id="x", email="x@e", groups=["a", "b"])  # list coerced to tuple
    assert c.groups == ("a", "b")
    with pytest.raises(ValidationError):
        c.user_id = "y"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AuthContext(user_id="", email="x@e")
    assert AuthContext(user_id="anon").groups == () and AuthContext(user_id="anon").email == ""


# ---------------------------------------------------------------------------------------- env adapter


def test_env_adapter_returns_the_fixed_identity():
    adapter = EnvAuthAdapter("otto.ops")
    assert isinstance(adapter, AuthAdapter)
    c = adapter.current()
    assert (c.user_id, c.email, c.groups) == ("otto.ops", "otto.ops@bavd.example", ("bavd-ops",))
    assert adapter.current() is c  # stable object, no per-call state


def test_env_adapter_unknown_user_raises_and_names_the_known_ones():
    with pytest.raises(Unauthenticated) as e:
        EnvAuthAdapter("nobody").current()
    assert "nobody" in str(e.value) and "rita.read" in str(e.value)


def test_env_adapter_accepts_a_custom_directory():
    users = {"t": AuthContext(user_id="t", email="t@x", groups=("admin",))}
    assert EnvAuthAdapter("t", users=users).current().groups == ("admin",)
    with pytest.raises(Unauthenticated):
        EnvAuthAdapter("dev", users=users).current()


# ------------------------------------------------------------------------------------- header adapter


def test_header_adapter_parses_oauth2_proxy_headers():
    headers = {
        "X-Forwarded-User": "otto.ops",
        "X-Forwarded-Email": "otto.ops@bavd.example",
        "X-Forwarded-Groups": "bavd-ops, admin,,bavd-ops ,",
    }
    c = HeaderAuthAdapter(headers).current()
    assert c.user_id == "otto.ops" and c.email == "otto.ops@bavd.example"
    assert c.groups == ("bavd-ops", "admin")  # trimmed, empties dropped, duplicates removed, order kept


def test_header_adapter_header_names_are_case_insensitive():
    headers = {"x-forwarded-user": "rita.read", "X-FORWARDED-GROUPS": "bavd-readonly"}
    c = HeaderAuthAdapter(headers).current()
    assert c.user_id == "rita.read" and c.groups == ("bavd-readonly",) and c.email == ""


def test_header_adapter_missing_or_blank_user_header_raises():
    with pytest.raises(Unauthenticated) as e:
        HeaderAuthAdapter({"X-Forwarded-Email": "a@b"}).current()
    assert "X-Forwarded-User" in str(e.value)
    with pytest.raises(Unauthenticated):
        HeaderAuthAdapter({"X-Forwarded-User": "   "}).current()
    with pytest.raises(Unauthenticated):
        HeaderAuthAdapter(None).current()
    with pytest.raises(Unauthenticated):
        HeaderAuthAdapter({}).current()


def test_header_adapter_custom_header_names_and_no_groups():
    headers = {"Remote-User": "u1", "Remote-Mail": "u1@x"}
    c = HeaderAuthAdapter(
        headers, user_header="Remote-User", email_header="Remote-Mail", groups_header="Remote-Groups"
    ).current()
    assert c == AuthContext(user_id="u1", email="u1@x", groups=())


def test_header_adapter_does_not_consult_the_mock_directory():
    """Production identities come from the ingress only: a header user named like a mock user gets the header's groups."""
    c = HeaderAuthAdapter({"X-Forwarded-User": "anna.admin"}).current()
    assert c.groups == () and c.email == ""


def test_header_adapter_works_with_a_mapping_like_object():
    class Headers:  # the shape of st.context.headers: Mapping-like, get + iteration + __getitem__
        def __init__(self, d):
            self._d = d

        def get(self, k, default=None):
            return self._d.get(k, default)

        def __iter__(self):
            return iter(self._d)

        def __getitem__(self, k):
            return self._d[k]

    c = HeaderAuthAdapter(Headers({"X-Forwarded-User": "u", "x-forwarded-groups": "g1,g2"})).current()
    assert c.user_id == "u" and c.groups == ("g1", "g2")


# --------------------------------------------------------------------------------------------- limits


def test_defaults_match_the_spec():
    assert DEFAULT_LIMITS == GroupLimits(daily_messages=10, max_turns_per_conversation=10, allowed_doc_ids=None)
    assert RULES["bavd-ops"].daily_messages == 10
    assert RULES["bavd-readonly"].allowed_doc_ids == (ZSD,)
    assert RULES["admin"].allowed_doc_ids is None


def test_limits_for_single_group(policy):
    assert policy.limits_for(ctx("otto.ops")) == RULES["bavd-ops"]
    assert policy.limits_for(ctx("rita.read")) == RULES["bavd-readonly"]


def test_limits_for_takes_the_max_across_groups_and_none_doc_filter_wins(policy):
    lim = policy.limits_for(ctx("anna.admin"))
    assert (lim.daily_messages, lim.max_turns_per_conversation, lim.allowed_doc_ids) == (100, 20, None)
    mixed = AuthContext(user_id="m", groups=("bavd-readonly", "admin"))
    assert policy.limits_for(mixed).allowed_doc_ids is None
    assert policy.limits_for(mixed).daily_messages == 100


def test_limits_for_unions_restricted_doc_lists():
    p = Policy(
        {
            "a": GroupLimits(daily_messages=1, max_turns_per_conversation=1, allowed_doc_ids=(ZSD,)),
            "b": GroupLimits(daily_messages=2, max_turns_per_conversation=3, allowed_doc_ids=(CAAS, ZSD)),
        }
    )
    lim = p.limits_for(AuthContext(user_id="u", groups=("a", "b")))
    assert lim == GroupLimits(daily_messages=2, max_turns_per_conversation=3, allowed_doc_ids=(ZSD, CAAS))


def test_limits_for_unknown_groups_grant_nothing(policy):
    assert policy.limits_for(AuthContext(user_id="u", groups=())) == DEFAULT_LIMITS
    assert policy.limits_for(AuthContext(user_id="u", groups=("marketing",))) == DEFAULT_LIMITS
    # an unknown group must not widen a restricted one to the defaults
    lim = policy.limits_for(AuthContext(user_id="u", groups=("marketing", "bavd-readonly")))
    assert lim == RULES["bavd-readonly"]


def test_policy_accepts_custom_rules_and_default():
    p = Policy({}, default=GroupLimits(daily_messages=1, max_turns_per_conversation=1))
    assert p.limits_for(ctx("anna.admin")).daily_messages == 1
    assert p.rules == {}


# ----------------------------------------------------------------------------------------- daily cap


def test_check_message_ok_reports_remaining_before_this_message(policy, usage):
    d = policy.check_message(ctx("otto.ops"), usage, today=TODAY, turns_in_conversation=0)
    assert d.allowed and d.reason == "ok" and d.remaining_today == 10 and d.doc_ids is None
    assert d.limits == RULES["bavd-ops"] and d.message_de == ""


def test_daily_cap_refuses_the_eleventh_message(policy, usage):
    for _ in range(10):
        assert policy.check_message(ctx("otto.ops"), usage, today=TODAY, turns_in_conversation=0).allowed
        usage.increment("otto.ops", TODAY)
    d = policy.check_message(ctx("otto.ops"), usage, today=TODAY, turns_in_conversation=0)
    assert not d.allowed and d.reason == "daily_cap" and d.remaining_today == 0
    assert d.message_de == REASON_TEXT_DE["daily_cap"] and "Tageslimit" in d.message_de


def test_daily_cap_is_per_group_and_per_day(policy, usage):
    for _ in range(5):
        usage.increment("rita.read", TODAY)
    assert policy.check_message(ctx("rita.read"), usage, today=TODAY, turns_in_conversation=0).reason == "daily_cap"
    tomorrow = TODAY + timedelta(days=1)
    d = policy.check_message(ctx("rita.read"), usage, today=tomorrow, turns_in_conversation=0)
    assert d.allowed and d.remaining_today == 5
    # another user's usage is separate
    assert policy.check_message(ctx("otto.ops"), usage, today=TODAY, turns_in_conversation=0).remaining_today == 10


def test_remaining_today_never_goes_negative(policy, usage):
    usage.increment("otto.ops", TODAY, by=25)
    d = policy.check_message(ctx("otto.ops"), usage, today=TODAY, turns_in_conversation=0)
    assert d.reason == "daily_cap" and d.remaining_today == 0


# ------------------------------------------------------------------------------------------ turn cap


def test_turn_cap_refuses_when_the_conversation_is_full(policy, usage):
    d = policy.check_message(ctx("otto.ops"), usage, today=TODAY, turns_in_conversation=10)
    assert not d.allowed and d.reason == "turn_cap" and d.remaining_today == 10
    assert "neues Gespräch" in d.message_de
    assert policy.check_message(ctx("otto.ops"), usage, today=TODAY, turns_in_conversation=9).allowed
    assert policy.check_message(ctx("anna.admin"), usage, today=TODAY, turns_in_conversation=19).allowed
    assert policy.check_message(ctx("anna.admin"), usage, today=TODAY, turns_in_conversation=20).reason == "turn_cap"


def test_daily_cap_is_reported_before_the_turn_cap(policy, usage):
    usage.increment("rita.read", TODAY, by=5)
    d = policy.check_message(ctx("rita.read"), usage, today=TODAY, turns_in_conversation=5)
    assert d.reason == "daily_cap"


# ------------------------------------------------------------------------------------ document access


def test_effective_doc_ids_unrestricted_user(policy):
    assert policy.effective_doc_ids(ctx("otto.ops"), None) is None
    assert policy.effective_doc_ids(ctx("otto.ops"), []) is None
    assert policy.effective_doc_ids(ctx("otto.ops"), [CAAS, ZSD, CAAS]) == [CAAS, ZSD]


def test_effective_doc_ids_readonly_intersection(policy):
    assert policy.effective_doc_ids(ctx("rita.read"), None) == [ZSD]
    assert policy.effective_doc_ids(ctx("rita.read"), []) == [ZSD]
    assert policy.effective_doc_ids(ctx("rita.read"), [CAAS, ZSD]) == [ZSD]
    assert policy.effective_doc_ids(ctx("rita.read"), [ZSD]) == [ZSD]


def test_effective_doc_ids_empty_means_forbidden(policy):
    assert policy.effective_doc_ids(ctx("rita.read"), [CAAS]) == []
    assert policy.effective_doc_ids(ctx("rita.read"), ["BHB-PLT-0042"]) == []


def test_check_message_forbidden_when_only_unreadable_manuals_requested(policy, usage):
    d = policy.check_message(
        ctx("rita.read"), usage, today=TODAY, turns_in_conversation=0, requested_doc_ids=[CAAS]
    )
    assert not d.allowed and d.reason == "forbidden" and d.doc_ids == ()
    assert "Leseberechtigung" in d.message_de
    # forbidden is decided before quota: nothing about this request should be counted
    assert usage.count("rita.read", TODAY) == 0


def test_check_message_carries_the_effective_doc_filter(policy, usage):
    d = policy.check_message(ctx("rita.read"), usage, today=TODAY, turns_in_conversation=0)
    assert d.allowed and d.doc_ids == (ZSD,)
    d = policy.check_message(
        ctx("rita.read"), usage, today=TODAY, turns_in_conversation=0, requested_doc_ids=[CAAS, ZSD]
    )
    assert d.allowed and d.doc_ids == (ZSD,)
    d = policy.check_message(
        ctx("anna.admin"), usage, today=TODAY, turns_in_conversation=0, requested_doc_ids=[CAAS]
    )
    assert d.allowed and d.doc_ids == (CAAS,)
    d = policy.check_message(ctx("anna.admin"), usage, today=TODAY, turns_in_conversation=0)
    assert d.doc_ids is None


def test_decision_is_frozen_and_json_serialisable(policy, usage):
    d = policy.check_message(ctx("rita.read"), usage, today=TODAY, turns_in_conversation=0)
    with pytest.raises(ValidationError):
        d.allowed = False  # type: ignore[misc]
    dumped = json.loads(d.model_dump_json())
    assert dumped["limits"]["allowed_doc_ids"] == [ZSD] and dumped["reason"] == "ok"
    assert Decision.model_validate(dumped) == d


# --------------------------------------------------------------------------------------- usage store


def test_memory_usage_store_counts_increments_and_refunds():
    s = MemoryUsageStore()
    assert isinstance(s, UsageStore)
    assert s.count("u", TODAY) == 0
    assert s.increment("u", TODAY) == 1
    assert s.increment("u", TODAY, by=2) == 3
    assert s.increment("u", TODAY, by=-1) == 2  # refund after an LLM error
    assert s.increment("u", TODAY, by=-5) == 0  # never negative
    assert s.count("u", TODAY + timedelta(days=1)) == 0


# ------------------------------------------------------------------------------------------- settings


def test_settings_defaults():
    s = UsersSettings(_env_file=None)
    assert s.adapter == "env" and s.dev_user == "dev"
    assert (s.header_user, s.header_email, s.header_groups) == (
        "X-Forwarded-User",
        "X-Forwarded-Email",
        "X-Forwarded-Groups",
    )


def test_settings_read_users_prefix_and_ignore_other_prefixes(monkeypatch):
    monkeypatch.setenv("USERS__DEV_USER", "rita.read")
    monkeypatch.setenv("USERS__HEADER_USER", "Remote-User")
    monkeypatch.setenv("RAG__LLM__MODEL", "x")
    monkeypatch.setenv("CHAT__UI__TITLE", "y")
    s = UsersSettings(_env_file=None)
    assert s.dev_user == "rita.read" and s.header_user == "Remote-User" and s.adapter == "env"


def test_settings_reject_unknown_adapter(monkeypatch):
    monkeypatch.setenv("USERS__ADAPTER", "ldap")
    with pytest.raises(ValidationError):
        UsersSettings(_env_file=None)


def test_settings_read_dot_env_from_the_working_directory(tmp_path, monkeypatch):
    """chat-system runs from its folder: USERS__* keys in chat-system/.env feed this module."""
    (tmp_path / ".env").write_text("USERS__ADAPTER=header\nUSERS__DEV_USER=otto.ops\nCHAT__X=1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    s = UsersSettings()
    assert s.adapter == "header" and s.dev_user == "otto.ops"


def test_get_adapter_honours_users_adapter(monkeypatch):
    monkeypatch.setenv("USERS__DEV_USER", "anna.admin")
    env_adapter = get_adapter(UsersSettings(_env_file=None))
    assert isinstance(env_adapter, EnvAuthAdapter) and env_adapter.current().user_id == "anna.admin"

    monkeypatch.setenv("USERS__ADAPTER", "header")
    monkeypatch.setenv("USERS__HEADER_GROUPS", "X-Groups")
    hdr = get_adapter(UsersSettings(_env_file=None), headers={"X-Forwarded-User": "u", "X-Groups": "admin"})
    assert isinstance(hdr, HeaderAuthAdapter) and hdr.current().groups == ("admin",)
    # header adapter selected but no request headers available -> unauthenticated, not a crash
    with pytest.raises(Unauthenticated):
        get_adapter(UsersSettings(_env_file=None)).current()


def test_get_adapter_without_settings_reads_the_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("USERS__DEV_USER", "rita.read")
    assert get_adapter().current().user_id == "rita.read"


# ----------------------------------------------------------------------------------- end-to-end flow


def test_readonly_user_full_day(policy, usage):
    """rita.read: ZSD only, five messages, then the cap; a refund re-opens one slot."""
    rita = ctx("rita.read")
    sent = 0
    for turn in range(10):
        d = policy.check_message(
            rita, usage, today=TODAY, turns_in_conversation=turn, requested_doc_ids=[CAAS, ZSD]
        )
        if not d.allowed:
            break
        assert d.doc_ids == (ZSD,)
        usage.increment(rita.user_id, TODAY)
        sent += 1
    assert sent == 5 and d.reason in {"daily_cap", "turn_cap"}
    usage.increment(rita.user_id, TODAY, by=-1)  # the last answer failed -> refund
    assert policy.check_message(rita, usage, today=TODAY, turns_in_conversation=0).allowed


# ----------------------------------------------------------------------------------------- __main__


def test_show_prints_directory_and_current_user(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USERS__DEV_USER", "rita.read")
    assert show_main([]) == 0
    out = capsys.readouterr().out
    assert "current: rita.read <rita.read@bavd.example> groups=bavd-readonly" in out
    assert "bavd-readonly" in out and "BHB-PLT-0007" in out and "anna.admin" in out


def test_show_json_and_unauthenticated(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USERS__DEV_USER", "ghost")
    assert show_main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "error" in data["current"] and "ghost" in data["current"]["error"]
    assert data["users"]["anna.admin"]["limits"]["daily_messages"] == 100
    assert data["rules"]["bavd-readonly"]["allowed_doc_ids"] == [ZSD]
