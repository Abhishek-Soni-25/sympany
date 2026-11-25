"""FastAPI backend that serves the React surveillance dashboard.

Endpoints:
    GET  /api/health          liveness
    GET  /api/stats           dashboard aggregates (counts by severity/category/channel)
    GET  /api/cases           list case files (newest first), optional filters
    GET  /api/cases/{id}      single case file
    GET  /api/channels        configured channels + mode (live/demo)
    GET  /api/scan/status     current/last scan status + active LLM model
    POST /api/scan            start a scan (in the web app, or as an ECS task with scan.launch: ecs)
    POST /api/login           sign in with username + password (auth.mode password)
    GET  /api/me              the signed-in user + enabled features
    GET  /api/logout          sign out (clears the session cookie)

Run:  uvicorn src.api:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import load_config, PROJECT_ROOT
from . import auth
from . import case_management
from . import scan_status as scan_state
from . import store
from .connectors.n8n_connector import _fetch as _n8n_fetch, _channel_of, _author_from_url
from .models import Post
from . import mentions as mentions_store
from . import competitors as competitors_store
from . import followers as followers_store
from . import response_time as response_time_store
from . import coverage as coverage_store
from . import keywords as keywords_store
from . import compliance as compliance_mod
from . import media_enrich
from . import scan_runner
from .pipeline.risk_classifier import RiskClassifier, make_classifier

_URGENCY = {"HIGH": "Immediate", "MEDIUM": "Priority", "LOW": "Routine", "NONE": "None"}
_SENT_SCORE = {"negative": -0.6, "positive": 0.6, "neutral": 0.05, "mixed": -0.1}

log = logging.getLogger("surveillance.api")

app = FastAPI(title="Social Media Surveillance API", version="0.1.0")
# The SPA and the API share one origin behind the ALB, so CORS is only needed for local
# development (CORS_ORIGINS, comma-separated, e.g. http://localhost:5173).
_cors = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors:
    app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _no_store(request, call_next):
    """Never cache the API responses or the SPA shell, so a reload always shows the
    latest stored data (and picks up a freshly built frontend bundle) instead of a stale
    cached copy. Hashed static assets (JS/CSS) keep their default long-cache behaviour."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api") or path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response

# --- Lazy singletons -----------------------------------------------------------

# Loaded at import so every endpoint has config even under TestClient (which skips
# the startup event unless used as a context manager). Refreshed again on startup.
_cfg: dict[str, Any] = load_config()
store.configure(_cfg)
_classifier: Optional[RiskClassifier] = None


@app.on_event("startup")
def _startup() -> None:
    global _cfg
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    _cfg = load_config()
    store.configure(_cfg)
    log.info("Startup: storage=%s ai=%s transcription=%s auth=%s scan=%s",
             _cfg.get("storage", {}).get("backend"), _cfg.get("analysis", {}).get("provider"),
             _cfg.get("transcription", {}).get("provider"), auth.mode(_cfg),
             _cfg.get("scan", {}).get("launch"))
    if _scan_launch() != "ecs":
        scan_runner.start_daily(_cfg)       # scan.daily_at (e.g. 06:00 Swiss time); off when empty


# --- Authentication (application sign-in, or Cognito via the ALB) -------------------
# Every /api route except the health check and the sign-in/sign-out calls needs a user.
_PUBLIC_API = {"/api/health", "/api/login", "/api/logout"}


@app.middleware("http")
async def _authenticate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api") and path not in _PUBLIC_API:
        try:
            request.state.user = await run_in_threadpool(
                auth.authenticate, request.headers, _cfg, dict(request.cookies))
        except auth.AuthError as exc:
            return JSONResponse({"detail": f"Not authenticated: {exc}", "auth_mode": auth.mode(_cfg)},
                                status_code=401)
        except Exception:  # noqa: BLE001 — e.g. ALB public key unreachable
            log.exception("authentication error")
            return JSONResponse({"detail": "Authentication unavailable"}, status_code=503)
    if path.startswith("/api/compliance") and not _media_compliance_enabled():
        return JSONResponse({"detail": "Media Compliance is not enabled."}, status_code=404)
    return await call_next(request)


def _user(request: Request) -> auth.User:
    return getattr(request.state, "user", None) or auth.User(sub="anonymous")


