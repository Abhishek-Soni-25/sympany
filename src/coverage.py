"""Collection coverage: periods in which a channel may have missed posts.

A scan records a note here when a channel could not reach back to its last complete scan
(a provider returned a full page of only new posts even at the largest run size, more new
posts than one scan may take, or the gap since the last scan was longer than
catchup.max_days). Each note keeps the period the scan covered, so a report for a date
range can say whether any channel may be incomplete in that range.

A channel that failed to run at all is not recorded: its cursor did not move, so the next
scan fetches the same days again.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import store

log = logging.getLogger(__name__)

_DOC = "coverage"
_KEEP = 500                                 # notes kept (oldest dropped); keeps the document small


def load() -> list[dict[str, Any]]:
    data = store.get_doc(_DOC, {})
    notes = data.get("notes") if isinstance(data, dict) else None
    return notes if isinstance(notes, list) else []


def record(channel: str, window_from: str | None, notes: list[str], now: datetime | None = None) -> None:
    """Store the possible gaps of one channel's scan: the period it covered (window_from to
    now) and what may be missing."""
    if not notes:
        return
    now = now or datetime.now(timezone.utc)
    entries = [{"channel": channel, "from": window_from, "to": now.isoformat(), "at": now.isoformat(), "note": n}
               for n in notes]
    try:
        store.put_doc(_DOC, {"notes": (load() + entries)[-_KEEP:]})
    except Exception as exc:  # noqa: BLE001 — coverage notes must never fail a scan
        log.warning("Could not store coverage notes for %s: %s", channel, exc)
