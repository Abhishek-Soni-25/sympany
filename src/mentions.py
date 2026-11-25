"""Mentions store — a lightweight log of EVERY analysed item (not just flagged cases).

Flagged HIGH/MEDIUM items become case files (case_management.py) for the audit trail. But the
dashboard also needs the full picture: sentiment per platform, and how many times each account
has posted about a keyword. Persisting only cases would miss all the neutral/positive/low items.

So each analysed post is appended here as one compact JSON line with only the fields the UI
uses. De-duplicated by (platform, id). Stored through src/store.py (DynamoDB on AWS,
data/mentions.jsonl locally).

A post whose AI analysis failed is stored with analysis_status "failed" (sentiment "failed")
and keeps everything needed to analyse it again; the next scan retries it (main.retry_failed).
Posts that a provider returns again in a later scan get their engagement numbers refreshed
(update_engagement) without being analysed again.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from .models import Post, RiskAssessment
from . import post_meta, store

log = logging.getLogger(__name__)

KIND = "mention"


def _key(platform: str, mid: str) -> str:
    return f"{platform}::{mid}"


def key_of(rec: dict) -> str:
    return _key(rec.get("platform", ""), rec.get("id", ""))


def load_mentions() -> list[dict[str, Any]]:
    """All mentions, newest first, de-duplicated by (platform, id) keeping the latest."""
    out = store.list_records(KIND, key_of)
    out.sort(key=lambda r: r.get("analysed_at", ""), reverse=True)
    return out


# Sympany's own YouTube uploads come from two sources (the channel's videos and its Shorts), and
# the old channel feed listed Shorts too: one video can be stored under both platforms.
OWN_YOUTUBE = ("youtube_channel", "youtube_shorts")


def for_display() -> list[dict[str, Any]]:
    """The stored mentions as the dashboard and the counts should see them: an own YouTube
    video stored under both own-YouTube platforms appears once (the record with the most
    engagement), and a video whose link is a /shorts/ link is shown as a Short."""
    out: list[dict[str, Any]] = []
    videos: dict[str, dict[str, Any]] = {}
    stored = load_mentions()
    # The YouTube keyword search also finds the insurer's own uploads: those are already
    # counted from the channel, so the search copy is left out.
    own_ids = {_video_id(m) for m in stored if m.get("platform") in OWN_YOUTUBE} - {""}
    for m in stored:
        if m.get("platform") == "youtube" and _video_id(m) in own_ids:
            continue
        if m.get("platform") not in OWN_YOUTUBE:
            out.append(m)
            continue
        if "/shorts/" in str(m.get("url") or ""):
            m = {**m, "platform": "youtube_shorts"}
        vid = str(m.get("id") or "")
        cur = videos.get(vid)
        if cur is None or _engagement(m) > _engagement(cur):
            videos[vid] = m
    out.extend(videos.values())
    out.sort(key=lambda r: r.get("analysed_at", ""), reverse=True)
    return out


def _video_id(m: dict[str, Any]) -> str:
    """The 11-character YouTube video id from the post's link ("" when there is none)."""
    found = re.search(r"(?:[?&]v=|/shorts/|youtu\.be/)([\w-]{11})", str(m.get("url") or ""))
    return found.group(1) if found else ""


def _engagement(m: dict[str, Any]) -> int:
    return sum(int(v or 0) for v in (m.get("engagement") or {}).values() if isinstance(v, (int, float)))


def save_mentions(records: list[dict[str, Any]]) -> None:
    """Upsert several mention records (used by maintenance tools)."""
    store.put_records(KIND, [(key_of(r), r) for r in records])


def record_mention(
    post: Post, assessment: RiskAssessment, official_handles: list[str] | None = None,
    retry_count: int = 0, final: bool = False,
) -> dict[str, Any]:
    """Append a normalised mention record and return it. A storage error is raised, so the
    scan knows the post was not stored and fetches it again next time."""
    rec = build_record(post, assessment, official_handles, retry_count=retry_count, final=final)
    store.put_record(KIND, key_of(rec), rec)
    return rec