def require_admin(request: Request) -> auth.User:
    """Administrative endpoints: scans, keywords, Do's and Don'ts (auth.admin_group)."""
    user = _user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="This action needs the administrator group.")
    return user


def _media_compliance_enabled() -> bool:
    """features.media_compliance (FEATURE_MEDIA_COMPLIANCE). Off: the Media Compliance pages
    are hidden in the dashboard and its upload / extraction endpoints are switched off. The
    code stays in place so the module can be turned back on without a code change."""
    return bool(_cfg.get("features", {}).get("media_compliance", False))


@app.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    return {**_user(request).as_dict(), "auth_mode": auth.mode(_cfg),
            "features": {"media_compliance": _media_compliance_enabled()}}


@app.post("/api/login")
def login(body: dict[str, Any], request: Request) -> JSONResponse:
    """auth.mode password: check the username/password and set the session cookie."""
    if auth.mode(_cfg) != "password":
        raise HTTPException(status_code=404, detail="Sign-in is handled by the load balancer.")
    client = request.client.host if request.client else "unknown"
    try:
        name = auth.login(str(body.get("username") or ""), str(body.get("password") or ""), client)
        hours = float(_cfg.get("auth", {}).get("session_hours", 8))
        token = auth.issue_session(name, hours)
    except auth.AuthError as exc:
        status = 429 if "too many" in str(exc) else 401
        return JSONResponse({"detail": str(exc)}, status_code=status)
    resp = JSONResponse({"ok": True, "user": name})
    resp.set_cookie(auth.SESSION_COOKIE, token, max_age=int(hours * 3600), path="/",
                    secure=request.url.scheme == "https", httponly=True, samesite="strict")
    return resp


@app.get("/api/logout")
def logout(request: Request) -> Response:
    """Sign out. password mode: clear the session cookie. alb mode: expire the ALB session
    cookies, then end the Cognito session (LOGOUT_URL is the Cognito /logout URL)."""
    if auth.mode(_cfg) == "password":
        resp = RedirectResponse("/", status_code=302)
        resp.delete_cookie(auth.SESSION_COOKIE, path="/", secure=request.url.scheme == "https",
                           httponly=True, samesite="strict")
        return resp
    resp = RedirectResponse(os.environ.get("LOGOUT_URL", "/"), status_code=302)
    for name in auth.SESSION_COOKIES:
        resp.set_cookie(name, "", max_age=-1, expires=0, path="/", secure=True, httponly=True)
    return resp


def _get_classifier() -> RiskClassifier:
    global _classifier
    if _classifier is None:
        _classifier = make_classifier(_cfg)
    return _classifier


_live_classifier: Optional[RiskClassifier] = None


def _get_live_classifier() -> RiskClassifier:
    """Un-throttled classifier for the on-demand /api/live endpoint (only ~6 items per
    call, fired concurrently so the dashboard responds quickly)."""
    global _live_classifier
    if _live_classifier is None:
        # Un-throttled: concurrency is capped at the call site instead.
        _live_classifier = make_classifier(_cfg, requests_per_minute=0)
    return _live_classifier


# --- Case-file access ----------------------------------------------------------

def _load_cases() -> list[dict[str, Any]]:
    cases = case_management.load_cases()
    cases.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    # De-duplicate by source URL (keep the newest) so re-scanning the same live
    # Reddit/LinkedIn post doesn't show as multiple cases.
    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for c in cases:
        url = c.get("url")
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        deduped.append(c)
    return deduped


# --- Routes --------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    cases = _load_cases()
    by_sev: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_cat: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    for c in cases:
        by_sev[c.get("severity", "LOW")] = by_sev.get(c.get("severity", "LOW"), 0) + 1
        by_cat[c["risk_category"]] = by_cat.get(c["risk_category"], 0) + 1
        by_channel[c["platform"]] = by_channel.get(c["platform"], 0) + 1
    return {
        "total_cases": len(cases),
        "by_severity": by_sev,
        "by_category": by_cat,
        "by_channel": by_channel,
        "latest": cases[0]["created_at"] if cases else None,
    }


