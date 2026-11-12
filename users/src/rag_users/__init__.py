"""rag-users: the auth/policy seam of the RAG prototype (SPEC §10.2, ADR-0008).

One seam, two adapters: ``AuthContext{user_id, email, groups}`` comes from either the :class:`EnvAuthAdapter`
(local: ONE fixed mock user, ``USERS__DEV_USER``) or the :class:`HeaderAuthAdapter` (remote: the headers
oauth2-proxy injects at the ingress). There is no user directory and no per-group rule by default: every user may
search every manual, there is no daily message limit, and a conversation ends after ``USERS__MAX_TURNS`` turns
(ADR-0011). :class:`Policy` still understands per-group rules, a daily cap and ``allowed_doc_ids`` when a caller
passes them, and :class:`UsageStore` is the protocol the chat-system's database implements for the counter.

Nothing in this module does I/O; it has no dependency on the other modules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "DEFAULT_LIMITS",
    "REASON_TEXT_DE",
    "RULES",
    "AuthAdapter",
    "AuthContext",
    "Decision",
    "EnvAuthAdapter",
    "GroupLimits",
    "HeaderAuthAdapter",
    "MemoryUsageStore",
    "Policy",
    "Reason",
    "Unauthenticated",
    "UsageStore",
    "UsersSettings",
    "get_adapter",
    "get_policy",
    "get_settings",
]

Reason = Literal["ok", "daily_cap", "turn_cap", "forbidden"]


# --------------------------------------------------------------------------------------------- identity


class AuthContext(BaseModel):
    """Who is asking. Produced by exactly one adapter per process (SPEC §10.2); everything downstream keys on it."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1)
    email: str = ""
    groups: tuple[str, ...] = ()


class Unauthenticated(Exception):
    """No usable identity: empty mock user, or the ingress did not inject a user header."""


@runtime_checkable
class AuthAdapter(Protocol):
    def current(self) -> AuthContext:
        """The identity of the current request; raises :class:`Unauthenticated`."""
        ...


class EnvAuthAdapter:
    """Local adapter (ADR-0008): ONE fixed mock user, named by ``USERS__DEV_USER``. Never use it behind an ingress."""

    def __init__(self, user_id: str) -> None:
        self.user_id = (user_id or "").strip()

    def current(self) -> AuthContext:
        if not self.user_id:
            raise Unauthenticated("USERS__DEV_USER is empty: the env adapter needs a mock user id")
        return AuthContext(user_id=self.user_id, email=f"{self.user_id}@localhost")


class HeaderAuthAdapter:
    """Production adapter (ADR-0008): identity from the headers oauth2-proxy injects at the ingress.

    ``headers`` is any mapping (``st.context.headers``, a dict from a test); names are matched case-insensitively.
    The user header is mandatory, the e-mail header optional, groups are comma separated (oauth2-proxy's format).
    A missing user header is an error, never a fallback user. Groups are kept but grant nothing by default.
    """

    def __init__(
        self,
        headers: Mapping[str, str] | None,
        *,
        user_header: str = "X-Forwarded-User",
        email_header: str = "X-Forwarded-Email",
        groups_header: str = "X-Forwarded-Groups",
    ) -> None:
        self._headers = headers if headers is not None else {}
        self.user_header = user_header
        self.email_header = email_header
        self.groups_header = groups_header

    def _get(self, name: str) -> str | None:
        value = self._headers.get(name)
        if value is None:
            wanted = name.lower()
            for key in self._headers:
                if key.lower() == wanted:
                    value = self._headers[key]
                    break
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    def current(self) -> AuthContext:
        user_id = self._get(self.user_header)
        if user_id is None:
            raise Unauthenticated(f"missing header {self.user_header!r}: not behind the authenticating ingress?")
        email = self._get(self.email_header) or ""
        groups = _split_groups(self._get(self.groups_header))
        return AuthContext(user_id=user_id, email=email, groups=groups)


