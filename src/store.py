"""Persistence layer — Amazon DynamoDB on AWS, local JSON files for development.

On AWS two web tasks and the scheduled scan task share one data store, so nothing may be
kept on a task's local disk. Every module persists through this interface instead:

    records   put_record / put_records / list_records   (mentions, competitor posts, cases)
    documents get_doc / put_doc                        (small JSON blobs: follower
                                                        snapshots, rule set, scan status,
                                                        connector cursors, ...)
    audit     append_audit / list_audit                 (append-only compliance register)
    locks     try_lock / release_lock                   (one scan at a time across web tasks)

DynamoDB layout (backend "dynamodb"):

  data table  (storage.table, PK pk / SK sk, TTL attribute expires_at)
      pk = record kind ("mention", "competitor_post", "case") or "doc"
      sk = record key, or the document name
      data = the record as a JSON string (avoids DynamoDB number/Decimal conversion)
      expires_at = epoch seconds — DynamoDB TTL deletes collected posts and cases after
                   storage.post_retention_days, with no write charge
      pk = "lock" items are short-lived locks (conditional writes), see try_lock
  audit table (storage.audit_table, PK pk / SK sk, no TTL — kept throughout, PITR on)
      pk = "compliance_audit" | "compliance_notification", sk = "<ISO time>#<uuid>"

Local layout (backend "local") keeps the original files under data/, so existing local
data keeps working unchanged.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CASES_DIR, DATA_DIR, STATE_DIR, aws_region, load_config, storage_backend

log = logging.getLogger(__name__)

# Record kinds that carry a TTL (collected social content). Audit data never expires.
EXPIRING_KINDS = {"mention", "competitor_post", "case"}

_cfg: dict | None = None
_lock = threading.Lock()
_local_locks: dict[str, tuple[str, float]] = {}


def configure(cfg: dict) -> None:
    """Use an already-loaded config (otherwise it is loaded on first use)."""
    global _cfg, _backend
    _cfg, _backend = cfg, None


def _config() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


# ---------------------------------------------------------------------------------------
# Local files backend
# ---------------------------------------------------------------------------------------

_LOCAL_RECORD_FILES = {"mention": "mentions.jsonl", "competitor_post": "competitor_mentions.jsonl"}
_LOCAL_DOC_FILES = {
    "competitors_sov": DATA_DIR / "competitors.json",
    "followers": DATA_DIR / "followers.json",
    "response_times": DATA_DIR / "response_times.json",
    "keywords": DATA_DIR / "keywords.json",
    "ruleset_active": DATA_DIR / "compliance" / "ruleset-active.json",
}
_LOCAL_AUDIT_FILES = {
    "compliance_audit": DATA_DIR / "compliance" / "audit.jsonl",
    "compliance_notification": DATA_DIR / "compliance" / "notifications.jsonl",
}


class _LocalBackend:
    def _doc_path(self, name: str) -> Path:
        if name in _LOCAL_DOC_FILES:
            return _LOCAL_DOC_FILES[name]
        safe = name.replace(":", "_").replace("/", "_")
        return STATE_DIR / f"{safe}.json"

    def put_records(self, kind: str, items: list[tuple[str, dict]]) -> None:
        if kind == "case":
            CASES_DIR.mkdir(parents=True, exist_ok=True)
            for key, rec in items:
                (CASES_DIR / f"{key}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
            return
        path = DATA_DIR / _LOCAL_RECORD_FILES[kind]
        with _lock, path.open("a", encoding="utf-8") as fh:
            for _key, rec in items:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def list_records(self, kind: str, key_of) -> list[dict]:
        if kind == "case":
            out = []
            for f in CASES_DIR.glob("CASE-*.json"):
                try:
                    out.append(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
            return out
        path = DATA_DIR / _LOCAL_RECORD_FILES[kind]
        if not path.exists():
            return []
        by_key: dict[str, dict] = {}                 # append-only file: last write wins
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_key[key_of(rec)] = rec
        return list(by_key.values())

    def get_doc(self, name: str) -> Any:
        path = self._doc_path(name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put_doc(self, name: str, value: Any) -> None:
        path = self._doc_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_audit(self, kind: str, record: dict) -> None:
        path = _LOCAL_AUDIT_FILES[kind]
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def try_lock(self, name: str, owner: str, ttl: float) -> bool:
        now = time.time()
        with _lock:
            held = _local_locks.get(name)
            if held and held[1] > now and held[0] != owner:
                return False
            _local_locks[name] = (owner, now + ttl)
            return True

    def release_lock(self, name: str, owner: str) -> None:
        with _lock:
            if _local_locks.get(name, ("",))[0] == owner:
                _local_locks.pop(name, None)

    def list_audit(self, kind: str) -> list[dict]:
        path = _LOCAL_AUDIT_FILES[kind]
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


# ---------------------------------------------------------------------------------------
# DynamoDB backend
# ---------------------------------------------------------------------------------------

class _DynamoBackend:
    def __init__(self, cfg: dict) -> None:
        import boto3
        from botocore.config import Config

        st = cfg.get("storage", {})
        res = boto3.resource("dynamodb", region_name=aws_region(cfg),
                             config=Config(retries={"max_attempts": 8, "mode": "adaptive"}))
        self._data = res.Table(st.get("table", "sympany-socmon-data"))
        self._audit = res.Table(st.get("audit_table", "sympany-socmon-audit"))
        self._ttl_days = int(st.get("post_retention_days", 730) or 0)

    def _query_all(self, table, pk: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        items: list[dict] = []
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk)}
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                return items
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def put_records(self, kind: str, items: list[tuple[str, dict]]) -> None:
        now = int(time.time())
        with self._data.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as batch:
            for key, rec in items:
                item = {"pk": kind, "sk": key, "data": json.dumps(rec, ensure_ascii=False), "updated_at": now}
                if kind in EXPIRING_KINDS and self._ttl_days > 0:
                    item["expires_at"] = now + self._ttl_days * 86400
                batch.put_item(Item=item)

    def list_records(self, kind: str, key_of) -> list[dict]:
        out = []
        now = int(time.time())
        for it in self._query_all(self._data, kind):
            # TTL deletion runs in the background; skip items already past their expiry.
            if it.get("expires_at") and int(it["expires_at"]) < now:
                continue
            try:
                out.append(json.loads(it["data"]))
            except (KeyError, json.JSONDecodeError):
                continue
        return out

    def get_doc(self, name: str) -> Any:
        resp = self._data.get_item(Key={"pk": "doc", "sk": name}, ConsistentRead=True)
        item = resp.get("Item")
        return json.loads(item["data"]) if item else None

    def put_doc(self, name: str, value: Any) -> None:
        self._data.put_item(Item={"pk": "doc", "sk": name, "data": json.dumps(value, ensure_ascii=False),
                                  "updated_at": int(time.time())})

    def append_audit(self, kind: str, record: dict) -> None:
        at = record.get("at") or datetime.now(timezone.utc).isoformat()
        self._audit.put_item(Item={"pk": kind, "sk": f"{at}#{uuid.uuid4().hex[:12]}",
                                   "data": json.dumps(record, ensure_ascii=False)})

    def try_lock(self, name: str, owner: str, ttl: float) -> bool:
        """Atomic: take the lock unless another owner holds an unexpired one."""
        from botocore.exceptions import ClientError

        now = int(time.time())
        try:
            self._data.put_item(
                Item={"pk": "lock", "sk": name, "lock_owner": owner, "expires_at": now + int(ttl)},
                ConditionExpression="attribute_not_exists(pk) OR expires_at < :now OR lock_owner = :me",
                ExpressionAttributeValues={":now": now, ":me": owner},
            )
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def release_lock(self, name: str, owner: str) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self._data.delete_item(Key={"pk": "lock", "sk": name}, ConditionExpression="lock_owner = :me",
                                   ExpressionAttributeValues={":me": owner})
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                log.warning("Could not release lock %s: %s", name, exc)
        except BotoCoreError as exc:                    # network / timeout after botocore's retries
            log.warning("Could not release lock %s: %s", name, exc)

    def list_audit(self, kind: str) -> list[dict]:
        out = []
        for it in self._query_all(self._audit, kind):           # sorted by sk (time)
            try:
                out.append(json.loads(it["data"]))
            except (KeyError, json.JSONDecodeError):
                continue
        return out


_backend: _LocalBackend | _DynamoBackend | None = None


def _get() -> _LocalBackend | _DynamoBackend:
    global _backend
    if _backend is None:
        cfg = _config()
        _backend = _DynamoBackend(cfg) if storage_backend(cfg) == "dynamodb" else _LocalBackend()
        log.info("Storage backend: %s", type(_backend).__name__)
    return _backend


def is_local() -> bool:
    return isinstance(_get(), _LocalBackend)


# ---------------------------------------------------------------------------------------
# Public API (with a short read cache so dashboard loads don't re-query every request)
# ---------------------------------------------------------------------------------------

_CACHE_SECONDS = 20
_cache: dict[str, tuple[float, list[dict]]] = {}


def put_record(kind: str, key: str, record: dict) -> None:
    put_records(kind, [(key, record)])


def put_records(kind: str, items: list[tuple[str, dict]]) -> None:
    if not items:
        return
    _get().put_records(kind, items)
    _cache.pop(kind, None)


def list_records(kind: str, key_of) -> list[dict]:
    """All records of a kind, de-duplicated by ``key_of(record)`` (latest write wins)."""
    hit = _cache.get(kind)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return list(hit[1])
    recs = _get().list_records(kind, key_of)
    _cache[kind] = (time.monotonic(), recs)
    return list(recs)


def get_doc(name: str, default: Any = None) -> Any:
    try:
        val = _get().get_doc(name)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read document %s: %s", name, exc)
        val = None
    return default if val is None else val


def put_doc(name: str, value: Any) -> None:
    _get().put_doc(name, value)


def append_audit(kind: str, record: dict) -> None:
    _get().append_audit(kind, record)


def list_audit(kind: str) -> list[dict]:
    return _get().list_audit(kind)


def try_lock(name: str, owner: str, ttl_seconds: float) -> bool:
    """Take a named lock for `owner` (shared by every web task on AWS). False if it is held
    by another owner and not yet expired. Expired locks are taken over."""
    return _get().try_lock(name, owner, ttl_seconds)


def release_lock(name: str, owner: str) -> None:
    _get().release_lock(name, owner)
