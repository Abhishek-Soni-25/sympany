"""Orchestrator / entry point.

Wires the pipeline together:
    poll -> ingest -> sentiment -> classify -> alert -> case -> escalate

Usage:
    python -m src.main --once       # one polling cycle then exit
    python -m src.main               # continuous loop
    python -m src.main --config path/to/config.yaml
"""

from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from .config import load_config
from datetime import datetime, timezone
from .connectors import (
    CONNECTOR_REGISTRY,
    ConnectorUnavailable,
    DemoConnector,
    N8nConnector,
    BrightDataConnector,
    ApifyConnector,
    YouTubeChannelConnector,
)
from .connectors.base import LAST_OK
from .pipeline import ingest, sentiment as sentiment_mod, alerting, relevance
from .pipeline.risk_classifier import make_classifier
from . import case_management
from . import mentions as mentions_store
from . import media_enrich
from . import coverage, scan_status, viral
from .escalation import Escalation
from .models import RiskAssessment

log = logging.getLogger("surveillance")


def _keywords_for(ch_cfg: dict, cfg: dict) -> list[str]:
    """Per-channel keywords, or the shared default keyword list, or the target aliases —
    always merged with user-added custom keywords from the Campaign page."""
    from . import keywords as kw_store
    base = (
        ch_cfg.get("keywords")
        or cfg.get("keywords")
        or cfg.get("target", {}).get("aliases", [])
    )
    return kw_store.merged(base)


def _parse_date(value, end_of_day: bool = False):
    """Parse a YYYY-MM-DD (or ISO) config value into a tz-aware UTC datetime, or None."""
    if not value:
        return None
    try:
        s = str(value).strip()
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")) if ("T" in s or ":" in s) else datetime.strptime(s, "%Y-%m-%d")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if end_of_day and "T" not in s and ":" not in s:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    except (ValueError, TypeError):
        return None


def _within_window(ts, since, until) -> bool:
    """True if ``ts`` falls within [since, until]. Open-ended when a bound is None."""
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if since and ts < since:
        return False
    if until and ts > until:
        return False
    return True


def build_connectors(cfg: dict):
    connectors = []
    max_items = cfg.get("max_items_per_poll", 25)
    # The brand's own accounts (official: true) come first, so every scan collects the owned
    # content before the public mentions.
    channels = sorted(cfg.get("channels", {}).items(), key=lambda kv: not kv[1].get("official", False))
    for name, ch_cfg in channels:
        if not ch_cfg.get("enabled"):
            continue
        mode = ch_cfg.get("mode", "live")
        if mode == "demo":
            connector = DemoConnector(
                channel=name, sources=ch_cfg.get("sources", []), max_items=max_items
            )
        elif mode == "n8n":
            connector = N8nConnector(
                channel=name,
                webhook_url=cfg.get("n8n", {}).get("webhook_url", ""),
                max_items=max_items,
            )
        elif mode == "brightdata":
            bd = cfg.get("brightdata", {})
            dataset_key = ch_cfg.get("dataset", name)
            connector = BrightDataConnector(
                channel=name,
                dataset_id=bd.get("datasets", {}).get(dataset_key, ""),
                keywords=_keywords_for(ch_cfg, cfg),
                keyword_field=ch_cfg.get("keyword_field", "keyword"),
                extra_input=ch_cfg.get("extra_input", {}),
                max_items=max_items,
                poll_timeout=bd.get("poll_timeout_seconds", 180),
            )
        elif mode == "apify":
            ap = cfg.get("apify", {})
            actor_key = ch_cfg.get("actor", name)
            actor_cfg = ap.get("actors", {}).get(actor_key, {})
            first_party = ch_cfg.get("first_party", False)
            # First-party channels pass an explicit input (e.g. the channel URL) and must
            # NOT be mixed with the user's campaign keywords.
            kw = ch_cfg.get("keywords", []) if first_party else _keywords_for(ch_cfg, cfg)
            connector = ApifyConnector(
                channel=name,
                actor_id=actor_cfg.get("id", ""),
                keywords=kw,
                keyword_field=actor_cfg.get("keyword_field", "keywords"),
                keyword_as_list=actor_cfg.get("keyword_as_list", True),
                # extra_input: a channel's own settings on top of the actor's (e.g. the same
                # Instagram actor asked for an account's posts or for posts tagging it).
                input_template={**actor_cfg.get("input_template", {}), **ch_cfg.get("extra_input", {})},
                state_key=ch_cfg.get("state_key"),
                scoped=ch_cfg.get("scoped", False),
                max_limit=actor_cfg.get("max_limit"),
                secret_inputs=actor_cfg.get("secret_inputs", {}),
                max_items=max_items,
                timeout=ap.get("run_timeout_seconds", 300),
                first_party=first_party,
                platform=ch_cfg.get("platform"),
                normalizer=ch_cfg.get("normalizer"),
                place_must_contain=ch_cfg.get("place_must_contain"),
                place_exclude=ch_cfg.get("place_exclude"),
                url_objects=actor_cfg.get("url_objects", False),
                limit_field=actor_cfg.get("limit_field"),
                since_field=actor_cfg.get("since_field"),
            )
        elif mode == "youtube_channel":
            connector = YouTubeChannelConnector(
                channel=name,
                handle=ch_cfg.get("handle", ""),
                max_items=max_items,
            )
        else:
            cls = CONNECTOR_REGISTRY.get(name)
            if not cls:
                log.warning("Unknown channel '%s' in config; skipping.", name)
                continue
            connector = cls(sources=ch_cfg.get("sources", []), max_items=max_items)
        connector.official = bool(ch_cfg.get("official", False))
        try:
            connector.setup()
            connectors.append(connector)
            log.info(
                "Connector ready: %s [%s] (%d source(s))",
                name, mode, len(connector.sources),
            )
        except ConnectorUnavailable as exc:
            log.warning("Connector '%s' unavailable: %s", name, exc)
    return connectors