def _split_groups(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    seen: dict[str, None] = {}
    for part in raw.split(","):
        g = part.strip()
        if g:
            seen.setdefault(g, None)
    return tuple(seen)


# ----------------------------------------------------------------------------------------------- limits


class GroupLimits(BaseModel):
    """What a user may do. ``daily_messages=None`` = no daily limit; ``allowed_doc_ids=None`` = every manual."""

    model_config = ConfigDict(frozen=True)

    daily_messages: int | None = Field(None, ge=0)
    max_turns_per_conversation: int = Field(ge=0)
    allowed_doc_ids: tuple[str, ...] | None = None


DEFAULT_LIMITS = GroupLimits(daily_messages=None, max_turns_per_conversation=10, allowed_doc_ids=None)
"""Every user: no daily limit, 10 turns per conversation, all manuals. :func:`get_policy` reads the turn cap from
``USERS__MAX_TURNS``."""

RULES: dict[str, GroupLimits] = {}
"""Per-group limits: none by default. A :class:`Policy` built with rules gives a user in several groups the most
permissive value of each field."""

REASON_TEXT_DE: dict[Reason, str] = {
    "ok": "",
    "daily_cap": "Das Tageslimit an Nachrichten ist erreicht. Morgen geht es weiter.",
    "turn_cap": "Dieses Gespräch hat die maximale Länge erreicht. Bitte ein neues Gespräch beginnen.",
    "forbidden": "Für die gewählten Handbücher besteht keine Leseberechtigung.",
}
"""German wording per refusal reason, for the UI and the CLI."""


@runtime_checkable
class UsageStore(Protocol):
    """Messages sent per user and day. Implemented by chat-system's database (SPEC §10.2: not in the UI)."""

    def count(self, user_id: str, day: date) -> int: ...

    def increment(self, user_id: str, day: date, by: int = 1) -> int:
        """Add ``by`` (may be negative to refund) and return the new count."""
        ...


class MemoryUsageStore:
    """In-process :class:`UsageStore` for tests and single-process demos (not shared between processes)."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, date], int] = {}

    def count(self, user_id: str, day: date) -> int:
        return self._counts.get((user_id, day), 0)

    def increment(self, user_id: str, day: date, by: int = 1) -> int:
        new = max(0, self._counts.get((user_id, day), 0) + by)
        self._counts[(user_id, day)] = new
        return new


class Decision(BaseModel):
    """Outcome of :meth:`Policy.check_message`.

    ``remaining_today`` counts the messages the user may still send today *before* the checked one is counted
    (so it is ≥ 1 whenever ``allowed`` and the caller then increments the store); ``None`` = no daily limit. ``doc_ids`` is the effective
    manual filter for this request (``None`` = no filter); it is ``()`` exactly when ``reason == "forbidden"``.
    """

    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: Reason
    remaining_today: int | None
    limits: GroupLimits
    doc_ids: tuple[str, ...] | None = None

    @property
    def message_de(self) -> str:
        return REASON_TEXT_DE[self.reason]


class Policy:
    """Group rules → limits, quota and document-access decisions. Stateless; usage lives in the :class:`UsageStore`."""

    def __init__(
        self, rules: Mapping[str, GroupLimits] | None = None, *, default: GroupLimits = DEFAULT_LIMITS
    ) -> None:
        self.rules: dict[str, GroupLimits] = dict(RULES if rules is None else rules)
        self.default = default

    def limits_for(self, ctx: AuthContext) -> GroupLimits:
        """Most permissive value per field across the user's *known* groups; unknown groups grant nothing."""
        matched = [self.rules[g] for g in ctx.groups if g in self.rules]
        if not matched:
            return self.default
        allowed: tuple[str, ...] | None
        if any(m.allowed_doc_ids is None for m in matched):
            allowed = None
        else:
            allowed = _unique(d for m in matched for d in (m.allowed_doc_ids or ()))
        daily = [m.daily_messages for m in matched]
        return GroupLimits(
            daily_messages=None if any(d is None for d in daily) else max(d for d in daily if d is not None),
            max_turns_per_conversation=max(m.max_turns_per_conversation for m in matched),
            allowed_doc_ids=allowed,
        )

    def effective_doc_ids(self, ctx: AuthContext, requested: Sequence[str] | None) -> list[str] | None:
        """Manuals this request may search: the intersection of the request with the group's allowlist.

        ``None`` = no filter (unrestricted user, nothing requested). An empty request means "all I may read".
        ``[]`` means the user asked only for manuals they may not read — the caller refuses ("forbidden").
        """
        allowed = self.limits_for(ctx).allowed_doc_ids
        wanted = _unique(requested or ())
        if allowed is None:
            return list(wanted) if wanted else None
        if not wanted:
            return list(allowed)
        allowed_set = set(allowed)
        return [d for d in wanted if d in allowed_set]

    def check_message(
        self,
        ctx: AuthContext,
        usage: UsageStore,
        *,
        today: date,
        turns_in_conversation: int,
        requested_doc_ids: Sequence[str] | None = None,
    ) -> Decision:
        """May ``ctx`` send one more message now? Checks, in order: document access, daily cap, turn cap.

        ``today`` is passed in (the caller owns the clock and the time zone). Nothing is counted here; the caller
        increments the store after an allowed decision.
        """
        limits = self.limits_for(ctx)
        used = usage.count(ctx.user_id, today)
        remaining = None if limits.daily_messages is None else max(0, limits.daily_messages - used)
        effective = self.effective_doc_ids(ctx, requested_doc_ids)
        doc_ids = None if effective is None else tuple(effective)

        def _decide(allowed: bool, reason: Reason) -> Decision:
            return Decision(allowed=allowed, reason=reason, remaining_today=remaining, limits=limits, doc_ids=doc_ids)

        if effective is not None and not effective:
            return _decide(False, "forbidden")
        if remaining is not None and remaining <= 0:
            return _decide(False, "daily_cap")
        if turns_in_conversation >= limits.max_turns_per_conversation:
            return _decide(False, "turn_cap")
        return _decide(True, "ok")


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


# --------------------------------------------------------------------------------------------- settings


class UsersSettings(BaseSettings):
    """``USERS__*`` from the environment or the ``.env`` of the working directory (chat-system's, when run from there)."""

    model_config = SettingsConfigDict(
        env_prefix="USERS__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    adapter: Literal["env", "header"] = "env"
    dev_user: str = "dev"  # the one mock user of the env adapter (local profile)
    max_turns: int = Field(10, ge=1)  # turns per conversation, then "start a new conversation"
    daily_messages: int | None = Field(None, ge=0)  # unset = no daily limit
    header_user: str = "X-Forwarded-User"
    header_email: str = "X-Forwarded-Email"
    header_groups: str = "X-Forwarded-Groups"


def get_settings() -> UsersSettings:
    return UsersSettings()


def get_adapter(settings: UsersSettings | None = None, headers: Mapping[str, str] | None = None) -> AuthAdapter:
    """The configured adapter: ``env`` → :class:`EnvAuthAdapter`, ``header`` → :class:`HeaderAuthAdapter` over ``headers``."""
    s = settings if settings is not None else get_settings()
    if s.adapter == "header":
        return HeaderAuthAdapter(
            headers, user_header=s.header_user, email_header=s.header_email, groups_header=s.header_groups
        )
    return EnvAuthAdapter(s.dev_user)


def get_policy(settings: UsersSettings | None = None) -> Policy:
    """The policy of the app: the same limits for every user, from ``USERS__MAX_TURNS`` / ``USERS__DAILY_MESSAGES``."""
    s = settings if settings is not None else get_settings()
    return Policy(
        rules={},
        default=GroupLimits(daily_messages=s.daily_messages, max_turns_per_conversation=s.max_turns, allowed_doc_ids=None),
    )