@app.get("/api/cases")
def list_cases(
    severity: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
) -> list[dict[str, Any]]:
    cases = _load_cases()
    if severity:
        cases = [c for c in cases if c.get("severity") == severity.upper()]
    if category:
        cases = [c for c in cases if c.get("risk_category") == category.upper()]
    if channel:
        cases = [c for c in cases if c.get("platform") == channel.lower()]
    return cases


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, Any]:
    for c in case_management.load_cases():
        if c.get("case_id") == case_id:
            return c
    raise HTTPException(status_code=404, detail="case not found")


@app.get("/api/channels")
def channels() -> list[dict[str, Any]]:
    out = []
    for name, ch in _cfg.get("channels", {}).items():
        out.append({
            "name": name,
            "enabled": ch.get("enabled", False),
            "mode": ch.get("mode", "live"),
            "sources": ch.get("sources", []),
        })
    return out


@app.get("/api/mentions")
def mentions(
    platform: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
) -> list[dict[str, Any]]:
    """Every analysed item (newest first) — the primary feed. Each carries its permalink
    (`url`) so it can be opened for verification, the account handle, and Groq sentiment."""
    items = mentions_store.for_display()
    if platform:
        items = [m for m in items if m.get("platform") == platform.lower()]
    if sentiment:
        items = [m for m in items if m.get("sentiment") == sentiment.lower()]
    if severity:
        items = [m for m in items if m.get("severity") == severity.upper()]
    return items


@app.get("/api/authors")
def authors(platform: Optional[str] = Query(None)) -> list[dict[str, Any]]:
    """Per-account activity: how many times each account posted about the keyword, with a
    sentiment split and a link to their latest post for verification."""
    return mentions_store.author_activity(platform)


@app.get("/api/sentiment")
def sentiment_by_platform() -> dict[str, dict[str, int]]:
    """Sentiment breakdown (positive / neutral / negative) per platform."""
    return mentions_store.platform_sentiment()


@app.get("/api/live")
def live(per_channel: int = 3) -> dict[str, Any]:
    """Fetch the n8n webhook, draw `per_channel` Reddit + LinkedIn items at random, and
    classify each with Gemini (concurrently). Returns ALL drawn items (risk or not) for
    direct display — nothing is stored. Falls back to the n8n-provided sentiment if the
    classifier errors (e.g. quota)."""
    url = _cfg.get("n8n", {}).get("webhook_url", "")
    try:
        data = _n8n_fetch(url)
    except Exception as exc:  # noqa: BLE001
        return {"items": [], "error": f"n8n webhook unreachable: {exc}"}

    racm = _cfg.get("racm_mapping", {})
    now = datetime.now(timezone.utc)
    picks: list[tuple[str, dict]] = []
    for ch in ("reddit", "linkedin"):
        mine = [r for r in data if _channel_of(r.get("source", "")) == ch]
        random.shuffle(mine)
        picks.extend((ch, rec) for rec in mine[:per_channel])

    # Build the classifier defensively: if it can't be created (e.g. GROQ_API_KEY not
    # set on the server), don't 500 — fall back to the n8n-provided sentiment.
    try:
        clf = _get_live_classifier()
    except Exception as exc:  # noqa: BLE001
        log.warning("live classifier unavailable, using sentiment fallback: %s", exc)
        clf = None

    def analyze(pair: tuple[str, dict]) -> dict[str, Any]:
        ch, rec = pair
        title = (rec.get("title") or "").strip()
        snippet = (rec.get("snippet") or "").strip()
        text = f"{title}\n{snippet}".strip()
        url_v = rec.get("url") or ""
        n8n_sent = str(rec.get("sentiment") or "Neutral")
        post = Post(
            channel=ch,
            source="Google Search" if ch == "linkedin" else "Reddit (Google Search)",
            message_id=str(abs(hash(url_v or title))),
            author_id=_author_from_url(url_v, ch),
            timestamp=now,
            text=text,
            url=url_v or None,
        )
        a = clf.classify(post) if clf is not None else None
        if a is None or a.rationale.startswith("classifier error"):
            # Fallback: derive risk from the n8n-provided sentiment when the LLM is
            # unavailable (e.g. quota). Never leave an item un-categorised.
            if n8n_sent.lower().startswith("neg"):
                cat, sev, conf = "REPUTATIONAL", "MEDIUM", 0.6
                rationale = "Negative sentiment about Sympany (sentiment-based)."
            else:
                cat, sev, conf = "GENERAL", "NONE", 0.7
                rationale = "General mention of Sympany; analysed, no specific risk indicator."
            inds = []
        else:
            cat, sev, conf, rationale, inds = (
                a.category, a.severity, a.confidence, a.rationale, a.indicators
            )
            # A genuine no-risk result is still categorised GENERAL (not blank).
            if cat == "NONE" or not a.is_risk:
                cat, sev = "GENERAL", "NONE"
                conf = conf or 0.7
                rationale = rationale or "Analysed; no specific risk indicator for Sympany."
        m = racm.get(cat, {})
        return {
            "case_id": f"LIVE-{cat[:3]}-{ch}-{random.randint(10000, 99999)}",
            "platform": ch,
            "source": post.source,
            "timestamp": now.isoformat(),
            "author_ref": post.author_id,
            "raw_content": text,
            "risk_category": cat,
            "severity": sev,
            "sentiment_polarity": n8n_sent,
            "sentiment_score": _SENT_SCORE.get(n8n_sent.lower(), 0.0),
            "confidence": conf,
            "rationale": rationale,
            "indicators": inds,
            "mitigation_urgency": _URGENCY.get(sev, "None"),
            "racm_ref": m.get("racm_ref", "-"),
            "kri_ref": m.get("kri_ref", "-"),
            "url": url_v or None,
            "created_at": now.isoformat(),
        }

    if not picks:
        return {"items": []}
    # Cap concurrency to avoid bursting past Groq's free-tier rate limit (429s).
    with ThreadPoolExecutor(max_workers=3) as ex:
        items = list(ex.map(analyze, picks))
    return {"items": items}