# Posts with a risk (HIGH / MEDIUM / LOW) kept in the scan stats for the summary e-mail.
_MAX_FLAGGED = 50
_FLAGGED_FIELDS = ("platform", "author", "timestamp", "risk_category", "sentiment", "url")


_REVIEW_SOURCES = {"play_store": "Play Store", "app_store": "App Store", "google_maps": "Google Maps"}


def _rated_review(post, cfg, stats) -> RiskAssessment | None:
    """A star-rated review (Play Store, App Store, Google Maps) analysed from its rating, or
    None when it should go to the AI. Its sentiment is its rating (1-2 negative, 3 neutral,
    4-5 positive). Low-rated reviews with text go to the AI for risk analysis, up to
    analysis.review_ai_per_scan per scan: app stores bring thousands of reviews, more than
    the AI can read in one scan."""
    rating = (post.raw_meta or {}).get("rating")
    try:
        stars = int(rating)
    except (TypeError, ValueError):
        return None
    where = _REVIEW_SOURCES.get(post.channel, post.channel)
    sentiment = "negative" if stars <= 2 else "neutral" if stars == 3 else "positive"
    has_text = len((post.text or "").strip()) >= 15 and not post.text.startswith(f"{stars}-star review")
    budget = int(cfg.get("analysis", {}).get("review_ai_per_scan", 400))
    if stars <= 2 and has_text and stats.get("review_ai", 0) < budget:
        stats["review_ai"] = stats.get("review_ai", 0) + 1
        return None
    note = (" A low rating: not read by the AI in this scan (over the per-scan limit for reviews)."
            if stars <= 2 and has_text else "")
    return RiskAssessment(
        is_risk=False, category="GENERAL", severity="NONE", confidence=1.0,
        rationale=f"{stars}-star review on {where}; sentiment taken from the rating.{note}",
        sentiment=sentiment, author_type="individual",
    )


def _analyse(post, classifier, escalation, cfg, stats, retry_count: int = 0) -> bool:
    """Classify one post, raise a case / alert for HIGH and MEDIUM, and store it. A failed
    AI call is stored as "failed" (retried by the next scan), never as "no risk". Returns
    False when the analysis failed. The post is stored last: a stored post is never
    analysed again, so its case and alert must already exist (an interruption in between
    means a repeated alert rather than a missed one)."""
    target = cfg.get("target", {})
    sent = sentiment_mod.analyze(post.text)
    assessment = _rated_review(post, cfg, stats) or classifier.classify(post)
    limit = int(cfg.get("analysis", {}).get("failed_retry_limit", 10))

    def record() -> dict:
        return mentions_store.record_mention(post, assessment, target.get("official_handles", []),
                                             retry_count=retry_count, final=retry_count >= limit)

    if assessment.failed:
        record()
        return False

    tier = alerting.decide_alert(assessment, cfg.get("thresholds", {}))
    stats[tier] = stats.get(tier, 0) + 1
    if tier in ("HIGH", "MEDIUM"):
        case = case_management.build_case(
            post, sent, assessment, tier, cfg.get("racm_mapping", {}),
            cfg.get("privacy", {}).get("hash_author_ids", True),
        )
        case_management.persist_case(case)
        escalation.handle(case, tier)
    elif tier == "LOW":
        log.info(
            "LOW: %s/%s %s (%.0f%%) - %s",
            post.channel, post.source, assessment.category,
            assessment.confidence * 100, assessment.rationale[:80],
        )
    rec = record()
    flagged = stats.setdefault("flagged", [])
    if tier != "NONE" and len(flagged) < _MAX_FLAGGED:
        # Listed in the scan-summary e-mail (src/scan_job.py).
        flagged.append({"tier": tier, **{k: rec.get(k) for k in _FLAGGED_FIELDS},
                        "text": str(rec.get("text") or "")[:300]})
    return True


