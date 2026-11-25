"""Bright Data Web Scraper connector — keyword discovery for YouTube, Reddit and the wider web.

Bright Data's Web Scraper API is an *asynchronous job* model:

    1. POST /datasets/v3/trigger?dataset_id=<id>   with a JSON array of inputs
       -> {"snapshot_id": "..."}
    2. GET  /datasets/v3/progress/<snapshot_id>     until {"status": "ready"}
    3. GET  /datasets/v3/snapshot/<snapshot_id>?format=json  -> list of records

Each platform/object pairing maps to a Bright Data ``dataset_id`` (see config.yaml ->
brightdata.datasets and docs/data-providers.md). A single keyword is the primary input.

Records are de-duplicated across scans by their platform id (falling back to URL) using the
connector cursor store, so each ``poll()`` only returns content unseen in previous cycles.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from ..config import env
from ..models import Post
from .base import BaseConnector, ConnectorUnavailable

log = logging.getLogger(__name__)

_BASE = "https://api.brightdata.com/datasets/v3"


class BrightDataConnector(BaseConnector):
    """Generic Bright Data Web Scraper connector, parameterised per channel.

    Config (config.yaml -> channels.<name>):
        mode: brightdata
        dataset: youtube_videos        # key into brightdata.datasets
        keywords: ["Sympany", ...]     # optional; falls back to target aliases
        extra_input: {country: "CH", num_of_posts: 10}   # merged into each trigger record
    """

    def __init__(
        self,
        channel: str,
        dataset_id: str,
        keywords: list[str],
        keyword_field: str = "keyword",
        extra_input: dict[str, Any] | None = None,
        discover_by: str = "keyword",
        max_items: int = 25,
        poll_timeout: int = 180,
        state_key: str | None = None,
    ) -> None:
        self.channel = channel  # set before base builds its state path
        super().__init__(sources=keywords, max_items=max_items, state_key=state_key)
        self._dataset_id = dataset_id
        self._keyword_field = keyword_field
        self._extra_input = extra_input or {}
        self._discover_by = discover_by
        self._poll_timeout = poll_timeout
        self._token: str | None = None

    def setup(self) -> None:
        self._token = env("BRIGHTDATA_API_KEY")
        if not self._token:
            raise ConnectorUnavailable(
                "Bright Data API key missing or PLACEHOLDER (BRIGHTDATA_API_KEY, Parameter Store /sympany-socmon/BRIGHTDATA_API_KEY)."
            )
        if not self._dataset_id:
            raise ConnectorUnavailable(
                f"No dataset_id configured for Bright Data channel '{self.channel}'."
            )
        if not self.sources:
            raise ConnectorUnavailable(
                f"No keywords configured for Bright Data channel '{self.channel}'."
            )

    # --- HTTP helpers --------------------------------------------------------

    def _request(self, method: str, url: str, body: Any | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # surface Bright Data's error body for debugging
            detail = exc.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"HTTP {exc.code} {url.split('?')[0]}: {detail}") from exc

    def _trigger(self, inputs: list[dict]) -> str:
        # Keyword-discovery datasets require the discover phase to be requested explicitly.
        url = (
            f"{_BASE}/trigger?dataset_id={self._dataset_id}"
            f"&type=discover_new&discover_by={self._discover_by}&include_errors=true"
        )
        out = self._request("POST", url, inputs)
        snap = out.get("snapshot_id") if isinstance(out, dict) else None
        if not snap:
            raise RuntimeError(f"Bright Data trigger returned no snapshot_id: {out}")
        return snap

    def _wait(self, snapshot_id: str) -> None:
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            prog = self._request("GET", f"{_BASE}/progress/{snapshot_id}")
            status = (prog.get("status") if isinstance(prog, dict) else "") or ""
            if status == "ready":
                return
            if status in ("failed", "error"):
                raise RuntimeError(f"Bright Data snapshot {snapshot_id} failed: {prog}")
            time.sleep(5)
        raise TimeoutError(
            f"Bright Data snapshot {snapshot_id} not ready within {self._poll_timeout}s"
        )

    def _fetch(self, snapshot_id: str) -> list[dict]:
        out = self._request("GET", f"{_BASE}/snapshot/{snapshot_id}?format=json")
        if isinstance(out, list):
            return out
        if isinstance(out, dict):
            return out.get("data") or out.get("results") or []
        return []

    # --- lifecycle -----------------------------------------------------------

    def poll(self) -> list[Post]:
        seen = self.get_cursor("ids")
        # Insertion-ordered (dict keys), so the cap below drops the OLDEST ids, not random ones.
        seen_ids: dict[str, None] = dict.fromkeys(json.loads(seen)) if seen else {}

        # Cap the number of records requested where the dataset supports it, scaled for
        # catch-up (see connectors/base.py).
        limit = self.scaled(int(self._extra_input.get("num_of_posts", self.max_items)))
        # Keywords added since the last scan ask for as many results as one run allows.
        new = self.new_sources()
        while True:
            inputs = [{self._keyword_field: kw, **self._extra_input,
                       "num_of_posts": max(limit, self.max_fetch) if kw in new else limit}
                      for kw in self.sources]
            try:
                snapshot_id = self._trigger(inputs)
                self._wait(snapshot_id)
                records = self._fetch(snapshot_id)
            except Exception as exc:
                raise ConnectorUnavailable(f"Bright Data run failed: {exc}") from exc
            # A full result with no post seen before: older posts may lie beyond it.
            if not (self.check_overlap and seen_ids and len(records) >= limit * max(1, len(self.sources))):
                break
            if any(p and p.message_id in seen_ids for p in map(self._to_post, records)):
                break
            if limit >= self.max_fetch:
                self.gaps.append(f"{len(records)} results returned, none seen before; "
                                 "older posts may be missing")
                break
            limit = min(limit * 2, self.max_fetch)
            log.info("%s: full result with no overlap, fetching again with %d per keyword",
                     self.channel, limit)

        out: list[Post] = []
        self.engagement_updates = []
        # Analyse everything the provider returned (its run is already capped at max_fetch):
        # posts skipped here would be lost, as the next scan starts after this one.
        cap = max(self.max_items * self.catchup_factor, self.max_fetch)
        for rec in records:
            post = self._to_post(rec)
            if post is None:
                continue
            if post.message_id in seen_ids:
                self.engagement_updates.append(
                    (post.channel, post.message_id, (post.raw_meta or {}).get("engagement") or {}))
                continue
            seen_ids[post.message_id] = None
            out.append(post)
            if len(out) >= cap:
                self.gaps.append(f"more than {cap} new posts in one scan; some may be missing")
                break

        # Persist a bounded set of seen ids to keep the cursor file small.
        self.set_cursor("ids", json.dumps(list(seen_ids)[-2000:]))
        return out

    def _to_post(self, rec: dict) -> Post | None:
        title = _first(rec, ("title", "post_text", "header"))
        body = _first(rec, ("description", "text", "comment", "snippet", "post_text"))
        text = "\n".join(p for p in (title, body) if p and (not title or p != title)).strip()
        text = (text or title or body or "").strip()
        if not text:
            return None
        url = _first(rec, ("url", "link", "post_url", "video_url", "permalink"))
        rid = _first(rec, ("id", "post_id", "video_id", "comment_id")) or url or text[:64]
        ts = _parse_ts(_first(rec, ("date_posted", "created_time", "timestamp", "date")))
        author = _first(rec, ("user_posted", "youtuber", "channel_name", "author", "username"))
        author_url = _first(rec, ("user_url", "channel_url", "profile_url", "author_url"))
        engagement = {
            "likes": rec.get("likes") or rec.get("num_likes") or rec.get("num_upvotes"),
            "comments": rec.get("num_comments") or rec.get("replies"),
            "views": rec.get("views") or rec.get("view_count"),
        }
        engagement = {k: v for k, v in engagement.items() if v is not None}
        return Post(
            channel=self.channel,
            source="Bright Data",
            message_id=str(rid),
            author_id=str(author or self.channel),
            timestamp=ts,
            text=text,
            url=url or None,
            raw_meta={
                "provider": "brightdata",
                "dataset_id": self._dataset_id,
                "author_name": author,
                "author_url": author_url,
                "keyword": _first(rec, ("keyword", "search_keyword")),
                "engagement": engagement,
            },
        )


def _first(rec: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = rec.get(k)
        if v:
            return str(v)
    return None


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)
