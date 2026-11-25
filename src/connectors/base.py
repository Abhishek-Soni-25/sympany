"""Connector base class + per-source cursor persistence.

A cursor records the last-seen item id per source so each `poll()` returns only new
content. Cursors are stored as "cursor:<channel>" documents through src/store.py
(DynamoDB on AWS, `data/state/<channel>.json` locally).

`poll()` only moves the cursors in memory; the scan saves them with `commit_cursors()`
once every returned post has been stored, so a scan cut short (deployment, restart,
storage error) fetches the unstored posts again instead of skipping them for good.

Catch-up: scans run when someone clicks Run Scan, so days can pass between two scans.
`commit_cursors()` records when a channel was last scanned completely ("_last_ok"), and
`plan_catchup()` turns the time since then into a catch-up factor: a scan 3 days later asks
the provider for 3 times as many posts (and, where the provider takes a date, for posts
since that day). Connectors that keep seen ids also check for overlap: a full page with
no post seen before means older posts may be beyond it, so they fetch again with a larger
limit. Anything still possibly missing is recorded in `gaps` and reported by the scan.
"""

from __future__ import annotations

import json
import logging
import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from .. import store
from ..models import Post

log = logging.getLogger(__name__)

LAST_OK = "_last_ok"                      # cursor key: when this channel was last scanned completely


def _parse_time(value) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def backfill_start(cfg: dict, now: datetime | None = None) -> str:
    """Start date ("YYYY-MM-DD") of a first scan: collection.backfill_days back from now,
    never before collection.since."""
    now = now or datetime.now(timezone.utc)
    coll = cfg.get("collection", {}) or {}
    start = (now - timedelta(days=int(coll.get("backfill_days", 90)))).date().isoformat()
    floor = str(coll.get("since") or "")[:10]
    return max(start, floor) if floor else start


def catchup_window(cfg: dict, last_ok, now: datetime | None = None) -> tuple[int, str | None, int]:
    """(factor, start date "YYYY-MM-DD" or None, days since `last_ok`) for a scan now. The
    factor is the number of days since the last complete scan (at least 1), capped at
    catchup.max_days; the start date goes catchup.margin_hours further back."""
    cu = cfg.get("catchup", {}) or {}
    now = now or datetime.now(timezone.utc)
    last = _parse_time(last_ok) if last_ok else None
    if last is None:
        return 1, None, 1
    # Whole days, with 6 hours' tolerance (a scan 3 days and 2 hours later counts as 3 days;
    # the overlap check covers the difference).
    days = max(1, math.ceil((now - last).total_seconds() / 86400 - 0.25))
    start = (last - timedelta(hours=float(cu.get("margin_hours", 24)))).date().isoformat()
    return min(days, max(1, int(cu.get("max_days", 14)))), start, days


class ConnectorUnavailable(RuntimeError):
    """Raised when a connector cannot run (missing creds or unsupported channel)."""