@app.get("/api/scan/status")
def scan_status() -> dict[str, Any]:
    model = None
    if _classifier is not None:
        model = _classifier.active_model
    return {**scan_state.get(), "active_model": model, "models": _cfg.get("analysis", {}).get("models"),
            "quota": scan_runner.quota(_cfg)}


def _scan_launch() -> str:
    """scan.launch: inline (in the web app; "local" is the same) or ecs (separate ECS task)."""
    mode = str(_cfg.get("scan", {}).get("launch", "inline")).lower()
    return "ecs" if mode == "ecs" else "inline"


def _launch_scan(job: str, user: auth.User) -> dict[str, Any]:
    """Start a scan: inline (default) runs it in a background thread of this web task, with a
    lock shared by all web tasks; scan.launch: ecs runs the scan task definition with RunTask."""
    who = user.email or user.sub
    if _scan_launch() == "inline":
        started, reason = scan_runner.launch(job, _cfg, launched_by=who)
        return {"started": True} if started else {"started": False, "reason": reason}
    if scan_state.get()["running"]:
        return {"started": False, "reason": "a scan is already running"}
    if not scan_runner.quota(_cfg)["available"]:
        return {"started": False, "reason": "today's scan has already been run; the next one can be run tomorrow"}
    try:
        arn = _run_ecs_scan_task(job)
    except Exception as exc:  # noqa: BLE001
        log.exception("could not start the scan task")
        raise HTTPException(status_code=502, detail=f"Could not start the scan task: {exc}")
    scan_state.start(job, launched_by=who, task_arn=arn)
    return {"started": True, "task_arn": arn}


def _run_ecs_scan_task(job: str) -> str:
    """ecs:RunTask for the scan task definition (private subnets, no public IP)."""
    import boto3

    from .config import aws_region

    def need(name: str) -> str:
        val = os.environ.get(name, "").strip()
        if not val:
            raise RuntimeError(f"{name} is not set on the web task")
        return val

    resp = boto3.client("ecs", region_name=aws_region(_cfg)).run_task(
        cluster=need("ECS_CLUSTER"),
        taskDefinition=need("SCAN_TASK_DEFINITION"),
        launchType="FARGATE",
        count=1,
        networkConfiguration={"awsvpcConfiguration": {
            "subnets": [x.strip() for x in need("SCAN_SUBNETS").split(",") if x.strip()],
            "securityGroups": [x.strip() for x in need("SCAN_SECURITY_GROUPS").split(",") if x.strip()],
            "assignPublicIp": "DISABLED",
        }},
        overrides={"containerOverrides": [{
            "name": os.environ.get("SCAN_CONTAINER_NAME", "scan"),
            "command": ["python", "-m", "src.scan_job", "--job", job],
        }]},
        startedBy="sympany-web-run-scan",
    )
    if resp.get("failures"):
        raise RuntimeError(str(resp["failures"]))
    return resp["tasks"][0]["taskArn"]


