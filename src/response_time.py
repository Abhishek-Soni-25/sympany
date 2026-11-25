"""First-level response time per brand (Competition report).

Measured on two platforms and combined per brand.

Facebook — each brand's own page posts (already collected by the scans, stored with
is_official) that are at least a day old and have comments: their comments and nested
replies come from apify/facebook-comments-scraper. A reply's permalink carries
`comment_id=<parent>&reply_comment_id=<reply>`, and a reply by the page itself is the
brand's response.

Instagram — for each brand's official account (Sympany from target.owned_accounts,
competitors from competitors.set[].instagram):

  1. read the account's latest posts (apify/instagram-profile-scraper; some profiles come
     back without them, so apify/instagram-post-scraper is the fallback),
  2. take the most recent ones that have comments and pull their comments WITH nested
     replies (apify/instagram-comment-scraper),
  3. for every comment by someone else, the brand's first reply to it gives one
     response time = reply timestamp - comment timestamp (replies come back flattened, so
     they are matched by Instagram's "@user" reply prefix — see _measure).

Per-platform delays and the combined average / median / reply rate are stored in
the "response_times" document (src/store.py). Billed per comment, so the per-brand post and per-post comment
caps in config.yaml -> response_time bound the cost.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import datetime, timezone
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import store
from .config import STATE_DIR, env
from .connectors.apify_connector import run_actor
from .followers import instagram_profiles
from .post_meta import _norm

log = logging.getLogger(__name__)

_DOC = "response_times"
# Raw comment dumps (local development only — re-measurable without re-billing).
_RAW_PATH = STATE_DIR / "response_time_comments.json"
_RAW_FB_PATH = STATE_DIR / "response_time_fb_comments.json"


def _save_raw(path, comments: list[dict]) -> None:
    if store.is_local():
        try:
            path.write_text(json.dumps(comments), encoding="utf-8")
        except OSError:
            pass
_MENTION = re.compile(r"\s*@([A-Za-z0-9._]+)")


def _ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _owner(c: dict) -> str:
    owner = c.get("owner") if isinstance(c.get("owner"), dict) else {}
    return str(c.get("ownerUsername") or owner.get("username") or "").lower()


def brand_handles(cfg: dict) -> dict[str, str]:
    """{brand name: instagram handle} for the monitored brand and every competitor."""
    out: dict[str, str] = {}
    own = (cfg.get("target", {}).get("owned_accounts", {}) or {}).get("instagram")
    if own:
        out[cfg.get("target", {}).get("name", "Brand")] = own
    for c in cfg.get("competitors", {}).get("set", []):
        if c.get("name") and c.get("instagram"):
            out[c["name"]] = c["instagram"]
    return out


def _measure(handle: str, comments: list[dict]) -> dict[str, Any]:
    """Response delays (seconds) for comments by other accounts that the brand replied to.

    Without a login the comment scraper returns replies flattened as ordinary comments, but
    Instagram prefixes every reply with "@<user>". So a brand comment starting "@user" on a
    post is paired with that user's latest earlier comment on the same post. A nested
    replies[] array, when the actor does return one, is used directly.
    """
    handle = handle.lower()
    mine = [c for c in comments if _owner(c) == handle]
    others = [c for c in comments if _owner(c) and _owner(c) != handle]

    first_reply: dict[str, datetime] = {}          # other comment id -> brand's first reply time
    for c in others:
        brand_ts = [t for r in (c.get("replies") or []) if _owner(r) == handle and (t := _ts(r.get("timestamp")))]
        if brand_ts:
            first_reply[str(c.get("id"))] = min(brand_ts)
    for r in mine:
        m = _MENTION.match(r.get("text") or "")
        rt = _ts(r.get("timestamp"))
        if not m or not rt:
            continue
        target = m.group(1).lower()
        earlier = [c for c in others if _owner(c) == target and c.get("postUrl") == r.get("postUrl")
                   and (t := _ts(c.get("timestamp"))) and t <= rt]
        if earlier:
            c = max(earlier, key=lambda x: _ts(x.get("timestamp")))
            cid = str(c.get("id"))
            first_reply[cid] = min(rt, first_reply.get(cid, rt))

    delays = []
    for c in others:
        start, reply = _ts(c.get("timestamp")), first_reply.get(str(c.get("id")))
        if start and reply:
            delays.append(max(0.0, (reply - start).total_seconds()))
    return {"comments": len(others), "delays": delays}


def _summary(comments: int, delays: list[float]) -> dict[str, Any]:
    return {
        "comments": comments,
        "replied": len(delays),
        "reply_rate": round(len(delays) / comments * 100, 1) if comments else None,
        "avg_seconds": round(statistics.mean(delays)) if delays else None,
        "median_seconds": round(statistics.median(delays)) if delays else None,
    }


def _measure_facebook(page_name: str, comments: list[dict]) -> dict[str, Any]:
    """Delays from a page's replies to comments on its own posts (nested FB replies)."""
    page = _norm(page_name)
    top: dict[str, dict] = {}
    replies: list[tuple[str, dict]] = []
    for c in comments:
        if not c.get("commentId"):
            continue
        q = parse_qs(urlparse(str(c.get("commentUrl") or "")).query)
        parent = (q.get("comment_id") or [None])[0]
        if (q.get("reply_comment_id") or int(c.get("threadingDepth") or 0) > 0) and parent:
            replies.append((parent, c))
        else:
            top[str(c["commentId"])] = c
    by_page = lambda c: _norm(c.get("profileName") or "") == page  # noqa: E731
    others = {cid: c for cid, c in top.items() if not by_page(c)}
    first: dict[str, datetime] = {}
    for parent, r in replies:
        t = _ts(r.get("date"))
        if parent in others and by_page(r) and t:
            first[parent] = min(t, first.get(parent, t))
    delays = []
    for cid, reply in first.items():
        start = _ts(others[cid].get("date"))
        if start:
            delays.append(max(0.0, (reply - start).total_seconds()))
    return {"comments": len(others), "delays": delays}


