"""Scan task — the ECS Fargate task started by EventBridge Scheduler (or by "Run Scan").

    python -m src.scan_job --job all            # scheduled run (default)
    python -m src.scan_job --job mentions       # Sympany scan + follower snapshot
    python -m src.scan_job --job competitors    # competitor scan + response times

Flow: collect (Apify / Bright Data, keys from Parameter Store) → transcribe video posts
(Amazon Transcribe) → classify (Amazon Bedrock) → store (DynamoDB) → alert (SNS).
The run status is written to the shared "scan_status" document so the dashboard can show
it; a summary is published to the SNS alert topic. The process exits non-zero when the run
fails, so the ECS task's stopped state / a CloudWatch alarm can notify the team.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import competitors, followers, response_time, scan_status, store
from . import main as pipeline
from .config import load_config
from .escalation import Escalation, publish_alert
from .pipeline.risk_classifier import make_classifier

log = logging.getLogger("scan_job")


LOCAL_TZ = ZoneInfo("Europe/Zurich")      # Swiss time (CET / CEST)
_TIER_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_MAX_LISTED = 10                       # risky posts written out in the e-mail; the rest are counted


def _short(brand: str) -> str:
    """'Visana Versicherungen' -> 'Visana'."""
    return re.sub(r"\s+(Kranken)?[Vv]ersicherung(en)?$", "", str(brand)).strip() or str(brand)


def _duration(seconds) -> str:
    if seconds is None:
        return "not measured (no replies found)"
    mins = round(float(seconds) / 60)
    if mins < 1:
        return "under 1 min"
    return f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60} min"


def _day(ts) -> str:
    try:
        d = datetime.fromisoformat(str(ts))
    except ValueError:
        return "?"
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(LOCAL_TZ).strftime("%d %b")


def _post_lines(p: dict) -> list[str]:
    cat = str(p.get("risk_category") or "").replace("_", " ").capitalize()
    tags = " · ".join(t for t in (p.get("tier"), cat if cat and cat != "None" else "", p.get("sentiment")) if t)
    text = " ".join(str(p.get("text") or "").split())
    return [
        f"  [{tags}] {str(p.get('platform') or '?').replace('_', ' ').title()} · {p.get('author') or '?'}"
        f" · {_day(p.get('timestamp'))}",
        f"  \"{text[:200]}{'…' if len(text) > 200 else ''}\"",
        f"  Link: {p.get('url') or 'n/a'}",
    ]


def _summary(job: str, stats: dict, minutes: float, cfg: dict | None = None,
             launched_by: str = "", started: datetime | None = None) -> tuple[bool, str, str]:
    """(anything new?, subject, e-mail text) for the run-summary alert. SNS e-mail is plain
    text and its subject must be ASCII."""
    cfg = cfg or {}
    started = (started or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    m = stats.get("mentions") or {}
    new = int(m.get("analyzed", 0)) + int(m.get("retried_ok", 0))
    flagged = sorted(m.get("flagged") or [], key=lambda p: _TIER_RANK.get(p.get("tier"), 3))
    n_review = int(m.get("HIGH", 0)) + int(m.get("MEDIUM", 0)) + int(m.get("LOW", 0))
    how = "daily scan" if launched_by in ("daily schedule", "scan-task") else f"Run Scan by {launched_by}"

    lines = ["Sympany Social Listening — scan summary",
             f"{started.strftime('%d %b %Y, %H:%M %Z')} · {how} · took {minutes:g} min"]
    if cfg.get("escalation", {}).get("dashboard_url"):
        lines.append(f"Dashboard: {cfg['escalation']['dashboard_url']}")

    if m:
        lines += ["", f"NEEDS REVIEW ({n_review})"]
        if not n_review:
            lines.append("  Nothing new needs review.")
        for i, p in enumerate(flagged[:_MAX_LISTED]):
            lines += ([""] if i else []) + _post_lines(p)
        if n_review > min(len(flagged), _MAX_LISTED):
            lines.append(f"  …and {n_review - min(len(flagged), _MAX_LISTED)} more — see the dashboard.")

        failed = int(m.get("failed", 0)) + int(m.get("retry_failed", 0))
        lines += [
            "", "NEW POSTS",
            f"  Analysed ............ {m.get('analyzed', 0)}   (High {m.get('HIGH', 0)} · Medium "
            f"{m.get('MEDIUM', 0)} · Low {m.get('LOW', 0)} · No risk {m.get('NONE', 0)})",
            f"  Going viral ......... {m.get('viral', 0)}"
            + ("   (sent in a separate e-mail)" if m.get("viral") else ""),
            f"  AI check failed ..... {failed}" + ("   (retried automatically next scan)" if failed else ""),
            f"  Likes/views updated . {m.get('engagement_updated', 0)} posts",
        ]
        if m.get("retried_ok"):
            lines.append(f"  Earlier failures now analysed: {m['retried_ok']}")

    if m:
        gaps = m.get("coverage") or []
        skipped = m.get("not_scanned") or []
        lines += ["", "COVERAGE"]
        if not gaps and not skipped:
            lines.append("  Every channel reached back to its previous scan: no gaps.")
        for g in gaps:
            lines.append(f"  Possible gap · {str(g.get('channel')).replace('_', ' ')}: {g.get('note')}")
        if skipped:
            lines.append("  Not scanned this time (fetched again next scan): "
                         + ", ".join(c.replace("_", " ") for c in skipped))

    followers = {k: v for k, v in (stats.get("followers") or {}).items() if v is not None}
    if followers:
        lines += ["", "FOLLOWERS", "  " + " · ".join(
            f"{k.title().replace('Youtube', 'YouTube')} {int(v):,}"
            for k, v in sorted(followers.items(), key=lambda kv: -int(kv[1])))]

    comp = stats.get("competitors") or {}
    if comp:
        counts = sorted(comp.items(), key=lambda kv: -int(kv[1] or 0))
        own = stats.get("own_posts")
        lines += ["", "COMPETITOR POSTS (collection period, Sympany for comparison)", "  " + " · ".join(
            ([f"{_short(cfg.get('target', {}).get('name', 'Brand'))} {own}"] if own is not None else [])
            + [f"{_short(b)} {n}" for b, n in counts])]

    rt = stats.get("response_times") or {}
    if rt:
        order = sorted(rt.items(), key=lambda kv: (kv[1] is None, kv[1] or 0))
        parts = [f"{_short(b)} {_duration(s)}" for b, s in order]
        lines += ["", "TYPICAL TIME TO REPLY TO CUSTOMERS"]
        lines += ["  " + " · ".join(parts[i:i + 3]) for i in range(0, len(parts), 3)]

    if new:
        subject = (f"Sympany social listening - {started.strftime('%d %b')} - {new} new posts - "
                   + (f"{n_review} to review" if n_review else "nothing to review"))
    else:
        subject = f"Sympany social listening - {started.strftime('%d %b')} - scan completed, no new posts"
    return new > 0, subject, "\n".join(lines)


def run(job: str, cfg: dict) -> dict:
    stats: dict = {}
    classifier = make_classifier(cfg)
    if job in ("all", "mentions"):
        connectors = pipeline.build_connectors(cfg)
        if not connectors:
            raise RuntimeError("no connectors available — check config.yaml and the provider keys")
        try:
            stats["mentions"] = pipeline.run_cycle(connectors, classifier, Escalation(cfg.get("escalation", {})), cfg)
            # No channel could be fetched (e.g. an expired provider key): the scan failed. It
            # does not use up the day, and the "scan FAILED" e-mail gives the reason.
            skipped = stats["mentions"].get("not_scanned") or []
            if skipped and len(skipped) == len(connectors):
                raise RuntimeError(f"no channel could be scanned ({', '.join(skipped)}); the logs give each "
                                   "channel's error, e.g. an expired Apify or Bright Data key")
        finally:
            for c in connectors:
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass
        try:
            snap = followers.refresh(cfg)
            stats["followers"] = (snap or {}).get("counts")
        except Exception:  # noqa: BLE001 — follower counts must not fail the run
            log.exception("follower snapshot failed")
    if job in ("all", "competitors"):
        sov = competitors.run_competitor_scan(cfg, classifier)
        stats["competitors"] = {k: v.get("total", 0) for k, v in sov.get("competitors", {}).items()}
        stats["own_posts"] = (sov.get("own") or {}).get("total")
        try:
            # Reply times change slowly: measured every response_time.every_days (default 7),
            # otherwise the last measurement is reported.
            every = float(cfg.get("response_time", {}).get("every_days", 7))
            last = response_time.load().get("measured_at")
            age_days = ((datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 86400
                        if last else None)
            if age_days is None or age_days >= every - 0.25:
                rt = response_time.refresh(cfg)
            else:
                log.info("Reply times measured %.1f days ago; next measurement after %g days", age_days, every)
                rt = response_time.load()
            # Median: one very late reply would make the average look worse than the usual case.
            stats["response_times"] = {b: r.get("median_seconds", r.get("avg_seconds"))
                                       for b, r in rt.get("brands", {}).items()}
        except Exception:  # noqa: BLE001
            log.exception("response-time measurement failed")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Sympany social listening scan task")
    ap.add_argument("--job", choices=("all", "mentions", "competitors"), default="all")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    cfg = load_config()
    store.configure(cfg)
    return execute(args.job, cfg)


def execute(job: str, cfg: dict, launched_by: str = "scan-task") -> int:
    """One complete scan run: shared status, the scan itself, alerts. Used by the ECS scan
    task (main) and by scans run inside the web app (src/scan_runner.py). Returns 0 / 1."""
    started = time.monotonic()
    started_at = datetime.now(LOCAL_TZ)
    scan_status.start(job, launched_by=launched_by)
    log.info("Scan job '%s' started (%s)", job, launched_by)
    try:
        stats = run(job, cfg)
    except Exception as exc:  # noqa: BLE001
        log.exception("SCAN_JOB_FAILED")
        scan_status.finish(error=str(exc))
        publish_alert("Sympany social listening: scan FAILED", f"Job: {job}\nError: {exc}")
        return 1
    minutes = round((time.monotonic() - started) / 60, 1)
    stats["duration_minutes"] = minutes
    scan_status.finish(stats=stats)
    log.info("Scan job '%s' finished in %.1f min: %s", job, minutes, json.dumps(stats, default=str))
    # escalation.run_summary: new_only (default) e-mails the summary only when the scan found
    # something new; always = every run; off = never. A failed run is always e-mailed (above).
    mode = str(cfg.get("escalation", {}).get("run_summary", "new_only")).lower()
    has_new, subject, text = _summary(job, stats, minutes, cfg, launched_by, started_at)
    if mode == "always" or (mode == "new_only" and has_new):
        publish_alert(subject, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
