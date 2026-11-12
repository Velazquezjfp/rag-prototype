"""``python -m rag_users [--json]``: show which adapter ``USERS__*`` selects, who it resolves to and the limits.

The header adapter needs a request, so only the env adapter (local mock user) can be resolved here.
"""

from __future__ import annotations

import json
import sys

from . import Unauthenticated, get_adapter, get_policy, get_settings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    settings = get_settings()
    limits = get_policy(settings).default
    resolved: dict[str, object] = {}
    try:
        ctx = get_adapter(settings).current()
        resolved = {"user_id": ctx.user_id, "email": ctx.email, "groups": list(ctx.groups)}
    except Unauthenticated as e:
        resolved = {"error": str(e)}

    if "--json" in args:
        print(json.dumps({"settings": settings.model_dump(), "current": resolved, "limits": limits.model_dump()},
                         indent=2, ensure_ascii=False))
        return 0

    print(f"adapter: {settings.adapter}  (dev_user={settings.dev_user!r}, headers "
          f"{settings.header_user}/{settings.header_email}/{settings.header_groups})")
    if "error" in resolved:
        print(f"current: NOT authenticated — {resolved['error']}")
    else:
        print(f"current: {resolved['user_id']} <{resolved['email']}>")
    daily = "no daily limit" if limits.daily_messages is None else f"{limits.daily_messages} messages/day"
    print(f"limits:  {daily}, {limits.max_turns_per_conversation} turns per conversation, all manuals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
