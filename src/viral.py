"""Viral-post alert — e-mails Sympany's risk team when a post that is negative or carries a risk
passes an engagement threshold (views / likes / comments / shares) in a later scan.

A post's risk is judged once, from its text, when it is first analysed; only its engagement
is refreshed by later scans. Without this check a complaint judged LOW at 50 views could
reach 50,000 without a new alert. Each post alerts once (``viral_alerted_at`` on its mention
record), and every post that went viral in one scan goes out in a single SNS e-mail.
Configured under escalation.viral in config.yaml.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from . import mentions
from .escalation import publish_alert

log = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = {"views": 10000, "likes": 1000, "comments": 200, "shares": 200}
_MAX_LISTED = 25                       # posts written out in one e-mail; the rest are counted


def _num(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _posted_at(rec: dict) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(rec.get("timestamp")))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _watched(rec: dict) -> bool:
    """Negative, or analysed as carrying some risk — and analysed successfully."""
    if rec.get("analysis_status") == "failed":
        return False
    return rec.get("sentiment") == "negative" or rec.get("severity") not in (None, "", "NONE")


def crossed(rec: dict, thresholds: dict[str, int]) -> dict[str, int]:
    """The engagement numbers of `rec` at or above their threshold, e.g. {"views": 12400}."""
    eng = rec.get("engagement") or {}
    return {m: _num(eng.get(m)) for m, limit in thresholds.items() if limit and _num(eng.get(m)) >= limit}


def _line(rec: dict, hit: dict[str, int], thresholds: dict[str, int]) -> str:
    risk = rec.get("severity") or "NONE"
    if rec.get("risk_category") and rec.get("risk_category") != "NONE":
        risk += f" · {rec['risk_category']}"
    numbers = ", ".join(f"{m} {n:,} (alert at {thresholds[m]:,})" for m, n in hit.items())
    text = " ".join(str(rec.get("text") or "").split())
    return (
        f"[{risk} · {rec.get('sentiment')}] {rec.get('platform')} · {rec.get('author') or '?'}"
        f" · posted {str(rec.get('timestamp') or '')[:10]}\n"
        f"  {numbers}\n"
        f"  \"{text[:200]}{'…' if len(text) > 200 else ''}\"\n"
        f"  Link: {rec.get('url') or 'n/a'}"
    )


def check(cfg: dict) -> int:
    """Alert on watched posts that passed a threshold since the last scan. Returns the number
    of posts alerted. Posts stay unmarked when the e-mail could not be sent, so the next scan
    tries again."""
    vcfg = (cfg.get("escalation", {}) or {}).get("viral", {}) or {}
    if not vcfg.get("enabled", True):
        return 0
    thresholds = {m: _num(v) for m, v in (vcfg.get("thresholds") or DEFAULT_THRESHOLDS).items()}
    max_age = _num(vcfg.get("max_age_days", 7))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age) if max_age > 0 else None

    hits: list[tuple[dict, dict[str, int]]] = []
    for rec in mentions.load_mentions():
        if rec.get("viral_alerted_at") or not _watched(rec):
            continue
        posted = _posted_at(rec)
        if cutoff and (posted is None or posted < cutoff):
            continue                              # older posts: virality is no longer news
        hit = crossed(rec, thresholds)
        if hit:
            hits.append((rec, hit))
    if not hits:
        return 0

    sev_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    hits.sort(key=lambda h: (sev_rank.get(h[0].get("severity"), 3), -max(h[1].values())))
    body = [f"{len(hits)} negative or risky post(s) passed an engagement threshold:", ""]
    body += [_line(rec, hit, thresholds) + "\n" for rec, hit in hits[:_MAX_LISTED]]
    if len(hits) > _MAX_LISTED:
        body.append(f"…and {len(hits) - _MAX_LISTED} more — see the dashboard.")
    if not publish_alert(f"Sympany social listening: {len(hits)} post(s) going viral", "\n".join(body)):
        log.warning("Viral alert for %d post(s) not sent (no alert topic or SNS error); "
                    "retried next scan", len(hits))
        return 0

    now = datetime.now(timezone.utc).isoformat()
    mentions.save_mentions([{**rec, "viral_alerted_at": now, "viral_engagement": hit} for rec, hit in hits])
    log.info("Viral alert sent for %d post(s)", len(hits))
    return len(hits)
