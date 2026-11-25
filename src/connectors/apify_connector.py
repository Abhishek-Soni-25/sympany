"""Apify connector — keyword-search Actors for LinkedIn, Instagram, Telegram and Quora.

An Apify *Actor* is a hosted scraper that takes a JSON input (including the search term) and
writes results to a dataset. We use the synchronous run endpoint, which starts the Actor,
waits for it to finish, and returns the dataset items in one call:

    POST https://api.apify.com/v2/acts/<actor_id>/run-sync-get-dataset-items?token=<token>
         body = <actor input JSON>
    -> [ {record}, {record}, ... ]

Every actor has its own input schema and its own output fields, so this module keeps a small
per-platform NORMALIZER that maps each actor's raw record onto the fields our platform
actually uses — nothing more:

    permalink (click-to-open), author handle + profile url (per-account counts),
    text (for Groq sentiment/risk), timestamp, and light engagement (likes/comments/views).

Actor ids and input templates live in config.yaml -> apify.actors (see docs/data-providers.md).
"""

from __future__ import annotations

import json
import re
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import env
from ..models import Post
from .base import BaseConnector, ConnectorUnavailable

log = logging.getLogger(__name__)

_BASE = "https://api.apify.com/v2"


class ApifyConnector(BaseConnector):
    """Generic Apify Actor connector, normalised per channel.

    Config (config.yaml -> channels.<name> + apify.actors.<actor>):
        mode: apify
        actor: linkedin        # key into apify.actors
    """

    def __init__(
        self,
        channel: str,
        actor_id: str,
        keywords: list[str],
        keyword_field: str = "keywords",
        keyword_as_list: bool = True,
        input_template: dict | None = None,
        secret_inputs: dict[str, str] | None = None,
        max_items: int = 25,
        timeout: int = 300,
        state_key: str | None = None,
        first_party: bool = False,
        platform: str | None = None,
        normalizer: str | None = None,
        url_objects: bool = False,
        limit_field: str | None = None,
        since_field: str | None = None,
        scoped: bool = False,
        max_limit: int | None = None,
        place_must_contain: list[str] | None = None,
        place_exclude: list[str] | None = None,
        backfill_sample: dict | None = None,
    ) -> None:
        self.channel = channel  # set before base builds its state path
        super().__init__(sources=keywords, max_items=max_items, state_key=state_key)
        self._actor_id = actor_id
        self._keyword_field = keyword_field
        self._keyword_as_list = keyword_as_list
        self._input_template = input_template or {}
        # secret_inputs: {actor_input_field: ENV_VAR_NAME} injected at run time from .env.
        self._secret_inputs = secret_inputs or {}
        self._timeout = timeout
        # first_party: this actor scrapes the org's OWN channel (e.g. its YouTube uploads),
        # so every item is relevant by definition — mark the source so the relevance filter
        # keeps it even when a title doesn't happen to contain a brand alias.
        self._first_party = first_party
        # platform: the platform name stored on each post (e.g. a "facebook_page" channel
        # stores its posts as "facebook"); normalizer: which normaliser to apply;
        # url_objects: the actor wants [{"url": ...}] instead of plain keyword strings.
        self._platform = platform or channel
        self._normalizer = normalizer or channel
        self._url_objects = url_objects
        # limit_field: the actor input that caps the results of a run (scaled for catch-up);
        # since_field: the actor input that takes a start date (YYYY-MM-DD), if any.
        self._limit_field = limit_field
        self._since_field = since_field
        # scoped: every result is about the brand by construction (posts tagging its account,
        # its hashtag), so it passes the relevance filter like a search for the brand.
        self._scoped = scoped
        # max_limit: the largest value the actor accepts in limit_field (it rejects more).
        self._max_limit = max_limit
        # Google Maps: keep only agencies whose name names the insurer (place_must_contain) and
        # not a similarly named one (place_exclude), e.g. another business with "css" in its name.
        self._place_must = [w.lower() for w in place_must_contain or []]
        self._place_exclude = [w.lower() for w in place_exclude or []]
        # backfill_sample {every_days, per_window, until_field}: a first scan asks for up to
        # per_window posts in each every_days window instead of the newest max_fetch, so a
        # high-volume source (tweets, a big insurer's app reviews) is represented across the whole
        # collection window rather than only its last days.
        self._sample = backfill_sample or {}
        self._token: str | None = None

    def setup(self) -> None:
        self._token = env("APIFY_TOKEN")
        if not self._token:
            raise ConnectorUnavailable("Apify token missing or PLACEHOLDER (APIFY_TOKEN, Parameter Store /sympany-socmon/APIFY_TOKEN).")
        if not self._actor_id:
            raise ConnectorUnavailable(
                f"No actor id configured for Apify channel '{self.channel}'."
            )
        if not self.sources:
            raise ConnectorUnavailable(
                f"No keywords configured for Apify channel '{self.channel}'."
            )

    def _run(self, actor_input: dict) -> list[dict]:
        return run_actor(self._token or "", self._actor_id, actor_input, self._timeout)

    def _run_once(self, actor_input: dict) -> list[dict]:
        try:
            return self._run(actor_input)
        except Exception as exc:
            raise ConnectorUnavailable(f"Apify actor run failed: {exc}") from exc

    def _base_input(self) -> dict:
        actor_input = dict(self._input_template)
        for field, env_name in self._secret_inputs.items():
            val = env(env_name)
            if val:
                actor_input[field] = _maybe_json(val)
        return actor_input

    def poll(self) -> list[Post]:
        # Quora takes a single searchQuery string; the others take a keywords array. Keywords
        # added since the last scan run on their own, looking back over the backfill window.
        new = self.new_sources()
        runs: list[tuple[dict, bool]] = []
        if self._keyword_as_list:
            for group, backfill in (([s for s in self.sources if s not in new], False),
                                    ([s for s in self.sources if s in new], True)):
                if not group:
                    continue
                actor_input = self._base_input()
                actor_input[self._keyword_field] = [{"url": s} for s in group] if self._url_objects else group
                runs.append((actor_input, backfill))
        else:
            for kw in self.sources:
                actor_input = self._base_input()
                actor_input[self._keyword_field] = kw
                runs.append((actor_input, kw in new))

        seen = self.get_cursor("ids")
        # Insertion-ordered (dict keys), so the cap below drops the OLDEST ids, not random ones.
        seen_ids: dict[str, None] = dict.fromkeys(json.loads(seen)) if seen else {}
        normalize = _NORMALIZERS.get(self._normalizer, _normalize_generic)

        records: list[dict] = []
        for actor_input, backfill in runs:
            records.extend(self._fetch(actor_input, seen_ids, normalize, backfill))

        out: list[Post] = []
        self.engagement_updates = []
        # Analyse everything the provider returned (its run is already capped at max_fetch):
        # posts skipped here would be lost, as the next scan starts after this one.
        cap = max(self.max_items * self.catchup_factor, self.max_fetch)
        for fields in (f for rec in records for f in _records(normalize, rec)):
            if not self._keeps_place(fields):
                continue
            rid = _rid(fields)
            if rid in seen_ids:
                known = _to_post(self._platform, rid, fields)
                self.engagement_updates.append((known.channel, rid, known.raw_meta.get("engagement") or {}))
                continue
            seen_ids[rid] = None
            post = _to_post(self._platform, rid, fields)
            if self._first_party:
                post.source = f"company:{self.channel}"   # always passes the relevance filter
            elif self._scoped:
                post.source = f"search:{self.channel}"
            out.append(post)
            if len(out) >= cap:
                self.gaps.append(f"more than {cap} new posts in one scan; some may be missing")
                break

        # Capped so the cursor document stays well under DynamoDB's 400 KB item limit.
        self.set_cursor("ids", json.dumps(list(seen_ids)[-1500:]))
        return out

    def _keeps_place(self, fields: dict) -> bool:
        title = str(fields.get("place_title") or "").lower()
        if not title or not (self._place_must or self._place_exclude):
            return True
        return (not self._place_must or any(w in title for w in self._place_must)) and \
            not any(w in title for w in self._place_exclude)

    def _sampled_backfill(self, actor_input: dict) -> list[dict]:
        """A first scan in windows of backfill_sample.every_days from backfill_from to today,
        up to per_window posts each (see __init__)."""
        every = max(1, int(self._sample.get("every_days", 30)))
        per = int(self._sample.get("per_window", 100))
        until_field = self._sample.get("until_field")
        start = datetime.fromisoformat(self.backfill_from or datetime.now(timezone.utc).date().isoformat()).date()
        today = datetime.now(timezone.utc).date()
        out: list[dict] = []
        while start < today:
            end = min(start + timedelta(days=every), today + timedelta(days=1))
            inp = dict(actor_input)
            if self._limit_field:
                inp[self._limit_field] = per
            if self._since_field:
                inp[self._since_field] = start.isoformat()
            if until_field:
                inp[until_field] = end.isoformat()
            items = self._run_once(inp)
            log.info("%s: %s..%s sampled %d", self.channel, start, end, len(items))
            out.extend(items)
            start = end
        return out

    def _fetch(self, actor_input: dict, seen_ids: dict, normalize, backfill: bool = False) -> list[dict]:
        """One actor run, sized for catch-up. If the run comes back full and shares no post
        with earlier scans, older posts may lie beyond it: run again with twice the limit,
        up to max_fetch, and record a gap if it is still not enough. A backfill run (a new
        keyword) asks for up to max_fetch posts since backfill_from."""
        base = actor_input.get(self._limit_field) if self._limit_field else None
        limit = self.scaled(base) if isinstance(base, (int, float)) and base > 0 else None
        if limit and backfill:
            limit = max(limit, self.max_fetch)
        if limit and self._max_limit:
            limit = min(limit, self._max_limit)
        if limit:
            actor_input[self._limit_field] = limit
        start = self.backfill_from if backfill else self.catchup_from
        if self._since_field and start:
            floor = str(actor_input.get(self._since_field) or "")
            actor_input[self._since_field] = max(floor, start)
        # A first load (a new keyword, or a channel's first scan: plan_backfill) is sampled.
        if self._sample and (backfill or self.catchup_factor >= 10 ** 6):
            return self._sampled_backfill(actor_input)
        if backfill:
            return self._run_once(actor_input)
        label = actor_input.get(self._keyword_field)
        per_run = 1                           # the limit applies per keyword / URL in the run
        if isinstance(label, list):
            per_run = max(1, len(label))
            label = ", ".join(str(x.get("url", x) if isinstance(x, dict) else x) for x in label)
        while True:
            try:
                recs = self._run(actor_input)
            except Exception as exc:
                raise ConnectorUnavailable(f"Apify actor run failed: {exc}") from exc
            if not (limit and self.check_overlap and seen_ids and len(recs) >= limit * per_run):
                return recs
            if any(_rid(f) in seen_ids for r in recs for f in _records(normalize, r)):
                return recs
            if limit >= self.max_fetch:
                self.gaps.append(f"{label}: {len(recs)} posts returned, none seen before; "
                                 "older posts may be missing")
                return recs
            limit = min(limit * 2, self.max_fetch, self._max_limit or self.max_fetch)
            actor_input[self._limit_field] = limit
            log.info("%s (%s): full page with no overlap, fetching again with limit %d",
                     self.channel, label, limit)


