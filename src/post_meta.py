"""Per-post descriptive metadata stored alongside each mention.

Feeds the Listening / Competition report panels with REAL values instead of fixed splits:

    media_type   video | image | link | text   (from the actor payload, else the permalink)
    is_official  True when the brand's own account authored it (outgoing vs incoming)
    language     the post's main language (the LLM decides; Unicode script is the fallback)
    author_type  individual | creator | media | brand | other (the LLM decides from the
                 author name + content)
"""

from __future__ import annotations

import re

MEDIA_TYPES = ("video", "image", "link", "text")
AUTHOR_TYPES = ("individual", "creator", "media", "brand", "other")

_VIDEO_URL = re.compile(r"/(reel|reels|videos?|watch|shorts|tv)\b|youtu\.be/|[?&]v=", re.I)
_PHOTO_URL = re.compile(r"/photos?\b|/photo\.php", re.I)
_LINK_IN_TEXT = re.compile(r"https?://\S+", re.I)

# Platforms whose items are always videos.
_VIDEO_PLATFORMS = {"youtube", "youtube_channel", "youtube_shorts", "tiktok"}


def media_type(platform: str, url: str | None, text: str, hint: str | None = None) -> str:
    """Best-known media type: the connector's hint wins, then the platform/permalink."""
    if hint in MEDIA_TYPES:
        return hint
    if platform in _VIDEO_PLATFORMS:
        return "video"
    u = url or ""
    if _VIDEO_URL.search(u):
        return "video"
    if _PHOTO_URL.search(u):
        return "image"
    if platform == "instagram":          # an Instagram post without a video is a photo/carousel
        return "image"
    if _LINK_IN_TEXT.search(text or ""):
        return "link"
    return "text"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def is_official(author: str | None, author_url: str | None, handles: list[str]) -> bool:
    """True when the author (name or profile URL) matches one of the brand's own handles."""
    wanted = {_norm(h) for h in handles if h}
    if not wanted:
        return False
    if _norm(author or "") in wanted:
        return True
    tail = (author_url or "").rstrip("/").rsplit("/", 1)[-1].lstrip("@")
    return _norm(tail) in wanted


# Unicode script blocks -> language. Latin script defaults to English.
_SCRIPTS = (
    ("Malayalam", 0x0D00, 0x0D7F), ("Tamil", 0x0B80, 0x0BFF), ("Telugu", 0x0C00, 0x0C7F),
    ("Kannada", 0x0C80, 0x0CFF), ("Bengali", 0x0980, 0x09FF), ("Gujarati", 0x0A80, 0x0AFF),
    ("Punjabi", 0x0A00, 0x0A7F), ("Odia", 0x0B00, 0x0B7F), ("Hindi", 0x0900, 0x097F),
    ("Arabic", 0x0600, 0x06FF),
)


def script_language(text: str) -> str:
    """Fallback language guess from the dominant non-Latin script (else English)."""
    counts: dict[str, int] = {}
    latin = 0
    for ch in text or "":
        cp = ord(ch)
        if ch.isascii():
            latin += ch.isalpha()
            continue
        for name, lo, hi in _SCRIPTS:
            if lo <= cp <= hi:
                counts[name] = counts.get(name, 0) + 1
                break
    if counts:
        name, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= latin * 0.3:
            return name
    return "English"


def clean_language(value: object, text: str) -> str:
    v = str(value or "").strip()
    if not v or v.lower() in ("unknown", "none", "null", "n/a", "mixed"):
        return script_language(text)
    return v[:1].upper() + v[1:]


def clean_author_type(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in AUTHOR_TYPES else "other"
