"""Target relevance filter.

Every channel is narrowed to content about the monitored organization (e.g. Sympany).
A post is relevant if:
  - its text mentions any configured alias (case-insensitive), OR
  - it originates from an official handle / first-party source, OR
  - it arrived from a search query that already targeted the org (source starts "search:"
    or "company:").

This keeps generic channel feeds (a subreddit, a Telegram channel) focused on the target
without each connector needing its own filtering logic.
"""

from __future__ import annotations

import re

from ..models import Post


def names_other_org(text: str, target: dict) -> bool:
    """True when the text is about a different organization with a similar name (target
    .exclude_patterns, e.g. a foreign company with the same name as the target) and does not
    also name the target unambiguously (target.strong_aliases)."""
    t = (text or "").lower()
    if any(a.lower() in t for a in target.get("strong_aliases", []) if a):
        return False
    return any(re.search(p, t, re.I) for p in target.get("exclude_patterns", []) if p)


def is_relevant(post: Post, target: dict) -> bool:
    if not target or not target.get("require_relevance", False):
        return True

    aliases = [a.lower() for a in target.get("aliases", []) if a]
    handles = [h.lower().lstrip("@") for h in target.get("official_handles", []) if h]

    src = (post.source or "").lower()
    # The target's own accounts are always relevant.
    if src.startswith("company:"):
        return True
    # A keyword or hashtag search also finds namesakes (the same name in another country):
    # drop those even from search sources.
    if names_other_org(f"{post.text} {post.author_id} {post.url or ''}", target):
        return False
    # Search sources are otherwise scoped to the target by the platform query.
    if src.startswith("search:") or src.startswith("demo:"):
        return True

    # First-party content.
    author = (post.author_id or "").lower().lstrip("@")
    if author in handles or any(h in src for h in handles):
        return True

    # Alias mention in the content itself, once phrases that only contain the name are removed.
    return mentions_target(post.text or "", target)


def mentions_target(text: str, target: dict) -> bool:
    """True when the text names the target. target.namesake_phrases (another company whose name
    contains the target's, or a street landmark named after it) are removed first, so they
    alone do not count as a mention."""
    t = (text or "").lower()
    for p in target.get("namesake_phrases", []) or []:
        t = re.sub(p, " ", t, flags=re.I)
    return any(a.lower() in t for a in target.get("aliases", []) if a)