def _http_url(url: Any) -> str | None:
    """`url` if it is an http(s) link, else None. Stored links are shown as clickable in the
    dashboard and reports, so other schemes (javascript:, data:) are never kept."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    try:
        return url if urlsplit(url).scheme.lower() in ("http", "https") else None
    except ValueError:
        return None


def build_record(
    post: Post, assessment: RiskAssessment, official_handles: list[str] | None = None,
    retry_count: int = 0, final: bool = False,
) -> dict[str, Any]:
    """The compact JSON record stored for one analysed post (shared with competitor posts).
    `final`: a failed analysis that has used up its automatic retries."""
    meta = post.raw_meta or {}
    author = meta.get("author_name") or post.author_id
    hint = "video" if meta.get("is_video") else meta.get("media_type")
    rec = {
        "id": post.message_id,
        "platform": post.channel,
        "provider": meta.get("provider"),
        "author": author,
        "author_url": _http_url(meta.get("author_url")),
        "url": _http_url(post.url),          # permalink — click to open & verify
        "text": post.text,
        "keyword": meta.get("keyword"),
        "engagement": meta.get("engagement") or {},
        "sentiment": assessment.sentiment,   # positive | neutral | negative
        "risk_category": assessment.category,
        "severity": assessment.severity,
        "confidence": assessment.confidence,
        "rationale": assessment.rationale,
        "indicators": assessment.indicators,
        "language": assessment.language or post_meta.script_language(post.text),
        "author_type": assessment.author_type,
        "media_type": post_meta.media_type(post.channel, post.url, post.text, hint),
        "is_official": post_meta.is_official(author, meta.get("author_url"), official_handles or []),
        "timestamp": post.timestamp.isoformat(),
        "analysed_at": datetime.now(timezone.utc).isoformat(),
        "source": post.source,
        "analysis_status": "ok",
    }
    # App and agency reviews carry a star rating (and, for apps, the version reviewed).
    if meta.get("rating") is not None:
        rec["rating"] = meta.get("rating")
    if meta.get("app_version"):
        rec["app_version"] = meta.get("app_version")
    if assessment.failed:
        reason = assessment.rationale.removeprefix("classifier error:").strip()[:300]
        rec.update(
            analysis_status="failed",
            sentiment="failed",
            retry_count=retry_count,
            error=reason,
            rationale=(f"AI analysis failed after {retry_count + 1} attempts ({reason}). It is no longer retried automatically."
                       if final else f"AI analysis failed ({reason}). It is retried automatically on the next scan."),
        )
    return rec


def post_from_record(rec: dict[str, Any]) -> Post:
    """Rebuild the analysed Post from its stored record (to retry a failed analysis). The
    stored text already includes any video transcript, so nothing is fetched again."""
    try:
        ts = datetime.fromisoformat(str(rec.get("timestamp")))
    except ValueError:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return Post(
        channel=rec.get("platform", ""),
        source=rec.get("source") or rec.get("provider") or rec.get("platform", ""),
        message_id=str(rec.get("id", "")),
        author_id=str(rec.get("author") or ""),
        timestamp=ts,
        text=rec.get("text") or "",
        url=rec.get("url"),
        raw_meta={
            "provider": rec.get("provider"),
            "author_name": rec.get("author"),
            "author_url": rec.get("author_url"),
            "keyword": rec.get("keyword"),
            "engagement": rec.get("engagement") or {},
            "is_video": rec.get("media_type") == "video",
        },
    )


def failed_mentions(limit: int) -> list[dict[str, Any]]:
    """Stored mentions whose AI analysis failed and that have retries left (oldest first)."""
    out = [m for m in load_mentions()
           if m.get("analysis_status") == "failed" and int(m.get("retry_count") or 0) < limit]
    out.sort(key=lambda m: m.get("analysed_at", ""))
    return out


def update_engagement(updates: Iterable[tuple[str, str, dict]]) -> int:
    """Refresh likes / comments / views of already-stored posts from a newer provider result.
    `updates` holds (platform, id, engagement). Only changed records are written; the
    analysis itself is kept. Returns the number of posts updated."""
    pending = [(p, str(i), e) for p, i, e in updates if e]
    if not pending:
        return 0
    by_key = {key_of(m): m for m in load_mentions()}
    now = datetime.now(timezone.utc).isoformat()
    changed: dict[str, dict[str, Any]] = {}
    for platform, mid, eng in pending:
        k = _key(platform, mid)
        rec = changed.get(k) or by_key.get(k)
        if rec is None:
            continue
        fresh = {name: val for name, val in eng.items() if val is not None}
        merged = {**(rec.get("engagement") or {}), **fresh}
        if merged != (rec.get("engagement") or {}):
            changed[k] = {**rec, "engagement": merged, "engagement_updated_at": now}
    if changed:
        try:
            save_mentions(list(changed.values()))
        except Exception as exc:  # noqa: BLE001 — a storage hiccup must not stop a scan
            log.warning("Could not refresh engagement: %s", exc)
            return 0
    return len(changed)


def author_activity(platform: str | None = None) -> list[dict[str, Any]]:
    """Per-account post counts about the monitored keyword, most active first.

    Answers: "how many times has this account posted about the keyword?" — with a
    sentiment split and the account's most recent post so it can be opened for verification.
    """
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for m in for_display():
        if platform and m.get("platform") != platform:
            continue
        author = (m.get("author") or "unknown").strip() or "unknown"
        gkey = (m.get("platform", ""), author)
        a = agg.setdefault(gkey, {
            "author": author,
            "platform": m.get("platform"),
            "author_url": m.get("author_url"),
            "posts": 0,
            "negative": 0, "neutral": 0, "positive": 0,
            "flagged": 0,
            "latest_url": None,
            "latest_at": "",
        })
        a["posts"] += 1
        a[m.get("sentiment", "neutral")] = a.get(m.get("sentiment", "neutral"), 0) + 1
        if m.get("severity") in ("HIGH", "MEDIUM"):
            a["flagged"] += 1
        if m.get("timestamp", "") >= a["latest_at"]:
            a["latest_at"] = m.get("timestamp", "")
            a["latest_url"] = m.get("url")
    out = list(agg.values())
    out.sort(key=lambda a: a["posts"], reverse=True)
    return out


def platform_sentiment() -> dict[str, dict[str, int]]:
    """Sentiment counts per platform: {platform: {positive, neutral, negative, total}}."""
    out: dict[str, dict[str, int]] = {}
    for m in for_display():
        p = m.get("platform", "unknown")
        d = out.setdefault(p, {"positive": 0, "neutral": 0, "negative": 0, "total": 0})
        d[m.get("sentiment", "neutral")] = d.get(m.get("sentiment", "neutral"), 0) + 1
        d["total"] += 1
    return out
