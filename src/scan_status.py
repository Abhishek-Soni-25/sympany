"""Shared scan status (a "scan_status" document in the store).

The web tasks and the scan task are separate containers, so "is a scan running, and how
did the last one go" lives in the data store rather than in process memory. A status
left "running" by a task that died is treated as stale after STALE_AFTER seconds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import store

_DOC = "scan_status"
STALE_AFTER = 3 * 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get() -> dict[str, Any]:
    st = store.get_doc(_DOC, {}) or {}
    st.setdefault("running", False)
    st.setdefault("last_run", None)
    st.setdefault("last_stats", None)
    st.setdefault("error", None)
    if st["running"] and st.get("started_at"):
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(st["started_at"])).total_seconds()
            if age > STALE_AFTER:
                st["running"] = False
                st["error"] = st.get("error") or "previous scan did not report completion"
        except ValueError:
            pass
    return st


def start(job: str, launched_by: str = "", task_arn: str | None = None) -> None:
    st = get()
    st.update(running=True, job=job, started_at=_now(), launched_by=launched_by, error=None)
    if task_arn:
        st["task_arn"] = task_arn
    store.put_doc(_DOC, st)


def finish(stats: dict | None = None, error: str | None = None) -> None:
    st = get()
    st.update(running=False, last_run=_now(), error=error)
    if stats is not None:
        st["last_stats"] = stats
    store.put_doc(_DOC, st)
