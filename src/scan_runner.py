"""Scans run inside the web app (scan.launch: inline).

On AWS a scan can also run as its own ECS task (scan.launch: ecs), but that needs
ecs:RunTask + iam:PassRole for the web task and an EventBridge Scheduler role. In inline mode
the web tasks do it themselves:

  * "Run Scan" (POST /api/scan) starts the scan in a background thread of the web task that
    received the click. scan.manual_per_day limits how many Run Scan clicks may finish
    successfully per Swiss calendar day, for everyone together (a failed scan does not count).
  * The daily scan (scan.daily_at, off on AWS): every web task checks every 5 minutes whether
    today's scan is due and has not run yet; the first one to take the lock runs it.

Only one scan runs at a time across all web tasks: the "scan" lock is an atomic conditional
write in DynamoDB (store.try_lock). A lock left by a task that died expires after
scan_status.STALE_AFTER, so the next check takes over. A daily scan that was cut off (e.g.
the task was replaced by a deployment) is started again once its lock has expired; a daily
scan that finished — successfully or with an error — is not repeated that day.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from . import scan_status, store

log = logging.getLogger(__name__)

LOCK = "scan"
_DAILY_DOC = "daily_scan"
_MANUAL_DOC = "manual_scans"                        # {"date", "count", "last_ok_at", "last_by"}
LOCAL_TZ = ZoneInfo("Europe/Zurich")                # Swiss time (CET / CEST)
CHECK_EVERY = 300                                   # seconds between daily-scan checks
_started = False


def _owner() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def _run_locked(job: str, cfg: dict, launched_by: str, owner: str, on_done=None) -> None:
    """Run the scan in a background thread; the caller already holds the lock."""
    from . import scan_job

    def work() -> None:
        rc = 1
        try:
            rc = scan_job.execute(job, cfg, launched_by=launched_by)
        except Exception:  # noqa: BLE001 — execute() already records failures
            log.exception("scan thread crashed")
        finally:
            if on_done is not None:
                try:
                    on_done(rc)
                except Exception:  # noqa: BLE001
                    log.exception("could not record the scan result")
            store.release_lock(LOCK, owner)

    threading.Thread(target=work, daemon=True, name=f"scan-{job}").start()


def _manual(today: str) -> dict:
    doc = store.get_doc(_MANUAL_DOC, {}) or {}
    return doc if doc.get("date") == today else {"date": today, "count": 0}


def quota(cfg: dict, now: datetime | None = None) -> dict:
    """Today's Run Scan allowance (scan.manual_per_day; 0 = no limit), Swiss calendar day.
    Only scans that finished successfully count."""
    limit = int(cfg.get("scan", {}).get("manual_per_day", 0) or 0)
    doc = _manual((now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ).date().isoformat())
    used = int(doc.get("count", 0))
    return {"limit": limit, "used": used, "available": limit <= 0 or used < limit,
            "last_ok_at": doc.get("last_ok_at"), "last_by": doc.get("last_by")}


def launch(job: str, cfg: dict, launched_by: str, now: datetime | None = None) -> tuple[bool, str | None]:
    """Start a scan now unless one is already running anywhere or today's Run Scan allowance
    is used up. Returns (started, reason when not started)."""
    owner = _owner()
    if not store.try_lock(LOCK, owner, scan_status.STALE_AFTER):
        return False, "a scan is already running"
    try:
        q = quota(cfg, now)                             # checked under the lock: no race
        if not q["available"]:
            store.release_lock(LOCK, owner)
            return False, "today's scan has already been run; the next one can be run tomorrow"
        today = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ).date().isoformat()

        def done(rc: int) -> None:
            if rc != 0:
                return                                  # a failed scan does not use up the day
            doc = _manual(today)
            store.put_doc(_MANUAL_DOC, {"date": today, "count": int(doc.get("count", 0)) + 1,
                                        "last_ok_at": datetime.now(LOCAL_TZ).isoformat(), "last_by": launched_by})

        _run_locked(job, cfg, launched_by, owner, on_done=done)
    except Exception:
        store.release_lock(LOCK, owner)
        raise
    return True, None


def _daily_time(cfg: dict) -> tuple[int, int] | None:
    raw = str(cfg.get("scan", {}).get("daily_at", "") or "").strip()
    if not raw:
        return None
    try:
        hh, mm = (int(x) for x in raw.split(":"))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except ValueError:
        pass
    log.warning("scan.daily_at %r is not HH:MM — daily scan disabled", raw)
    return None


def daily_tick(cfg: dict, now: datetime | None = None) -> bool:
    """Start today's scheduled scan if it is due and has not run yet. True if started."""
    at = _daily_time(cfg)
    if at is None:
        return False
    now = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    if (now.hour, now.minute) < at:
        return False
    today = now.date().isoformat()

    def finished_today() -> bool:
        doc = store.get_doc(_DAILY_DOC, {}) or {}
        return doc.get("date") == today and bool(doc.get("finished_at"))

    if finished_today():
        return False
    owner = _owner()
    if not store.try_lock(LOCK, owner, scan_status.STALE_AFTER):
        return False                                    # a scan is running; check again later
    try:
        if finished_today():
            store.release_lock(LOCK, owner)             # another task finished it meanwhile
            return False
        doc = store.get_doc(_DAILY_DOC, {}) or {}
        attempt = int(doc.get("attempt", 0)) + 1 if doc.get("date") == today else 1
        store.put_doc(_DAILY_DOC, {"date": today, "started_at": now.isoformat(), "attempt": attempt})
        log.info("Starting the daily scan for %s (attempt %d)", today, attempt)

        def done(rc: int) -> None:
            store.put_doc(_DAILY_DOC, {"date": today, "started_at": now.isoformat(), "attempt": attempt,
                                       "finished_at": datetime.now(LOCAL_TZ).isoformat(), "ok": rc == 0})

        _run_locked("all", cfg, "daily schedule", owner, on_done=done)
    except Exception:
        store.release_lock(LOCK, owner)                 # don't block scans until the lock expires
        raise
    return True


def start_daily(cfg: dict) -> None:
    """Start the background thread that runs the daily scan (once per process)."""
    global _started
    if _started or _daily_time(cfg) is None:
        return
    _started = True

    def loop() -> None:
        time.sleep(30)                                  # let the app finish starting
        while True:
            try:
                daily_tick(cfg)
            except Exception:  # noqa: BLE001 — never let the checker thread die
                log.exception("daily scan check failed")
            time.sleep(CHECK_EVERY)

    threading.Thread(target=loop, daemon=True, name="daily-scan").start()
    log.info("Daily scan enabled at %s Swiss time", cfg.get("scan", {}).get("daily_at"))
