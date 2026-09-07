"""``python -m rag_users [--json]``: show the mock directory, the group rules and the resolved limits per user.

Also prints which adapter ``USERS__*`` currently selects and who it resolves to (the env adapter only; the header
adapter needs a request). Handy for ``chat-doctor`` and for checking a ``.env`` before starting the UI.
"""

from __future__ import annotations

import json
import sys

from . import RULES, USERS, Policy, Unauthenticated, get_adapter, get_settings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    settings = get_settings()
    policy = Policy()
    resolved: dict[str, object] = {}
    try:
        adapter = get_adapter(settings)
        ctx = adapter.current()
        resolved = {"user_id": ctx.user_id, "email": ctx.email, "groups": list(ctx.groups)}
    except Unauthenticated as e:
        resolved = {"error": str(e)}

    if "--json" in args:
        out = {
            "settings": settings.model_dump(),
            "current": resolved,
            "rules": {g: lim.model_dump() for g, lim in RULES.items()},
            "users": {
                uid: {**ctx.model_dump(), "limits": policy.limits_for(ctx).model_dump()} for uid, ctx in USERS.items()
            },
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(f"adapter: {settings.adapter}  (dev_user={settings.dev_user!r}, headers "
          f"{settings.header_user}/{settings.header_email}/{settings.header_groups})")
    if "error" in resolved:
        print(f"current: NOT authenticated — {resolved['error']}")
    else:
        print(f"current: {resolved['user_id']} <{resolved['email']}> groups={','.join(resolved['groups']) or '-'}")
    print()
    print(f"{'group':<15} {'msgs/day':>8} {'turns/conv':>10}  allowed manuals")
    for g, lim in RULES.items():
        docs = "all" if lim.allowed_doc_ids is None else ", ".join(lim.allowed_doc_ids)
        print(f"{g:<15} {lim.daily_messages:>8} {lim.max_turns_per_conversation:>10}  {docs}")
    print()
    print(f"{'user':<12} {'email':<26} {'groups':<20} {'msgs/day':>8} {'turns':>5}  allowed manuals")
    for uid, ctx in USERS.items():
        lim = policy.limits_for(ctx)
        docs = "all" if lim.allowed_doc_ids is None else ", ".join(lim.allowed_doc_ids)
        print(f"{uid:<12} {ctx.email:<26} {','.join(ctx.groups):<20} {lim.daily_messages:>8} "
              f"{lim.max_turns_per_conversation:>5}  {docs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