@app.post("/api/scan")
def scan(user: auth.User = Depends(require_admin)) -> dict[str, Any]:
    """Run Scan: the full scan (Sympany posts, followers, competitors, reply times), limited to
    scan.manual_per_day successful runs per Swiss calendar day."""
    return _launch_scan("all", user)


@app.get("/api/competitors")
def competitors() -> dict[str, Any]:
    """Stored competitor Share-of-Voice (Sympany vs the competitor set)."""
    return competitors_store.load_competitor_sov(_cfg)


@app.get("/api/competitors/mentions")
def competitor_mentions() -> list[dict[str, Any]]:
    """Every stored competitor post inside the collection window (brand-tagged)."""
    return competitors_store.load_competitor_posts(_cfg)


@app.get("/api/followers")
def followers() -> dict[str, Any]:
    """Latest follower snapshot for the brand's own accounts + the comparison snapshot."""
    return followers_store.summary()


@app.get("/api/response-times")
def response_times() -> dict[str, Any]:
    """First-level response time per brand (official Facebook and Instagram accounts)."""
    return response_time_store.load()


@app.get("/api/coverage")
def coverage() -> list[dict[str, Any]]:
    """Periods in which a channel may have missed posts (src/coverage.py)."""
    return coverage_store.load()


@app.post("/api/scan/competitors")
def scan_competitors(user: auth.User = Depends(require_admin)) -> dict[str, Any]:
    """The Competition page's scan button: the same full scan as Run Scan (competitors are
    part of it), under the same daily allowance."""
    return _launch_scan("all", user)


@app.get("/api/keywords")
def get_keywords() -> dict[str, Any]:
    return {"base": _cfg.get("keywords", []), "custom": keywords_store.load_custom()}


@app.post("/api/keywords")
def set_keywords(body: dict[str, Any], _admin: auth.User = Depends(require_admin)) -> dict[str, Any]:
    saved = keywords_store.save_custom(body.get("custom", []))
    return {"base": _cfg.get("keywords", []), "custom": saved}


# --- Single-URL video / reel analysis -----------------------------------------------
# Fetch ONE TikTok / YouTube / Instagram video by its URL, transcribe the spoken content,
# score its sentiment & risk with Groq, and store it in the knowledge base.

_VIDEO_HOSTS = {"tiktok": ("tiktok.com",), "youtube": ("youtube.com", "youtu.be"),
                "instagram": ("instagram.com",)}