def _http(method: str, url: str, body: dict | None = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # GETs are safe to repeat, so a slow read is retried; a POST (which starts a billed
    # run) is never re-sent.
    attempts = 3 if method == "GET" else 1
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"HTTP {exc.code} {url.split('?')[0]}: {detail}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt + 1 >= attempts:
                raise
            log.warning("Apify %s %s slow (%s); retrying", method, url.split("?")[0], exc)
            time.sleep(5)


def run_actor(token: str, actor_id: str, actor_input: dict, timeout: int = 300) -> list[dict]:
    """Run one Apify actor and return its dataset items.

    Async pattern: start the run, poll its status, then fetch the dataset. This avoids
    holding a single connection open for the entire (possibly multi-minute) actor run.
    """
    actor_path = actor_id.replace("/", "~")
    start = _http("POST", f"{_BASE}/acts/{actor_path}/runs?token={token}", actor_input)
    run = start.get("data", {}) if isinstance(start, dict) else {}
    run_id = run.get("id")
    dataset_id = run.get("defaultDatasetId")
    if not run_id or not dataset_id:
        raise RuntimeError(f"Apify run did not start cleanly: {start}")

    deadline = time.monotonic() + timeout
    status = run.get("status")
    while status in ("READY", "RUNNING", None) and time.monotonic() < deadline:
        time.sleep(5)
        info = _http("GET", f"{_BASE}/actor-runs/{run_id}?token={token}")
        status = info.get("data", {}).get("status")
    if status != "SUCCEEDED":
        log.warning("Apify actor %s finished with status=%s", actor_id, status)

    items = _http("GET", f"{_BASE}/datasets/{dataset_id}/items?token={token}&clean=true")
    return items if isinstance(items, list) else items.get("items", [])


# --- per-platform normalizers: map raw actor record -> only the fields we use ------------

def _normalize_instagram(r: dict) -> dict:
    if "ownerUsername" in r or "shortCode" in r:
        return _normalize_instagram_search(r)
    caption = (r.get("caption") or "").strip()
    tags = " ".join(f"#{h}" for h in (r.get("hashtags") or []))
    post_url = r.get("post_url") or r.get("url")
    # Reels are videos — flag them and expose a downloadable video url so the pipeline can
    # transcribe the spoken content and score the reel's sentiment, not just the caption.
    ptype = str(r.get("product_type") or r.get("type") or "").lower()
    is_reel = ("clips" in ptype or ptype == "video" or "/reel" in (post_url or ""))
    video_url = r.get("video_url") or r.get("videoUrl") or r.get("videoUrlHd") or r.get("video")
    return {
        "id": post_url or r.get("username"),
        "text": (caption + ("\n" + tags if tags else "")).strip(),
        "url": post_url,
        "author": r.get("username"),
        "author_url": r.get("profile_url"),
        "timestamp": r.get("pub_date") or r.get("scraped_at") or r.get("timestamp"),
        "keyword": r.get("search_keyword"),
        "engagement": {"likes": r.get("like_count"), "comments": r.get("comment_count"), "views": r.get("video_view_count") or r.get("play_count")},
        "is_video": bool(is_reel or video_url),
        "video_url": video_url,
        "media_type": "video" if (is_reel or video_url) else "image",
    }


def _normalize_instagram_search(r: dict) -> dict:
    """apify/instagram-search-scraper (searchType "popular") — posts/reels matching a keyword."""
    caption = (r.get("caption") or "").strip()
    url = r.get("url") or (f"https://www.instagram.com/p/{r['shortCode']}/" if r.get("shortCode") else None)
    ptype = str(r.get("type") or "").lower()
    is_video = ptype == "video" or bool(r.get("videoUrl")) or r.get("productType") == "clips"
    owner = r.get("ownerUsername")
    return {
        "id": url or r.get("id"),
        "text": caption or (r.get("alt") or "").strip(),
        "url": url,
        "author": owner,
        "author_url": f"https://www.instagram.com/{owner}/" if owner else None,
        "timestamp": r.get("timestamp"),
        "keyword": r.get("searchTerm"),
        "engagement": {
            "likes": r.get("likesCount"), "comments": r.get("commentsCount"),
            "views": r.get("videoPlayCount") or r.get("videoViewCount"),
        },
        "is_video": is_video,
        "video_url": r.get("videoUrl"),
        "media_type": "video" if is_video else "image",
    }


def _normalize_facebook_page(r: dict) -> dict:
    """apify/facebook-posts-scraper — a page's own posts (owned content)."""
    user = r.get("user") if isinstance(r.get("user"), dict) else {}
    text = (r.get("text") or "").strip()
    url = r.get("url") or r.get("topLevelUrl")
    if not text and not url:
        return {}
    if r.get("isVideo"):
        media = "video"
    elif r.get("media"):
        media = "image"
    elif r.get("link"):
        media = "link"
    else:
        media = "text"
    return {
        "id": r.get("postId") or url,
        "text": text or url,
        "url": url,
        "author": user.get("name") or r.get("pageName"),
        "author_url": r.get("facebookUrl") or r.get("inputUrl"),
        "timestamp": r.get("time") or r.get("timestamp"),
        "keyword": None,
        "engagement": {
            "likes": r.get("likes"), "comments": r.get("comments"),
            "shares": r.get("shares"), "views": r.get("viewsCount"),
        },
        "is_video": bool(r.get("isVideo")),
        "media_type": media,
    }


def _normalize_tiktok(r: dict) -> dict:
    """clockworks/tiktok-scraper record — video caption, author, engagement, and (when
    requested) an auto-caption subtitle track we use to transcribe the reel's speech."""
    author = r.get("authorMeta") if isinstance(r.get("authorMeta"), dict) else {}
    vmeta = r.get("videoMeta") if isinstance(r.get("videoMeta"), dict) else {}
    caption = (r.get("text") or "").strip()
    hashtags = r.get("hashtags") or []
    tag_str = " ".join(
        f"#{h.get('name') if isinstance(h, dict) else h}" for h in hashtags if h
    )
    # Prefer an English auto-caption subtitle download link when present.
    subs = vmeta.get("subtitleLinks") if isinstance(vmeta.get("subtitleLinks"), list) else []
    sub_url = None
    if subs:
        eng = [s for s in subs if isinstance(s, dict) and str(s.get("language", "")).lower().startswith("eng")]
        pick = (eng or [s for s in subs if isinstance(s, dict)])
        if pick:
            sub_url = pick[0].get("downloadLink") or pick[0].get("link")
    media_urls = r.get("mediaUrls") if isinstance(r.get("mediaUrls"), list) else []
    video_url = (media_urls[0] if media_urls else None) or vmeta.get("downloadAddr") or r.get("videoUrl")
    handle = author.get("name") or author.get("uniqueId")
    return {
        "id": r.get("id") or r.get("webVideoUrl"),
        "text": (caption + ("\n" + tag_str if tag_str else "")).strip() or (r.get("webVideoUrl") or ""),
        "url": r.get("webVideoUrl") or r.get("url"),
        "author": handle or author.get("nickName"),
        "author_url": f"https://www.tiktok.com/@{handle}" if handle else None,
        "timestamp": r.get("createTimeISO") or r.get("createTime"),
        "keyword": r.get("searchQuery") or r.get("search_keyword"),
        "engagement": {
            "likes": r.get("diggCount"), "comments": r.get("commentCount"),
            "views": r.get("playCount"), "shares": r.get("shareCount"),
        },
        "is_video": True,
        "video_url": video_url,
        "subtitle_url": sub_url,
    }


def _normalize_telegram(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "text": (r.get("text") or "").strip(),
        "url": r.get("source_url"),          # t.me/s/<channel> page (keyword mode)
        "author": r.get("source_name"),
        "author_url": r.get("source_url"),
        "timestamp": r.get("date"),
        "keyword": r.get("search_keyword"),
        "engagement": {"views": r.get("view_count")},
    }


def _normalize_quora(r: dict) -> dict:
    # fatihtahta/quora-scraper (no-cookie) record: record_type, url, title, text,
    # author{name,url,credential}, metrics{upvotes,comments,...}, source_context.
    if r.get("record_type"):
        if r.get("record_type") not in ("answer", "question", "post"):
            return {}
        title = (r.get("title") or "").strip()
        body = (r.get("text") or "").strip()
        author = r.get("author") if isinstance(r.get("author"), dict) else {}
        metrics = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
        ctx = r.get("source_context") if isinstance(r.get("source_context"), dict) else {}
        return {
            "id": r.get("url"),
            "text": (title + "\n" + body).strip() if title else body,
            "url": r.get("url"),
            "author": author.get("name"),
            "author_url": author.get("url"),
            "timestamp": r.get("date") or r.get("posted_at") or r.get("created_at"),
            "keyword": ctx.get("seed_value"),
            "engagement": {"upvotes": metrics.get("upvotes"), "comments": metrics.get("comments")},
        }
    # Legacy crawlerbros/quora-scraper record — only answer records carry the text.
    if r.get("type") and r.get("type") != "answer":
        return {}
    title = (r.get("questionTitle") or "").strip()
    body = (r.get("text") or "").strip()
    return {
        "id": r.get("answerId") or r.get("questionUrl"),
        "text": (title + "\n" + body).strip() if title else body,
        "url": r.get("questionUrl") or r.get("url"),
        "author": r.get("authorName"),
        "author_url": r.get("authorUrl"),
        "timestamp": r.get("createdAt"),
        "keyword": None,
        "engagement": {"upvotes": r.get("upvotes")},
    }


def _normalize_linkedin(r: dict) -> dict:
    # harvestapi/linkedin-post-search — full post content, author and engagement (no cookies).
    text = (r.get("commentary") or r.get("content") or r.get("text") or "").strip()
    url = r.get("linkedinUrl") or r.get("url") or r.get("post_url")
    author = r.get("author") if isinstance(r.get("author"), dict) else {}
    posted = r.get("postedAt") if isinstance(r.get("postedAt"), dict) else {}
    eng = r.get("engagement") if isinstance(r.get("engagement"), dict) else {}
    if not text and not url:
        return {}
    return {
        "id": r.get("id") or url,
        "text": text or url,          # fall back to url so the item stays clickable
        "url": url,
        "author": author.get("name") or author.get("publicIdentifier") or r.get("authorName"),
        "author_url": author.get("linkedinUrl") or r.get("authorUrl"),
        "timestamp": posted.get("date") or r.get("postedAt") or r.get("postedDate"),
        "keyword": None,
        "engagement": {
            "likes": eng.get("likes") or eng.get("reactions"),
            "comments": eng.get("comments"),
            "shares": eng.get("shares"),
        },
    }


def _normalize_facebook(r: dict) -> dict:
    """scrapeforge/facebook-search-posts record — public post search (no cookies).
    Fields: post_id, url, message, timestamp (unix), author{name,url}, reactions_count,
    comments_count, reshare_count, video/image attachments."""
    author = r.get("author") if isinstance(r.get("author"), dict) else {}
    text = (r.get("message") or r.get("text") or "").strip()
    url = r.get("url") or r.get("post_url")
    ts = r.get("timestamp") or r.get("creation_time") or r.get("date")
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
        ts = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    video = r.get("video") if isinstance(r.get("video"), dict) else {}
    video_url = video.get("playable_url") or video.get("sd_url") or video.get("hd_url")
    if not text and not url:
        return {}
    if video_url:
        media = "video"
    elif any(r.get(k) for k in ("image", "images", "photo", "photos", "full_picture", "album_preview")):
        media = "image"
    elif r.get("external_url") or r.get("link"):
        media = "link"
    else:
        media = None                      # decided later from the permalink / text
    return {
        "id": r.get("post_id") or r.get("id") or url,
        "text": text or url,
        "url": url,
        "author": author.get("name") or r.get("author_name"),
        "author_url": author.get("url") or r.get("author_url"),
        "timestamp": ts,
        "keyword": r.get("query") or r.get("search_keyword"),
        "engagement": {
            "likes": r.get("reactions_count"),
            "comments": r.get("comments_count"),
            "shares": r.get("reshare_count"),
        },
        "is_video": bool(video_url),
        "video_url": video_url,
        "media_type": media,
    }


def _normalize_generic(r: dict) -> dict:
    text = _first(r, ("text", "content", "caption", "message", "body", "title"))
    url = _first(r, ("url", "post_url", "link", "permalink"))
    return {
        "id": _first(r, ("id", "post_id")) or url,
        "text": (text or "").strip(),
        "url": url,
        "author": _first(r, ("author", "username", "authorName", "ownerUsername")),
        "author_url": _first(r, ("author_url", "profile_url", "authorUrl")),
        "timestamp": _first(r, ("timestamp", "date", "createdAt", "pub_date")),
        "keyword": _first(r, ("search_keyword", "keyword")),
        "engagement": {},
    }


def _normalize_youtube_apidojo(r: dict) -> dict:
    """apidojo/youtube-scraper record — a channel's uploaded videos (title, description,
    views/likes/comments, upload date). Transcribed downstream for sentiment."""
    ch = r.get("channel") if isinstance(r.get("channel"), dict) else {}
    title = (r.get("title") or "").strip()
    desc = (r.get("description") or "").strip()
    return {
        "id": r.get("id") or r.get("url"),
        "text": (title + ("\n" + desc if desc else "")).strip() or title,
        "url": r.get("url"),
        "author": ch.get("name") or ch.get("handle") or "Sympany",
        "author_url": ch.get("url"),
        "timestamp": r.get("uploadDate") or r.get("publishDate"),
        "keyword": None,
        "engagement": {"likes": r.get("likes"), "comments": r.get("comments"), "views": r.get("views")},
        "is_video": True,
    }


def _normalize_youtube_streamers(r: dict) -> dict:
    """streamers/youtube-scraper and streamers/youtube-shorts-scraper record — a channel's
    videos or Shorts (title, description, views/likes/comments, date). Transcribed downstream
    for sentiment."""
    title = (r.get("title") or "").strip()
    desc = (r.get("text") or "").strip()
    subs = r.get("subtitles")
    sub_url = subs if isinstance(subs, str) and subs.startswith("http") else None
    return {
        "id": r.get("id") or r.get("url"),
        "text": (title + ("\n" + desc if desc else "")).strip() or title,
        "url": r.get("url"),
        "author": r.get("channelName") or r.get("channelUsername") or "Sympany",
        "author_url": r.get("channelUrl"),
        "timestamp": _date_or_relative(r.get("date")),
        "keyword": None,
        "engagement": {"likes": r.get("likes"), "comments": r.get("commentsCount"), "views": r.get("viewCount")},
        "is_video": True,
        "subtitle_url": sub_url,
    }


def _normalize_x(r: dict) -> dict:
    """apidojo/tweet-scraper record — a tweet (createdAt like "Tue Nov 24 09:04:02 +0000 2026")."""
    if r.get("isRetweet"):
        return {}
    author = r.get("author") or {}
    try:
        ts = datetime.strptime(str(r.get("createdAt")), "%a %b %d %H:%M:%S %z %Y").isoformat()
    except ValueError:
        ts = r.get("createdAt")
    return {
        "id": r.get("id") or r.get("url"),
        "text": (r.get("fullText") or r.get("text") or "").strip(),
        "url": r.get("url") or r.get("twitterUrl"),
        "author": author.get("userName") or author.get("name"),
        "author_url": author.get("url"),
        "timestamp": ts,
        "keyword": None,
        "engagement": {"likes": r.get("likeCount"), "comments": r.get("replyCount"),
                       "shares": r.get("retweetCount"), "views": r.get("viewCount")},
    }


def _normalize_play_store(r: dict) -> dict:
    """neatrat/google-play-store-reviews-scraper record — one review of the insurer's app."""
    app = r.get("appId") or ""
    return {
        "id": r.get("reviewId"),
        "text": (r.get("body") or "").strip(),
        "url": f"https://play.google.com/store/apps/details?id={app}&reviewId={r.get('reviewId')}" if app else None,
        "author": r.get("reviewer"),
        "timestamp": r.get("timestamp") or r.get("date"),
        "keyword": None,
        "engagement": {"likes": r.get("helpfulCounts")},
        "rating": r.get("rating"),
        "app_version": r.get("appVersion"),
    }


def _normalize_app_store(r: dict) -> dict:
    """thewolves/appstore-reviews-scraper record — one App Store review (title + text)."""
    title, body = (r.get("title") or "").strip(), (r.get("text") or "").strip()
    return {
        "id": r.get("id"),
        "text": f"{title}\n{body}".strip() if title and title not in body else body or title,
        "url": r.get("url"),
        "author": r.get("userName"),
        "author_url": r.get("userUrl"),
        "timestamp": r.get("date"),
        "keyword": None,
        "engagement": {},
        "rating": r.get("score"),
        "app_version": r.get("version"),
    }


def _normalize_google_maps(r: dict) -> list[dict]:
    """compass/crawler-google-places record — one agency with its reviews. Returns one record
    per review; the connector keeps only agencies named for the insurer (place_must_contain)."""
    title = str(r.get("title") or "")
    agency = ", ".join(x for x in (title, r.get("street") or r.get("neighborhood"), r.get("city")) if x)
    out = []
    for rv in r.get("reviews") or []:
        text = (rv.get("text") or rv.get("textTranslated") or "").strip()
        out.append({
            "id": rv.get("reviewId") or rv.get("reviewUrl"),
            # A star-only review has no text: keep it (its rating counts) with a short note.
            "text": f"{text}\n— {agency}" if text else f"{rv.get('stars')}-star review — {agency}",
            "url": rv.get("reviewUrl") or r.get("url"),
            "author": rv.get("name"),
            "author_url": rv.get("reviewerUrl"),
            "timestamp": rv.get("publishedAtDate"),
            "keyword": agency,
            "engagement": {"likes": rv.get("likesCount")},
            "rating": rv.get("stars"),
            "has_text": bool(text),
            "place_title": title,
        })
    return out


_NORMALIZERS = {
    "instagram": _normalize_instagram,
    "telegram": _normalize_telegram,
    "quora": _normalize_quora,
    "linkedin": _normalize_linkedin,
    "tiktok": _normalize_tiktok,
    "facebook": _normalize_facebook,
    "facebook_page": _normalize_facebook_page,
    "youtube_apidojo": _normalize_youtube_apidojo,
    "youtube_streamers": _normalize_youtube_streamers,
    "youtube_channel": _normalize_youtube_streamers,
    "youtube_shorts": _normalize_youtube_streamers,
    "x": _normalize_x,
    "play_store": _normalize_play_store,
    "app_store": _normalize_app_store,
    "google_maps": _normalize_google_maps,
}


def _records(normalize, raw: dict) -> list[dict]:
    """The normalised record(s) of one actor item: most actors give one post per item, the
    Google Maps actor one agency with many reviews."""
    out = normalize(raw)
    return [f for f in (out if isinstance(out, list) else [out]) if f and f.get("text")]


# --- helpers -----------------------------------------------------------------------------

def _to_post(channel: str, rid: str, f: dict) -> Post:
    engagement = {k: v for k, v in (f.get("engagement") or {}).items() if v is not None}
    return Post(
        channel=channel,
        source="Apify",
        message_id=rid,
        author_id=str(f.get("author") or channel),
        timestamp=_parse_ts(f.get("timestamp")),
        text=f["text"],
        url=f.get("url") or None,
        raw_meta={
            "provider": "apify",
            "author_name": f.get("author"),
            "author_url": f.get("author_url"),
            "keyword": f.get("keyword"),
            "engagement": engagement,
            # Video/reel enrichment hints consumed by media_enrich.py.
            "is_video": bool(f.get("is_video")),
            "video_url": f.get("video_url"),
            "subtitle_url": f.get("subtitle_url"),
            "media_type": f.get("media_type") or ("video" if f.get("is_video") else None),
            # App / agency reviews: the star rating (1-5) and the app version reviewed.
            "rating": f.get("rating"),
            "app_version": f.get("app_version"),
        },
    )


def _rid(fields: dict) -> str:
    """The id a normalised record is remembered by (seen-ids cursor)."""
    return str(fields.get("id") or fields.get("url") or fields["text"][:64])


def _first(rec: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = rec.get(k)
        if v:
            return str(v)
    return None


def _maybe_json(val: str):
    val = val.strip()
    if val.startswith("[") or val.startswith("{"):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    return val


_RELATIVE = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
_UNIT_DAYS = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}


def _date_or_relative(value):
    """An ISO date as is; "3 days ago" (some YouTube records) as an ISO date, so the post is
    not stored with today's date."""
    m = _RELATIVE.search(str(value or ""))
    if not m:
        return value
    days = int(m.group(1)) * _UNIT_DAYS[m.group(2).lower()]
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _parse_ts(value) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)
