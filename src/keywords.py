"""User-managed keyword campaigns.

Custom keywords added from the Campaign page are stored here and merged into the target
keyword set used by every scan, on top of the base keywords in config.yaml.
"""

from __future__ import annotations

import logging

from . import store

log = logging.getLogger(__name__)

_DOC = "keywords"


def load_custom() -> list[str]:
    data = store.get_doc(_DOC, [])
    if not isinstance(data, list):
        return []
    return [str(k).strip() for k in data if str(k).strip()]


def save_custom(keywords: list[str]) -> list[str]:
    clean, seen = [], set()
    for k in keywords:
        k = str(k).strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            clean.append(k)
    try:
        store.put_doc(_DOC, clean)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not persist keywords: %s", exc)
    return clean


def merged(base: list[str]) -> list[str]:
    """Base config keywords plus custom ones, de-duplicated (case-insensitive)."""
    out, seen = [], set()
    for k in [*(base or []), *load_custom()]:
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out