def _detect_platform(url: str) -> str:
    """The platform of an http(s) link whose host is TikTok / YouTube / Instagram (or one
    of their sub-domains); "unknown" for anything else, e.g. a javascript: URL that merely
    contains "youtube.com" — the URL is stored and shown as a link."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "unknown"
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() not in ("http", "https") or not host:
        return "unknown"
    for platform, domains in _VIDEO_HOSTS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    return "unknown"


def _apify_records_for_urls(actor_key: str, url_field: str, urls: list[str]) -> list[dict]:
    """Run an Apify actor for specific post URLs (not a keyword search)."""
    from .connectors.apify_connector import ApifyConnector

    ap = _cfg.get("apify", {})
    acfg = ap.get("actors", {}).get(actor_key, {})
    conn = ApifyConnector(
        channel=actor_key,
        actor_id=acfg.get("id", ""),
        keywords=["_"],
        input_template=acfg.get("input_template", {}),
        secret_inputs=acfg.get("secret_inputs", {}),
        timeout=ap.get("run_timeout_seconds", 300),
    )
    conn.setup()
    actor_input = conn._base_input()
    actor_input[url_field] = urls
    actor_input["resultsPerPage"] = len(urls)
    return conn._run(actor_input)


def _build_video_post(url: str, platform: str) -> Post | None:
    """Build a normalised Post for a single video URL (transcript added by the caller)."""
    from .connectors.apify_connector import _normalize_tiktok, _normalize_instagram, _to_post

    if platform == "youtube":
        return Post(
            channel="youtube", source="search:youtube-url",
            message_id=str(compliance_mod.youtube_id(url) or abs(hash(url))),
            author_id="youtube", timestamp=datetime.now(timezone.utc),
            text="YouTube video", url=url, raw_meta={"provider": "youtube", "is_video": True},
        )
    if platform in ("tiktok", "instagram"):
        actor_key = platform
        url_field = "postURLs" if platform == "tiktok" else "directUrls"
        records = _apify_records_for_urls(actor_key, url_field, [url])
        if not records:
            return None
        norm = _normalize_tiktok if platform == "tiktok" else _normalize_instagram
        fields = norm(records[0]) or {}
        if not fields.get("text") and not fields.get("url"):
            return None
        rid = str(fields.get("id") or url)
        return _to_post(platform, rid, fields)
    return None


@app.post("/api/analyze/video")
def analyze_video(body: dict[str, Any]) -> dict[str, Any]:
    """Analyse a single TikTok / YouTube / Instagram video by URL: transcribe the reel,
    compute its sentiment + risk with Groq, and persist it to the mentions knowledge base."""
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Provide a video URL.")
    platform = _detect_platform(url)
    if platform == "unknown":
        raise HTTPException(status_code=422, detail="URL is not a TikTok, YouTube or Instagram link.")
    try:
        post = _build_video_post(url, platform)
        if post is None:
            raise HTTPException(status_code=422, detail=f"Could not fetch the {platform} video (check URL / provider credentials).")
        transcript = media_enrich.enrich_post(post, _cfg, {"left": 1})
        assessment = _get_classifier().classify(post)
        rec = mentions_store.record_mention(post, assessment, _cfg.get("target", {}).get("official_handles", []))
        return {
            "analysed": True, "platform": platform,
            "sentiment": assessment.sentiment, "risk_category": assessment.category,
            "severity": assessment.severity, "confidence": assessment.confidence,
            "rationale": assessment.rationale, "indicators": assessment.indicators,
            "transcript": transcript, "text": post.text, "url": post.url,
            "mention_id": rec.get("id"),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("analyze_video failed")
        raise HTTPException(status_code=500, detail=f"Video analysis failed: {exc}")


# --- Media Compliance (FINMA) -------------------------------------------------------
# This backend performs RAW EXTRACTION only. The rule engine, matcher and decision
# logic live in TypeScript under lib/compliance/ and consume the extraction dict.
# It also serves the rule-set overlay and maintains the append-only compliance
# audit register.

# The active rule set and the audit register live in the store (DynamoDB on AWS; the
# audit records go to the separate audit table, kept throughout).
_RULESET_DOC = "ruleset_active"
_RULESET_DEFAULT = PROJECT_ROOT / "config" / "rules" / "sympany-ch-v1.json"

# Upload limits for Media Compliance videos (media.max_upload_mb / max_video_seconds).
def _media_limits() -> tuple[int, int]:
    m = _cfg.get("media", {})
    return int(m.get("max_upload_mb", 200)), int(m.get("max_video_seconds", 600))


def _video_seconds(data: bytes, filename: str) -> float | None:
    """Duration of an uploaded clip via ffprobe (None if unknown)."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffprobe"):
        return None
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, os.path.basename(filename or "video.mp4") or "video.mp4")
        with open(path, "wb") as fh:
            fh.write(data)
        try:
            from .netsafe import FFMPEG_INPUT_SAFETY

            out = subprocess.run(["ffprobe", "-v", "error", *FFMPEG_INPUT_SAFETY, "-show_entries", "format=duration",
                                  "-of", "default=nw=1:nk=1", path], capture_output=True, timeout=60)
            return float(out.stdout.decode().strip() or "nan")
        except Exception:  # noqa: BLE001
            return None