class BaseConnector(ABC):
    """Abstract base for all channel connectors."""

    channel: str = "base"

    def __init__(self, sources: list[str], max_items: int = 25,
                 state_key: str | None = None) -> None:
        self.sources = sources or []
        self.max_items = max_items
        # state_key isolates cursor storage so parallel keyword sets (e.g. competitor
        # collection) don't dedupe against each other or against the main scan.
        self._state_doc = f"cursor:{state_key or self.channel}"
        self._cursors: dict[str, str] = self._load_state()
        # (platform, id, engagement) for posts a poll returned again; the scan refreshes
        # their likes / comments / views without analysing them again.
        self.engagement_updates: list[tuple[str, str, dict]] = []
        # Catch-up (see the module docstring); set by plan_catchup() / set_catchup().
        self.catchup_factor = 1               # days of posts to fetch
        self.catchup_from: str | None = None  # "YYYY-MM-DD" for providers that take a start date
        self.check_overlap = True
        self.max_fetch = 400                  # most posts one provider run may return (cost guard)
        self.gaps: list[str] = []             # notes on posts that may be missing
        self.backfill_from: str | None = None  # where a new keyword / account starts ("YYYY-MM-DD")
        self.backfill_new_sources = True      # off for competitor sources (sized by days instead)
        self.window_from: str | None = None    # start of the period this scan covers (for coverage)

    # --- catch-up --------------------------------------------------------------

    def plan_catchup(self, cfg: dict, fallback_last_ok: str | None = None,
                     now: datetime | None = None) -> None:
        """Size this scan by the time since the channel's last complete scan (or, before
        the first one, since `fallback_last_ok`)."""
        last = self._cursors.get(LAST_OK) or fallback_last_ok
        factor, start, days = catchup_window(cfg, last, now)
        self.set_catchup(factor, start, max_fetch=int((cfg.get("catchup") or {}).get("max_fetch", 400)))
        self.backfill_from = backfill_start(cfg, now)
        self.window_from = start or self.backfill_from
        if days > factor:
            self.gaps.append(f"last complete scan was {days} days ago; only {factor} days' "
                             "worth of posts were fetched")

    def plan_backfill(self, cfg: dict, now: datetime | None = None) -> None:
        """First scan of a channel: fetch the last collection.backfill_days (3 months), up to
        catchup.max_fetch posts per run, instead of only the days since the last scan run."""
        start = backfill_start(cfg, now)
        self.set_catchup(10 ** 6, start, max_fetch=int((cfg.get("catchup") or {}).get("max_fetch", 400)),
                         check_overlap=False)
        self.backfill_from = self.window_from = start

    def set_catchup(self, factor: int, start_date: str | None = None, *, max_fetch: int = 400,
                    check_overlap: bool = True) -> None:
        self.catchup_factor = max(1, int(factor))
        self.catchup_from = start_date
        self.max_fetch = max(1, int(max_fetch))
        self.check_overlap = check_overlap
        self.gaps = []

    def scaled(self, base: int) -> int:
        """`base` (a per-run limit) scaled by the catch-up factor, within max_fetch — never
        below the configured base."""
        return max(int(base), min(int(base) * self.catchup_factor, self.max_fetch))

    # --- cursor helpers ------------------------------------------------------

    def _load_state(self) -> dict[str, str]:
        data = store.get_doc(self._state_doc, {})
        return data if isinstance(data, dict) else {}

    def _save_state(self) -> None:
        try:
            store.put_doc(self._state_doc, self._cursors)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not persist cursor state %s: %s", self._state_doc, exc)

    def new_sources(self) -> set[str]:
        """Keywords / accounts added since the last complete scan: their first scan looks back
        over the backfill window (backfill_from). Records the current list for the next scan
        (saved with the other cursors). Before the list was first recorded, the sources of a
        channel already scanned count as known."""
        if not self.backfill_new_sources:
            return set()
        raw = self._cursors.get("sources")
        try:
            known = set(json.loads(raw)) if raw else (set(self.sources) if self._cursors.get(LAST_OK) else set())
        except (TypeError, ValueError):
            known = set(self.sources)
        self.set_cursor("sources", json.dumps(sorted(known | set(self.sources))))
        return {s for s in self.sources if s not in known}

    def get_cursor(self, source: str) -> str | None:
        return self._cursors.get(source)

    def set_cursor(self, source: str, value: str) -> None:
        """Move a cursor in memory; `commit_cursors()` saves it."""
        self._cursors[source] = value

    def commit_cursors(self) -> None:
        """Save the cursors — call once the posts of the last `poll()` are stored. Also
        records the time, which sizes the catch-up of the next scan."""
        self._cursors[LAST_OK] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    def discard_cursors(self) -> None:
        """Forget cursor moves since the last commit, so the next `poll()` returns those
        posts again."""
        self._cursors = self._load_state()

    # --- lifecycle -----------------------------------------------------------

    def setup(self) -> None:
        """Optional one-time init (auth/clients). Override as needed."""

    @abstractmethod
    def poll(self) -> list[Post]:
        """Return new `Post` objects across all configured sources."""

    def close(self) -> None:
        """Optional cleanup. Override as needed."""
