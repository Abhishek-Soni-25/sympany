"""Backfill language / author_type / media_type / is_official on stored mentions.

Mentions recorded before these fields existed lack them, which leaves the Listening and
Competition panels short. This re-reads the stored mentions and competitor posts (DynamoDB
on AWS, data/*.jsonl locally), asks the text model (Bedrock / Groq) for the language +
author type of each post in small batches (no scraping, no provider cost), derives
media_type / is_official locally, and writes the records back.

    python -m tools.backfill_mention_meta            # only records missing a field
    python -m tools.backfill_mention_meta --all      # re-derive every record
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config  # noqa: E402
from src import competitors, mentions, post_meta, store  # noqa: E402
from src.pipeline.risk_classifier import RiskClassifier, make_classifier  # noqa: E402

log = logging.getLogger("backfill")

_PROMPT = """For each numbered social-media post below, give:
- "language": the main language it is written in, as an English name (e.g. "English", \
"German", "French"). Swiss German counts as German.
- "author_type": classify the AUTHOR account from its name and the content — "brand" (a \
company, insurer, shop or other business account), "media" (news outlet, journalist or \
publication), "creator" (influencer, vlogger, educator, job/finance page or other content \
creator publishing to an audience), "individual" (a private person), or "other".
Respond with ONLY a JSON object: {"items": [{"n": <number>, "language": "...", "author_type": "..."}, ...]}"""


def _classify_batch(clf: RiskClassifier, batch: list[dict]) -> dict[int, dict]:
    lines = []
    for i, r in enumerate(batch):
        text = (r.get("text") or "").replace("\n", " ")[:500]
        lines.append(f"{i}. AUTHOR: {r.get('author') or 'unknown'} | CHANNEL: {r.get('platform')}\n   CONTENT: {text}")
    clf._system_prompt = _PROMPT  # reuse the classifier's key rotation / retry / throttling
    raw = clf._call_with_retry("\n".join(lines))
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        return {}
    out: dict[int, dict] = {}
    for item in data.get("items", []):
        try:
            out[int(item.get("n"))] = item
        except (TypeError, ValueError):
            continue
    return out


def backfill(name: str, recs: list[dict], save, handles: list[str], clf: RiskClassifier, redo: bool) -> int:
    if not recs:
        return 0
    todo = [r for r in recs if redo or not r.get("language") or not r.get("author_type")]
    for start in range(0, len(todo), 10):
        batch = todo[start:start + 10]
        got = _classify_batch(clf, batch)
        for i, r in enumerate(batch):
            item = got.get(i, {})
            r["language"] = post_meta.clean_language(item.get("language"), r.get("text", ""))
            r["author_type"] = post_meta.clean_author_type(item.get("author_type"))
        log.info("%s: classified %d/%d", name, min(start + 10, len(todo)), len(todo))
    for r in recs:
        if redo or not r.get("media_type"):
            r["media_type"] = post_meta.media_type(r.get("platform", ""), r.get("url"), r.get("text", ""))
        if "brand" not in r:  # own-brand mentions only; competitor posts carry their brand
            r["is_official"] = post_meta.is_official(r.get("author"), r.get("author_url"), handles)
    save(recs)
    return len(todo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-derive every record, not just missing ones")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    store.configure(cfg)
    clf = make_classifier(cfg, max_tokens=2048)
    handles = cfg.get("target", {}).get("official_handles", [])
    for name, recs, save in (
        ("mentions", mentions.load_mentions(), mentions.save_mentions),
        ("competitor posts", competitors.load_all_competitor_posts(), competitors.save_competitor_posts),
    ):
        n = backfill(name, recs, save, handles, clf, args.all)
        log.info("%s: %d record(s) classified", name, n)


if __name__ == "__main__":
    main()