@app.post("/api/compliance/extract")
def compliance_extract(body: dict[str, Any]) -> dict[str, Any]:
    """Image mode: OCR the supplied images and return a normalised extraction asset."""
    images = body.get("images") or ([body["image"]] if body.get("image") else [])
    if not images:
        raise HTTPException(status_code=400, detail="Provide at least one image (data URL).")
    try:
        return compliance_mod.build_extraction(
            assetId=body.get("assetId"),
            adviserId=body.get("adviserId"),
            channel=body.get("channel"),
            images=images,
            transcript=None,
            captionText=body.get("captionText"),
            frames=images,
            metadata=body.get("metadata"),
            cfg=_cfg,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("compliance extract failed")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")


@app.post("/api/compliance/extract/video")
async def compliance_extract_video(
    file: UploadFile = File(...),
    frames: str = Form("[]"),
    captionText: str = Form(""),
    adviserId: str = Form(""),
    channel: str = Form(""),
    metadata: str = Form("{}"),
) -> dict[str, Any]:
    """Video mode: transcribe the file, OCR the frames, union into one extraction asset."""
    try:
        frame_list = json.loads(frames) if frames else []
        if not isinstance(frame_list, list):
            frame_list = []
    except json.JSONDecodeError:
        frame_list = []
    try:
        meta = json.loads(metadata) if metadata else {}
        if not isinstance(meta, dict):
            meta = {}
    except json.JSONDecodeError:
        meta = {}
    meta.setdefault("isVideo", True)
    # Server-side frame sampling drives OCR, so an incomplete browser-side capture no
    # longer forces a partial. Drop the client's expected-frame hint accordingly.
    meta.pop("expectedFrames", None)
    max_mb, max_seconds = _media_limits()
    try:
        # Processed in memory inside this task and discarded after the check — the media is
        # never stored (temporary ffmpeg files are deleted as soon as each step finishes).
        data = await file.read()
        await file.close()
        if len(data) > max_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Video is larger than {max_mb} MB.")
        name = file.filename or "video.mp4"
        seconds = await run_in_threadpool(_video_seconds, data, name)
        if seconds and seconds > max_seconds:
            raise HTTPException(status_code=413, detail=f"Video is longer than {max_seconds // 60} minutes.")

        def work() -> dict[str, Any]:
            transcript = compliance_mod.transcribe(data, name, _cfg)
            # Extract frames from the video on the server (ffmpeg) and OCR those; fall back
            # to any frames the browser captured only if server extraction yielded nothing.
            frames = compliance_mod.sample_video_frames(data, name, _cfg) or frame_list
            return compliance_mod.build_extraction(
                assetId=meta.get("assetId"),
                adviserId=adviserId,
                channel=channel,
                images=frames,
                transcript=transcript,
                captionText=captionText,
                frames=frames,
                metadata=meta,
                cfg=_cfg,
            )

        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("compliance video extract failed")
        raise HTTPException(status_code=500, detail=f"Video extraction failed: {exc}")


@app.post("/api/compliance/extract/link")
def compliance_extract_link(body: dict[str, Any]) -> dict[str, Any]:
    """Link mode: pull a YouTube caption transcript + thumbnail into an extraction asset."""
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Provide a video URL.")
    metadata = dict(body.get("metadata") or {})
    metadata.setdefault("sourceUrl", url)
    metadata.setdefault("isVideo", True)
    try:
        yt = compliance_mod.fetch_youtube(url)
    except Exception as exc:  # noqa: BLE001 — a failed fetch is a 'failed' extraction, not a 500
        log.warning("compliance link fetch failed: %s", exc)
        yt = {}
    thumb = yt.get("thumbnail")
    transcript = yt.get("transcript") or ""
    link_failed = not thumb and not transcript
    frames = [thumb] if thumb else []
    try:
        return compliance_mod.build_extraction(
            assetId=body.get("assetId"),
            adviserId=body.get("adviserId"),
            channel=body.get("channel"),
            images=frames,
            transcript=transcript,
            captionText=body.get("captionText"),
            frames=frames,
            metadata=metadata,
            cfg=_cfg,
            link_failed=link_failed,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("compliance link extract failed")
        raise HTTPException(status_code=500, detail=f"Link extraction failed: {exc}")


@app.get("/api/compliance/ruleset")
def compliance_get_ruleset() -> dict[str, Any]:
    """Return the active rule set: the overlay if present, else the shipped default."""
    try:
        active = store.get_doc(_RULESET_DOC)
        if isinstance(active, dict):
            return active
        with _RULESET_DEFAULT.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        log.exception("failed to read rule set")
        raise HTTPException(status_code=500, detail=f"Could not read rule set: {exc}")


@app.put("/api/compliance/ruleset")
def compliance_put_ruleset(body: dict[str, Any], user: auth.User = Depends(require_admin)) -> dict[str, Any]:
    """Persist a full rule set to the overlay and append a ruleset_change audit entry."""
    if not isinstance(body, dict) or not body.get("version"):
        raise HTTPException(status_code=400, detail="Rule set must include a 'version'.")
    # The signed-in user is the actor on AWS; the client-supplied name is only a fallback.
    actor = (user.email if auth.mode(_cfg) == "alb" else "") or body.get("_actor") or "compliance-officer"
    ruleset = {k: v for k, v in body.items() if k != "_actor"}
    store.put_doc(_RULESET_DOC, ruleset)
    _append_audit({
        "type": "ruleset_change",
        "version": ruleset.get("version"),
        "at": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
    })
    return ruleset


@app.post("/api/compliance/notify")
def compliance_notify(body: dict[str, Any]) -> dict[str, Any]:
    """Record a compliance notification to the post's author (append-only) and return
    a confirmation message for the UI toast."""
    author = (body.get("author") or "the author").strip() or "the author"
    status = (body.get("status") or "reviewed").strip() or "reviewed"
    channel = (body.get("channel") or "post").strip() or "post"
    rec = {
        "author": author,
        "status": status,
        "channel": channel,
        "mentionId": body.get("mentionId"),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store.append_audit("compliance_notification", rec)
    except Exception:  # noqa: BLE001
        log.warning("could not persist compliance notification")
    label = status.replace("_", "-")
    verb = "flagged as" if "non" in status.lower() else "confirmed"
    msg = f"Notification sent to {author}: their {channel} post was {verb} {label}."
    return {"ok": True, "message": msg, "notification": rec}


@app.post("/api/compliance/audit")
def compliance_audit_append(body: dict[str, Any], request: Request) -> dict[str, Any]:
    """Append one audit record (client has already pseudonymised PII) to the register.
    Only the status and decision metadata are stored — never the media itself."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Audit record must be a JSON object.")
    record = dict(body)
    record["receivedAt"] = datetime.now(timezone.utc).isoformat()
    if auth.mode(_cfg) == "alb":
        record["submittedBy"] = _user(request).email or _user(request).sub
    if not record.get("id"):
        record["id"] = "aud_" + uuid.uuid4().hex[:16]
    _append_audit(record)
    return {"ok": True, "id": record["id"]}


@app.get("/api/compliance/audit")
def compliance_audit_list(limit: Optional[int] = Query(None, ge=1)) -> list[dict[str, Any]]:
    """Return audit records, newest first, optionally capped by ?limit=."""
    records = _read_audit()
    records.reverse()  # newest first
    if limit:
        records = records[:limit]
    return records


@app.get("/api/compliance/audit.csv")
def compliance_audit_csv() -> Response:
    """Return the audit register as a CSV attachment (compliance audit export)."""
    import csv
    import io

    columns = [
        "id", "assetHash", "adviserId", "channel", "submittedAt", "extractionStatus",
        "computedOutcome", "finalDisposition", "ruleSetVersion", "hits", "notEvaluated",
        "override",
    ]
    json_cols = {"hits", "notEvaluated", "override"}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for rec in _read_audit():
        row = []
        for col in columns:
            val = rec.get(col)
            if val is None:
                row.append("")
            elif col in json_cols or isinstance(val, (dict, list)):
                row.append(json.dumps(val, ensure_ascii=False))
            else:
                row.append(str(val))
        writer.writerow(row)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="compliance-audit.csv"'},
    )


def _append_audit(record: dict[str, Any]) -> None:
    """Append-only write of one audit record; existing records are never rewritten."""
    record.setdefault("at", record.get("receivedAt") or datetime.now(timezone.utc).isoformat())
    store.append_audit("compliance_audit", record)


def _read_audit() -> list[dict[str, Any]]:
    """The audit register, oldest first."""
    return store.list_audit("compliance_audit")


# --- Serve the built React frontend (same container as the API, behind the ALB) -----
# Mounted LAST so it never shadows the /api/* routes above. Only active when the
# production build exists (i.e. in the container); local dev uses the Vite dev server.
_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
    log.info("Serving frontend from %s", _FRONTEND_DIST)
