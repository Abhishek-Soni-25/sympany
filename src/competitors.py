"""Competitor Share-of-Voice collection (PRD 6.6).

For each competitor keyword, run the configured Apify/Bright Data connectors and score each
post's sentiment toward that competitor with Groq (no risk mapping — SoV only). Every post is
kept in data/competitor_mentions.jsonl (author, engagement, date, language) so the
Competition report compares real engagement, unique users and trends; the SoV table is
aggregated from that store, limited to the configured collection window.

Sympany's own totals are read from the mentions store, so the benchmark is apples-to-apples.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
import re
from datetime import datetime, timezone
from typing import Any

from .connectors import ApifyConnector, BrightDataConnector, ConnectorUnavailable
from .connectors.base import catchup_window
from .pipeline import ingest, sentiment as sentiment_mod
from .models import RiskAssessment
from .connectors.base import LAST_OK
from .pipeline.risk_classifier import RiskClassifier
from . import mentions as mentions_store
from . import scan_status, store

from .main import _parse_date, _within_window

log = logging.getLogger(__name__)

POST_KIND = "competitor_post"
_SOV_DOC = "competitors_sov"
_SCAN_DOC = "competitor_scan"          # {"last_ok": <time of the last complete competitor scan>}


def _post_key(rec: dict) -> str:
    return f"{rec.get('brand')}::{rec.get('platform')}::{rec.get('id')}"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _build_connector(channel: str, keyword, cfg: dict, state_key: str, comp: dict | None = None):
    """One connector for one competitor on one channel: its keyword(s), page URL or app id."""
    keywords = keyword if isinstance(keyword, list) else [keyword]
    max_items = cfg.get("competitors", {}).get("max_items", 5)
    limits = cfg.get("competitors", {}).get("input_limits", {}).get(channel, {})
    ch_cfg = cfg.get("channels", {}).get(channel, {})
    mode = ch_cfg.get("mode")
    if mode == "brightdata":
        bd = cfg.get("brightdata", {})
        return BrightDataConnector(
            channel=channel,
            dataset_id=bd.get("datasets", {}).get(ch_cfg.get("dataset", channel), ""),
            keywords=keywords,
            extra_input=ch_cfg.get("extra_input", {}),
            max_items=max_items,
            poll_timeout=bd.get("poll_timeout_seconds", 300),
            state_key=state_key,
        )
    if mode == "apify":
        ap = cfg.get("apify", {})
        actor = ap.get("actors", {}).get(ch_cfg.get("actor", channel), {})
        return ApifyConnector(
            channel=channel,
            actor_id=actor.get("id", ""),
            keywords=keywords,
            keyword_field=actor.get("keyword_field", "keywords"),
            keyword_as_list=actor.get("keyword_as_list", True),
            input_template={**actor.get("input_template", {}), **limits},
            secret_inputs=actor.get("secret_inputs", {}),
            max_items=max_items,
            timeout=ap.get("run_timeout_seconds", 300),
            state_key=state_key,
            platform=ch_cfg.get("platform"),
            normalizer=ch_cfg.get("normalizer"),
            url_objects=actor.get("url_objects", False),
            limit_field=actor.get("limit_field"),
            since_field=actor.get("since_field"),
            max_limit=actor.get("max_limit"),
            # Agency reviews: only agencies named for this competitor.
            place_must_contain=(comp or {}).get("place_names") or (comp or {}).get("aliases"),
            place_exclude=(comp or {}).get("place_exclude"),
            backfill_sample=(cfg.get("competitors", {}).get("backfill_sample", {}) or {}).get(channel),
        )
    return None


def _names_brand(text: str, comp: dict) -> bool:
    aliases = [a.lower() for a in comp.get("aliases", []) if a] or [comp.get("name", "").lower()]
    t = (text or "").lower()
    return any(a in t for a in aliases)


def _blank() -> dict[str, Any]:
    return {"total": 0, "positive": 0, "neutral": 0, "negative": 0, "by_platform": {}}


def _brand_classifier(base: RiskClassifier, name: str) -> RiskClassifier:
    """A classifier that judges sentiment toward the competitor, not the monitored brand."""
    return RiskClassifier(
        models=base.models, max_tokens=base.max_tokens,
        requests_per_minute=int(60 / base._min_interval) if base._min_interval else 0,
        max_retries=base._max_retries, target_name=name, cfg=base._cfg or None,
    )


_STORES = {"play_store": "Play Store", "app_store": "App Store", "google_maps": "Google Maps"}


def _assess(post, owned: bool, brand_clf, name: str, ai_used: dict, ai_budget: int):
    """Sentiment toward the competitor. Reviews: from the star rating. Public posts: the AI,
    up to competitors.ai_per_brand_per_scan per competitor per scan (competitor scans bring
    thousands of posts). The competitor's own posts and public posts beyond that limit: the
    local VADER scorer. Competitor posts are counted for Share of Voice, not risk-mapped."""
    rating = (post.raw_meta or {}).get("rating")
    try:
        stars = int(rating)
    except (TypeError, ValueError):
        stars = None
    if stars is not None:
        return RiskAssessment(
            is_risk=False, category="NONE", severity="NONE", confidence=1.0,
            rationale=f"{stars}-star review of {name} on {_STORES.get(post.channel, post.channel)}; sentiment taken from the rating.",
            sentiment="negative" if stars <= 2 else "neutral" if stars == 3 else "positive",
            author_type="individual")
    if not owned and ai_used.get(name, 0) < ai_budget:
        ai_used[name] = ai_used.get(name, 0) + 1
        return brand_clf.classify(post)
    v = sentiment_mod.analyze(post.text or "").polarity.lower()
    return RiskAssessment(
        is_risk=False, category="NONE", severity="NONE", confidence=0.6,
        rationale=("Posted by the competitor's own account" if owned else "Beyond this scan's AI limit for competitor posts")
        + "; sentiment from the local text scorer.",
        sentiment=v if v in ("positive", "negative") else "neutral",
        author_type="brand" if owned else "other")


def run_competitor_scan(cfg: dict, classifier) -> dict[str, Any]:
    """Collect + sentiment-score competitor mentions, then persist and return the SoV table."""
    comp_cfg = cfg.get("competitors", {})
    channels = comp_cfg.get("channels", [])
    stored = 0
    # Posts analysed in an earlier scan keep their analysis (only engagement is refreshed);
    # new posts and posts whose analysis failed are analysed (again).
    existing = {_post_key(r): r for r in load_all_competitor_posts()}
    now = datetime.now(timezone.utc).isoformat()
    # Catch-up (connectors/base.py): fetch the days since the last complete competitor scan.
    # Competitor posts are de-duplicated in the post store, not by cursor, so there is no
    # overlap check here; the limits are scaled by the number of days instead.
    last_ok = (store.get_doc(_SCAN_DOC, {}) or {}).get("last_ok") or scan_status.get().get("last_run")
    factor, start, _days = catchup_window(cfg, last_ok)
    max_fetch = int((cfg.get("catchup") or {}).get("max_fetch", 400))

    # One provider run per competitor and channel, asked in parallel (scan.parallel_fetch at a
    # time); the posts are then analysed and stored one run at a time, in order.
    jobs = []
    caps = comp_cfg.get("max_fetch", {}) or {}
    for comp in comp_cfg.get("set", []):
        name, keyword = comp.get("name"), comp.get("keyword")
        if not name or not keyword:
            continue
        for channel in channels:
            # A competitor's own account (first_party: page URL) and its apps (scoped: app id)
            # come from its entry under that channel's name; searches use its keyword(s).
            ch = cfg.get("channels", {}).get(channel, {})
            owned = ch.get("first_party", False)
            needs_target = owned or channel in ("play_store", "app_store")
            # X takes the competitor's own search terms (name + handle); other searches its keyword
            # ("instagram" holds its handle for follower counts, not a search term).
            if needs_target or channel == "x":
                query = comp.get(channel) or (None if needs_target else keyword)
            else:
                query = keyword
            if not query:
                continue
            state_key = f"cmp_{_slug(name)}_{channel}"
            connector = _build_connector(channel, query, cfg, state_key, comp)
            if connector is None:
                continue
            # A channel's first competitor scan loads the collection window (back to
            # collection.since); later scans fetch the days since its last complete scan.
            if not connector.get_cursor(LAST_OK):
                connector.plan_backfill(cfg)
                connector.set_catchup(10 ** 6, connector.backfill_from,
                                      max_fetch=int(caps.get(channel, max_fetch)), check_overlap=False)
            else:
                connector.plan_catchup(cfg)
                connector.set_catchup(connector.catchup_factor, connector.catchup_from,
                                      max_fetch=int(caps.get(channel, max_fetch)), check_overlap=False)
            connector.backfill_new_sources = False
            try:
                connector.setup()
            except ConnectorUnavailable as exc:
                log.warning("Competitor %s/%s unavailable: %s", name, channel, exc)
                continue
            # Posts are de-duplicated in the post store, so re-fetch everything the actor
            # returns rather than skipping ids seen by an earlier scan.
            connector.set_cursor("ids", "[]")
            jobs.append((comp, name, channel, owned, connector))

    workers = max(1, int(cfg.get("scan", {}).get("parallel_fetch", 5)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cmp-fetch") as pool:
        fetches = [pool.submit(job[4].poll) for job in jobs]
        ai_used: dict[str, int] = {}
        ai_budget = int(comp_cfg.get("ai_per_brand_per_scan", 150))
        for (comp, name, channel, owned, connector), fetch in zip(jobs, fetches):
            try:
                posts = fetch.result()
            except ConnectorUnavailable as exc:
                log.warning("Competitor %s/%s unavailable: %s", name, channel, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                log.error("Competitor %s/%s poll error: %s", name, channel, exc)
                continue
            brand_clf = _brand_classifier(classifier, name)
            kept = 0
            # App reviews and the competitor's own agencies are about it by construction.
            scoped = owned or channel in ("play_store", "app_store", "google_maps")
            for post in posts:
                cleaned = ingest.clean_post(post)
                if cleaned is None or not (scoped or _names_brand(cleaned.text, comp)):
                    continue
                prev = existing.get(_post_key({"brand": name, "platform": cleaned.channel, "id": cleaned.message_id}))
                if prev and prev.get("analysis_status", "ok") != "failed":
                    eng = {k: v for k, v in ((cleaned.raw_meta or {}).get("engagement") or {}).items() if v is not None}
                    merged = {**(prev.get("engagement") or {}), **eng}
                    if merged != (prev.get("engagement") or {}):
                        _append_post({**prev, "engagement": merged, "engagement_updated_at": now})
                    kept += 1
                    continue
                rec = mentions_store.build_record(
                    cleaned, _assess(cleaned, owned, brand_clf, name, ai_used, ai_budget))
                rec["brand"] = name
                rec["is_official"] = owned        # posted by the competitor's own page
                _append_post(rec)
                kept += 1
            stored += kept
            connector.commit_cursors()     # this channel's next scan catches up from now
            log.info("Competitor %s/%s: %d items", name, channel, kept)

    payload = load_competitor_sov(cfg)
    try:
        store.put_doc(_SCAN_DOC, {"last_ok": now})
        store.put_doc(_SOV_DOC, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not persist competitor SoV: %s", exc)
    log.info("Competitor scan stored %d post(s)", stored)
    return payload


def _append_post(rec: dict[str, Any]) -> None:
    try:
        store.put_record(POST_KIND, _post_key(rec), rec)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not store competitor post: %s", exc)


def load_all_competitor_posts() -> list[dict[str, Any]]:
    """Every stored competitor post, de-duplicated (no collection-window filter)."""
    return store.list_records(POST_KIND, _post_key)


def save_competitor_posts(records: list[dict[str, Any]]) -> None:
    store.put_records(POST_KIND, [(_post_key(r), r) for r in records])


def load_competitor_posts(cfg: dict | None = None) -> list[dict[str, Any]]:
    """Stored competitor posts, de-duplicated, limited to the collection window."""
    coll = (cfg or {}).get("collection", {})
    since = _parse_date(coll.get("since"))
    until = _parse_date(coll.get("until"), end_of_day=True)
    out = [r for r in load_all_competitor_posts() if _within_window(_parse_date(r.get("timestamp")), since, until)]
    out.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return out


def _own_totals() -> dict[str, Any]:
    agg = _blank()
    for m in mentions_store.for_display():
        agg["total"] += 1
        agg[m.get("sentiment", "neutral")] = agg.get(m.get("sentiment", "neutral"), 0) + 1
        p = m.get("platform", "?")
        agg["by_platform"][p] = agg["by_platform"].get(p, 0) + 1
    return agg


def load_competitor_sov(cfg: dict | None = None) -> dict[str, Any]:
    if load_all_competitor_posts():
        # Aggregate from the per-post store (every configured competitor gets a row).
        results = {c.get("name"): _blank() for c in (cfg or {}).get("competitors", {}).get("set", []) if c.get("name")}
        for r in load_competitor_posts(cfg):
            agg = results.setdefault(r.get("brand", "?"), _blank())
            agg["total"] += 1
            s = r.get("sentiment", "neutral")
            agg[s] = agg.get(s, 0) + 1
            p = r.get("platform", "?")
            agg["by_platform"][p] = agg["by_platform"].get(p, 0) + 1
        return {"own": _own_totals(), "competitors": results}
    data = store.get_doc(_SOV_DOC)                 # legacy aggregate-only table
    if not isinstance(data, dict):
        return {"own": _own_totals(), "competitors": {}}
    data["own"] = _own_totals()                # keep the own-brand block fresh from the store
    data.setdefault("competitors", {})         # never omit the key (frontend iterates it)
    return data