def _write(platform: str, table: dict[str, Any]) -> dict[str, Any]:
    """Store one platform's per-brand results and recompute the combined table."""
    data = load()
    data.setdefault("platforms", {})[platform] = table
    now = datetime.now(timezone.utc).isoformat()
    brands: dict[str, Any] = {}
    for plat, rows in data["platforms"].items():
        for brand, row in rows.items():
            b = brands.setdefault(brand, {"handle": row.get("handle", ""), "posts": 0, "comments": 0,
                                          "delays": [], "by_platform": {}, "measured_at": row.get("measured_at", now)})
            b["posts"] += row.get("posts", 0)
            b["comments"] += row.get("comments", 0)
            b["delays"] += row.get("delays", [])
            b["by_platform"][plat] = {"comments": row.get("comments", 0), "replied": len(row.get("delays", []))}
    data["brands"] = {
        name: {"handle": b["handle"], "posts": b["posts"], "measured_at": b["measured_at"],
               "by_platform": b["by_platform"], **_summary(b["comments"], b["delays"])}
        for name, b in brands.items()
    }
    data["measured_at"] = now
    data["history"] = _with_history(data.get("history") or [], now, data["brands"])
    try:
        store.put_doc(_DOC, data)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not persist response times: %s", exc)
    return data


def refresh(cfg: dict) -> dict[str, Any]:
    """Measure every brand on Facebook and Instagram and persist the table."""
    try:
        refresh_facebook(cfg)
    except Exception:  # noqa: BLE001 — one platform failing must not stop the other
        log.exception("Facebook response-time measurement failed")
    return refresh_instagram(cfg)


def refresh_facebook(cfg: dict) -> dict[str, Any]:
    """Facebook: replies by each brand's page to comments on its own collected page posts."""
    from . import competitors as competitors_store   # local import: competitors imports main
    from . import mentions as mentions_store
    token = env("APIFY_TOKEN")
    actor = cfg.get("apify", {}).get("actors", {}).get("facebook_comments", {}).get("id")
    if not token or not actor:
        return load()
    rt_cfg = cfg.get("response_time", {})
    n_posts = int(rt_cfg.get("facebook_posts_per_brand", 5))
    n_comments = int(rt_cfg.get("facebook_comments_per_post", 15))
    timeout = cfg.get("apify", {}).get("run_timeout_seconds", 300)

    own_name = cfg.get("target", {}).get("name", "Brand")
    owned = [dict(m, brand=own_name) for m in mentions_store.load_mentions()
             if m.get("platform") == "facebook" and m.get("is_official")]
    owned += [p for p in competitors_store.load_competitor_posts(cfg)
              if p.get("platform") == "facebook" and p.get("is_official")]
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)   # give the page time to reply
    picks: dict[str, list[dict]] = {}
    for p in owned:
        t = _ts(p.get("timestamp"))
        if p.get("url") and (p.get("engagement") or {}).get("comments") and t and t <= cutoff:
            picks.setdefault(p["brand"], []).append(p)
    for brand in picks:
        picks[brand].sort(key=lambda p: (p.get("engagement") or {}).get("comments", 0), reverse=True)
        picks[brand] = picks[brand][:n_posts]

    urls = [p["url"] for ps in picks.values() for p in ps]
    comments = run_actor(token, actor, {
        "startUrls": [{"url": u} for u in urls], "resultsLimit": n_comments,
        "includeNestedComments": True, "viewOption": "RANKED_UNFILTERED",
    }, timeout) if urls else []
    _save_raw(_RAW_FB_PATH, comments)

    now = datetime.now(timezone.utc).isoformat()
    table: dict[str, Any] = {}
    for brand, ps in picks.items():
        mine = {p["url"].rstrip("/") for p in ps}
        page_name = ps[0].get("author") or brand
        cs = [c for c in comments if str(c.get("facebookUrl") or c.get("inputUrl") or "").rstrip("/") in mine]
        table[brand] = {"handle": page_name, "posts": len(ps), "measured_at": now, **_measure_facebook(page_name, cs)}
        log.info("Facebook response time %s: %d comments, %d replied", brand, table[brand]["comments"], len(table[brand]["delays"]))
    return _write("facebook", table)