def retry_failed(classifier, escalation, cfg, stats) -> None:
    """Analyse again every stored post whose AI analysis failed in an earlier scan, up to
    analysis.failed_retry_limit attempts per post."""
    limit = int(cfg.get("analysis", {}).get("failed_retry_limit", 10))
    for rec in mentions_store.failed_mentions(limit):
        attempt = int(rec.get("retry_count") or 0) + 1
        try:
            ok = _analyse(mentions_store.post_from_record(rec), classifier, escalation, cfg, stats,
                          retry_count=attempt)
        except Exception as exc:  # noqa: BLE001 — the post stays "failed" and is retried next scan
            log.error("Could not retry %s/%s: %s", rec.get("platform"), rec.get("id"), exc)
            continue
        if ok:
            stats["retried_ok"] += 1
        else:
            stats["retry_failed"] += 1
            if attempt >= limit:
                log.warning("Giving up on %s/%s after %d failed analyses",
                            rec.get("platform"), rec.get("id"), attempt)


def run_cycle(connectors, classifier, escalation, cfg) -> dict:
    target = cfg.get("target", {})

    # Collection window (e.g. the last 3 months). Items outside it are dropped so the
    # knowledge base only holds the requested period. Also caps how many videos/reels
    # are transcribed per scan (the most expensive step).
    coll = cfg.get("collection", {})
    since = _parse_date(coll.get("since"))
    until = _parse_date(coll.get("until"), end_of_day=True)
    video_budget = {"left": int(coll.get("max_video_transcriptions", 40))}

    # analyzed = new posts analysed; failed = new posts whose analysis failed;
    # retried_ok / retry_failed = earlier failures analysed again; engagement_updated =
    # stored posts whose likes / comments / views were refreshed; flagged = the posts with a
    # risk, listed in the summary e-mail.
    stats = {"ingested": 0, "filtered": 0, "analyzed": 0, "failed": 0,
             "retried_ok": 0, "retry_failed": 0, "engagement_updated": 0, "viral": 0,
             "HIGH": 0, "MEDIUM": 0, "LOW": 0, "NONE": 0, "flagged": []}

    # 1) Earlier posts whose analysis failed (e.g. Bedrock throttling) are retried first.
    retry_failed(classifier, escalation, cfg, stats)

    # Posts already stored (e.g. by a scan cut short before it saved its cursors) are
    # never analysed or alerted on again.
    existing = mentions_store.load_mentions()
    stored = {mentions_store.key_of(m) for m in existing}
    # Sympany's YouTube videos by id, whichever own-YouTube platform they are stored under, so a
    # video found by both the channel and the Shorts source is stored once.
    own_youtube = {str(m.get("id")): m.get("platform") for m in existing
                   if m.get("platform") in mentions_store.OWN_YOUTUBE}

    # Catch-up: each channel fetches the posts published since its last complete scan
    # (connectors/base.py), up to catchup.max_days back. A channel's first scan looks back
    # collection.backfill_days (3 months); so does a keyword added since the last scan.
    stats["coverage"] = []
    stats["not_scanned"] = []

    for connector in connectors:
        if not connector.get_cursor(LAST_OK):
            connector.plan_backfill(cfg)
        else:
            connector.plan_catchup(cfg)
        # A high-volume source (app reviews) can raise its own cap above catchup.max_fetch.
        own_cap = (cfg.get("channels", {}).get(connector.channel, {}) or {}).get("max_fetch")
        if own_cap:
            connector.max_fetch = int(own_cap)

    # The providers are asked in parallel (each run mostly waits for the provider), up to
    # scan.parallel_fetch at a time; their posts are then handled one channel at a time, in
    # channel order (Sympany's own accounts first), exactly as a sequential scan would.
    pool = ThreadPoolExecutor(max_workers=max(1, int(cfg.get("scan", {}).get("parallel_fetch", 5))),
                              thread_name_prefix="fetch")
    fetches = [pool.submit(c.poll) for c in connectors]
    for connector, fetch in zip(connectors, fetches):
        try:
            posts = fetch.result()
        except Exception as exc:
            log.error("Poll error on %s: %s", connector.channel, exc)
            connector.discard_cursors()
            # Not a gap: the cursor did not move, so the next scan fetches these days again.
            stats["not_scanned"].append(connector.channel)
            continue

        # 2) Posts the provider returned again: refresh their engagement numbers.
        stats["engagement_updated"] += mentions_store.update_engagement(
            getattr(connector, "engagement_updates", []))

        # 3) New posts: window + relevance filter, transcript, analysis, alerts. The
        # cursors are saved only when every post was handled; otherwise the next scan
        # fetches them again (the stored ones are skipped above).
        complete = True
        for post in posts:
            try:
                cleaned = ingest.clean_post(post)
                if cleaned is None:
                    continue
                key = mentions_store.key_of({"platform": cleaned.channel, "id": cleaned.message_id})
                if cleaned.channel in mentions_store.OWN_YOUTUBE and str(cleaned.message_id) in own_youtube:
                    stats["engagement_updated"] += mentions_store.update_engagement(
                        [(own_youtube[str(cleaned.message_id)], cleaned.message_id,
                          (cleaned.raw_meta or {}).get("engagement") or {})])
                    continue
                if key in stored:
                    stats["engagement_updated"] += mentions_store.update_engagement(
                        [(cleaned.channel, cleaned.message_id, (cleaned.raw_meta or {}).get("engagement") or {})])
                    continue

                # Keep only content inside the configured collection window.
                if not _within_window(cleaned.timestamp, since, until):
                    stats["filtered"] += 1
                    continue
                stats["ingested"] += 1

                # Narrow to content about the monitored target before spending tokens.
                if not relevance.is_relevant(cleaned, target):
                    stats["filtered"] += 1
                    continue

                # Video / reel channels: fold a transcript of the spoken content into the
                # text so the sentiment/risk pass scores the clip, not just its caption.
                try:
                    media_enrich.enrich_post(cleaned, cfg, video_budget)
                except Exception as exc:  # noqa: BLE001 — enrichment must never break a scan
                    log.info("media enrichment skipped for %s: %s", cleaned.channel, exc)

                # Always analyze; the LLM is the real decision-maker. (The VADER score is
                # carried for context and could gate cost in a higher-volume deployment.)
                stats["analyzed" if _analyse(cleaned, classifier, escalation, cfg, stats) else "failed"] += 1
                stored.add(key)
                if cleaned.channel in mentions_store.OWN_YOUTUBE:
                    own_youtube[str(cleaned.message_id)] = cleaned.channel
            except Exception as exc:  # noqa: BLE001 — one post must not stop the scan
                complete = False
                log.error("Could not process %s post %s: %s", connector.channel,
                          getattr(post, "message_id", "?"), exc)
        if complete:
            connector.commit_cursors()
        else:
            connector.discard_cursors()
            log.warning("%s: not every post was stored; they are fetched again next scan.",
                        connector.channel)
        for note in connector.gaps:
            log.warning("Coverage %s: %s", connector.channel, note)
        if connector.gaps:
            coverage.record(connector.channel, connector.window_from, connector.gaps)
            stats["coverage"] += [{"channel": connector.channel, "note": n} for n in connector.gaps]

    pool.shutdown(wait=True)

    # 4) Negative / risky posts whose engagement passed a threshold: one alert e-mail.
    try:
        stats["viral"] = viral.check(cfg)
    except Exception as exc:  # noqa: BLE001 — the viral check must not fail the scan
        log.error("Viral-post check failed: %s", exc)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Social media surveillance pipeline")
    parser.add_argument("--once", action="store_true", help="Run a single cycle then exit")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)

    # Retention purge on startup (privacy/compliance).
    case_management.purge_expired(cfg.get("privacy", {}).get("retention_days", 0))

    connectors = build_connectors(cfg)
    if not connectors:
        log.error("No connectors are enabled/available. Check config.yaml and .env.")
        return

    classifier = make_classifier(cfg)
    escalation = Escalation(cfg.get("escalation", {}))

    interval = cfg.get("poll_interval_seconds", 120)
    try:
        while True:
            log.info("--- polling cycle start ---")
            stats = run_cycle(connectors, classifier, escalation, cfg)
            log.info(
                "Cycle done: ingested=%(ingested)d filtered=%(filtered)d "
                "analyzed=%(analyzed)d HIGH=%(HIGH)d MEDIUM=%(MEDIUM)d "
                "LOW=%(LOW)d NONE=%(NONE)d", stats
            )
            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Interrupted; shutting down.")
    finally:
        for c in connectors:
            try:
                c.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
