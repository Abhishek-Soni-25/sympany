"""Follower / subscriber snapshots for the brand's own accounts (Marketing report).

Each refresh records the current public follower count of every account in
config.yaml -> target.owned_accounts:

    instagram  apify/instagram-profile-scraper   (~$0.0026 per profile)
    facebook   apify/facebook-pages-scraper      (~$0.012 per page)
    youtube    the public channel page            (free; YouTube rounds, e.g. "27.1k")

Snapshots are appended to the "followers" document (src/store.py), so "new followers" is the real difference
between two snapshots rather than an estimate. Run as part of every main scan.
"""

from __future__ import annotations

import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from . import store
from .config import env
from .connectors.apify_connector import run_actor

log = logging.getLogger(__name__)

_DOC = "followers"
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_SUBS_RE = re.compile(r'"subscriberCountText":"([\d.,]+)\s*([KkMmBb]?)\s*subscribers?"')
_MULT = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}


def _num(value: Any) -> int | None:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def youtube_subscribers(handle: str) -> int | None:
    """Subscriber count from the channel's public page (as precise as YouTube shows it).
    ``handle`` is an @handle, a channel id (UC...) or a channel URL."""
    handle = handle.strip().rstrip("/")
    if handle.startswith("http"):
        url = f"{handle}/about"
    elif handle.startswith("UC") and len(handle) == 24:
        url = f"https://www.youtube.com/channel/{handle}/about"
    else:
        url = f"https://www.youtube.com/@{handle.lstrip('@')}/about"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+1; SOCS=CAI",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "ignore")
    m = _SUBS_RE.search(html)
    if not m:
        return None
    return int(float(m.group(1).replace(",", "")) * _MULT[m.group(2).lower()])


def instagram_profiles(usernames: list[str], cfg: dict) -> dict[str, dict]:
    """{username: raw profile record} — followersCount plus the ~12 latest posts."""
    token = env("APIFY_TOKEN")
    if not token or not usernames:
        return {}
    actor = cfg.get("apify", {}).get("actors", {}).get("instagram_profile", {}).get("id")
    if not actor:
        return {}
    timeout = cfg.get("apify", {}).get("run_timeout_seconds", 300)
    items = run_actor(token, actor, {"usernames": usernames}, timeout)
    return {str(r.get("username", "")).lower(): r for r in items if r.get("username")}


def facebook_followers(page_url: str, cfg: dict) -> int | None:
    token = env("APIFY_TOKEN")
    actor = cfg.get("apify", {}).get("actors", {}).get("facebook_page_info", {}).get("id")
    if not token or not actor:
        return None
    timeout = cfg.get("apify", {}).get("run_timeout_seconds", 300)
    items = run_actor(token, actor, {"startUrls": [{"url": page_url}]}, timeout)
    for r in items:
        for key in ("followers", "followersCount", "followers_count", "likes"):
            n = _num(r.get(key))
            if n is not None:
                return n
    return None


def refresh(cfg: dict) -> dict[str, Any] | None:
    """Fetch current counts for every owned account and append a snapshot."""
    accounts = cfg.get("target", {}).get("owned_accounts", {}) or {}
    counts: dict[str, int] = {}
    if accounts.get("instagram"):
        try:
            prof = instagram_profiles([accounts["instagram"]], cfg).get(accounts["instagram"].lower(), {})
            n = _num(prof.get("followersCount"))
            if n is not None:
                counts["instagram"] = n
        except Exception as exc:  # noqa: BLE001 — one account failing must not stop the rest
            log.warning("Instagram follower count failed: %s", exc)
    if accounts.get("facebook"):
        try:
            n = facebook_followers(accounts["facebook"], cfg)
            if n is not None:
                counts["facebook"] = n
        except Exception as exc:  # noqa: BLE001
            log.warning("Facebook follower count failed: %s", exc)
    if accounts.get("youtube"):
        try:
            n = youtube_subscribers(accounts["youtube"])
            if n is not None:
                counts["youtube"] = n
        except Exception as exc:  # noqa: BLE001
            log.warning("YouTube subscriber count failed: %s", exc)
    if not counts:
        return None
    snap = {"at": datetime.now(timezone.utc).isoformat(), "counts": counts}
    data = _load()
    data["snapshots"].append(snap)
    data["snapshots"] = data["snapshots"][-200:]            # keep the document small
    try:
        store.put_doc(_DOC, data)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not persist follower snapshot: %s", exc)
    log.info("Follower snapshot: %s", counts)
    return snap


def _load() -> dict[str, Any]:
    data = store.get_doc(_DOC, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("snapshots", [])
    return data


def summary() -> dict[str, Any]:
    """Latest snapshot plus the comparison snapshot used for "new followers".

    The comparison is the newest snapshot at least an hour older than the latest (so two
    scans minutes apart don't read as zero growth), falling back to the oldest one. The
    page shows both timestamps, so a short span is visible as such.
    """
    snaps = sorted(_load()["snapshots"], key=lambda s: s.get("at", ""))
    if not snaps:
        return {"latest": None, "previous": None, "snapshots": []}
    latest = snaps[-1]
    previous = None
    try:
        cutoff = datetime.fromisoformat(latest["at"]) - timedelta(hours=1)
        older = [s for s in snaps[:-1] if datetime.fromisoformat(s["at"]) <= cutoff]
        previous = older[-1] if older else (snaps[0] if len(snaps) > 1 else None)
    except (KeyError, ValueError):
        pass
    return {"latest": latest, "previous": previous, "snapshots": snaps[-60:]}