def refresh_instagram(cfg: dict) -> dict[str, Any]:
    """Instagram: replies by each brand's official account to comments on its recent posts."""
    token = env("APIFY_TOKEN")
    handles = brand_handles(cfg)
    timeout = cfg.get("apify", {}).get("run_timeout_seconds", 300)
    if not token or not handles or not cfg.get("apify", {}).get("actors", {}).get("instagram_comments"):
        return load()

    profiles = instagram_profiles(list(handles.values()), cfg)
    latest = {h.lower(): (profiles.get(h.lower()) or {}).get("latestPosts") or [] for h in handles.values()}
    missing = [h for h, posts in latest.items() if not posts]
    posts_actor = cfg.get("apify", {}).get("actors", {}).get("instagram_posts", {}).get("id")
    if missing and posts_actor:
        for p in run_actor(token, posts_actor, {"username": missing, "resultsLimit": 12}, timeout):
            owner = str(p.get("ownerUsername") or "").lower()
            if owner in latest:
                latest[owner].append(p)
    return measure(cfg, handles, latest)


def measure(cfg: dict, handles: dict[str, str], latest: dict[str, list[dict]]) -> dict[str, Any]:
    """Pull comments (with replies) on each brand's recent posts, measure, and persist."""
    token = env("APIFY_TOKEN") or ""
    rt_cfg = cfg.get("response_time", {})
    n_posts = int(rt_cfg.get("posts_per_brand", 5))
    n_comments = int(rt_cfg.get("comments_per_post", 20))
    actor = cfg.get("apify", {}).get("actors", {}).get("instagram_comments", {}).get("id")
    timeout = cfg.get("apify", {}).get("run_timeout_seconds", 300)

    post_urls: dict[str, list[str]] = {}
    for brand, handle in handles.items():
        if not latest.get(handle.lower()):
            log.warning("Response time: no Instagram posts found for @%s (%s)", handle, brand)
            continue
        posts = [p for p in latest[handle.lower()] if (p.get("commentsCount") or 0) > 0 and p.get("url")]
        posts.sort(key=lambda p: p.get("timestamp") or "", reverse=True)
        post_urls[brand] = [p["url"] for p in posts[:n_posts]]

    urls = [u for us in post_urls.values() for u in us]
    comments: list[dict] = []
    if urls:
        comments = run_actor(token, actor, {
            "directUrls": urls, "resultsLimit": n_comments, "includeNestedComments": True,
        }, timeout)
        _save_raw(_RAW_PATH, comments)

    now = datetime.now(timezone.utc).isoformat()
    table: dict[str, Any] = {}
    for brand, handle in handles.items():
        mine = set(post_urls.get(brand, []))
        brand_comments = [c for c in comments if any(str(c.get("postUrl") or c.get("inputUrl") or "").startswith(u.rstrip("/")) for u in mine)]
        table[brand] = {"handle": f"@{handle}", "posts": len(mine), "measured_at": now, **_measure(handle, brand_comments)}
        log.info("Instagram response time %s (@%s): %d comments, %d replied", brand, handle, table[brand]["comments"], len(table[brand]["delays"]))
    return _write("instagram", table)


_HISTORY_KEEP = 365                       # about a year of daily scans; keeps the document small
_SAME_SCAN = timedelta(hours=6)            # Facebook and Instagram of one scan form one entry
_HISTORY_FIELDS = ("comments", "replied", "reply_rate", "avg_seconds", "median_seconds")


def _with_history(history: list[dict], now: str, brands: dict[str, Any]) -> list[dict]:
    """Append this measurement's per-brand summary to the history, so the website can show
    the reply time of a chosen period. The two platforms of one scan are written a few
    minutes apart: the second write replaces the entry the first one made."""
    entry = {"measured_at": now,
             "brands": {name: {k: b.get(k) for k in _HISTORY_FIELDS} for name, b in brands.items()}}
    if history:
        prev = _ts(history[-1].get("measured_at"))
        cur = _ts(now)
        if prev and cur and cur - prev < _SAME_SCAN:
            history = history[:-1]
    return (history + [entry])[-_HISTORY_KEEP:]


def load() -> dict[str, Any]:
    data = store.get_doc(_DOC)
    if isinstance(data, dict):
        return data
    return {"measured_at": None, "brands": {}, "platforms": {}}
