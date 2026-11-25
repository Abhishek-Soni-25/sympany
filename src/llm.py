"""Amazon Bedrock model calls (In-Region in eu-central-2, no cross-Region inference).

Two models, both called through the Bedrock Converse API:

    text model    analysis.bedrock.text_model   — sentiment / risk classification, and the
                  language + author-type backfill (Qwen3 235B A22B 2507)
    vision model  analysis.bedrock.vision_model — OCR of creative images and video frames
                  (Qwen3 VL 235B A22B)

The model ids are plain In-Region model ids (not inference profiles), so requests stay in
the Zurich Region. Throttling is retried by botocore's adaptive retry mode. The models are
asked for JSON in the prompt; callers parse it defensively.

analysis.provider: groq keeps the original Groq path for local development only.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .config import aws_region

log = logging.getLogger(__name__)

_clients: dict[str, Any] = {}
_lock = threading.Lock()


def provider(cfg: dict) -> str:
    return str(cfg.get("analysis", {}).get("provider", "bedrock")).lower()


def _bedrock(cfg: dict):
    region = aws_region(cfg)
    with _lock:
        if region not in _clients:
            import boto3
            from botocore.config import Config

            _clients[region] = boto3.client(
                "bedrock-runtime", region_name=region,
                config=Config(retries={"max_attempts": 8, "mode": "adaptive"},
                              read_timeout=180, connect_timeout=10),
            )
        return _clients[region]


def _text_of(resp: dict) -> str:
    blocks = resp.get("output", {}).get("message", {}).get("content", []) or []
    usage = resp.get("usage") or {}
    if usage:
        log.debug("Bedrock tokens in=%s out=%s", usage.get("inputTokens"), usage.get("outputTokens"))
    return "".join(b.get("text", "") for b in blocks if isinstance(b, dict)).strip()


def text_model(cfg: dict) -> str:
    return cfg.get("analysis", {}).get("bedrock", {}).get("text_model", "qwen.qwen3-235b-a22b-2507-v1:0")


def vision_model(cfg: dict) -> str:
    return cfg.get("analysis", {}).get("bedrock", {}).get("vision_model", "qwen.qwen3-vl-235b-a22b")


def bedrock_text(cfg: dict, system: str, user: str, max_tokens: int = 1024,
                 temperature: float = 0.0, model: str | None = None) -> str:
    """One Converse call to the text model; returns the response text."""
    resp = _bedrock(cfg).converse(
        modelId=model or text_model(cfg),
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": int(max_tokens), "temperature": float(temperature)},
    )
    return _text_of(resp)


def bedrock_vision(cfg: dict, system: str, instruction: str, images: list[bytes],
                   max_tokens: int = 1600, model: str | None = None) -> str:
    """One Converse call to the vision model with JPEG images; returns the response text."""
    content: list[dict[str, Any]] = [{"text": instruction}]
    for raw in images:
        content.append({"image": {"format": "jpeg", "source": {"bytes": raw}}})
    resp = _bedrock(cfg).converse(
        modelId=model or vision_model(cfg),
        system=[{"text": system}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": int(max_tokens), "temperature": 0.0},
    )
    return _text_of(resp)
