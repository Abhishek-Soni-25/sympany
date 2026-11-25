"""One-time migration: copy the local knowledge base under data/ into DynamoDB.

The image ships the data collected so far (data/*.json, data/*.jsonl, data/cases/,
data/compliance/). Run this once after the tables exist so the dashboard starts with that
history instead of empty — e.g. as a one-off ECS task using the scan task definition with
the command overridden to:

    python -m tools.seed_dynamodb            # copy what is missing (safe to re-run)
    python -m tools.seed_dynamodb --dry-run  # only count what would be copied

Only what DynamoDB does not have yet is written: records and documents that already exist
(e.g. updated by a scan or a user since) are never overwritten. Audit and notification
records are appended only when the audit table is still empty.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import store  # noqa: E402
from src.config import load_config  # noqa: E402
from src.mentions import key_of as mention_key  # noqa: E402

log = logging.getLogger("seed")

_DOCS = ["competitors_sov", "followers", "response_times", "keywords", "ruleset_active"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = load_config()
    if cfg.get("storage", {}).get("backend") != "dynamodb":
        log.error("STORAGE_BACKEND is not 'dynamodb' — nothing to seed into.")
        return 2
    local = store._LocalBackend()
    dynamo = store._DynamoBackend(cfg)

    def post_key(r: dict) -> str:
        return f"{r.get('brand')}::{r.get('platform')}::{r.get('id')}"

    key_fns = {
        "mention": mention_key,
        "competitor_post": post_key,
        "case": lambda c: c.get("case_id", ""),
    }
    batches = {kind: [(fn(r), r) for r in local.list_records(kind, fn)] for kind, fn in key_fns.items()}
    docs = {name: local.get_doc(name) for name in _DOCS}
    docs = {k: v for k, v in docs.items() if v is not None}
    audits = {kind: local.list_audit(kind) for kind in ("compliance_audit", "compliance_notification")}

    for kind, items in batches.items():
        log.info("%s: %d record(s)", kind, len(items))
    log.info("documents: %s", ", ".join(docs) or "none")
    for kind, recs in audits.items():
        log.info("%s: %d record(s)", kind, len(recs))
    if args.dry_run:
        return 0

    for kind, items in batches.items():
        have = {key_fns[kind](r) for r in dynamo.list_records(kind, key_fns[kind])}
        new = [(k, r) for k, r in items if k and k not in have]
        log.info("%s: %d new, %d already present — kept as they are", kind, len(new), len(items) - len(new))
        if new:
            dynamo.put_records(kind, new)
    for name, value in docs.items():
        if dynamo.get_doc(name) is not None:
            log.info("document %s already present — kept as it is", name)
            continue
        dynamo.put_doc(name, value)
    for kind, recs in audits.items():
        if dynamo.list_audit(kind):
            log.info("%s already has records — skipped", kind)
            continue
        for r in recs:
            dynamo.append_audit(kind, r)
    log.info("Seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
