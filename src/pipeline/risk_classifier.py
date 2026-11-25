"""Step 3 — AI risk classification (the analytical core).

Sends each post to the text model — Amazon Bedrock (Qwen3 235B, In-Region in eu-central-2)
on AWS, or Groq for local development (analysis.provider) — for context/sarcasm/intent-aware
risk judgement against the taxonomy in docs/risk-taxonomy.md. The model is asked to return
strict JSON, validated into a `RiskAssessment`.
"""

from __future__ import annotations

import json
import logging
import re
import time

from .. import llm
from ..config import env
from ..models import Post, RiskAssessment, RISK_CATEGORIES, SEVERITIES
from ..post_meta import clean_author_type, clean_language

log = logging.getLogger(__name__)

# Parse a retry hint from a provider error: "try again in 7.5s" / "retry after 7s".
_RETRY_DELAY_RE = re.compile(r"(?:try again in|retry[- ]?after|in)\s*(\d+(?:\.\d+)?)\s*s",
                             re.IGNORECASE)

# --- The taxonomy contract (kept in sync with docs/risk-taxonomy.md) ---------

SYSTEM_PROMPT = """\
You are a financial-services surveillance risk classifier for {ORG}. You analyze a single \
piece of public or authorized social-media/communications content and judge whether it \
indicates a risk to {ORG}, against a fixed taxonomy. The content has already been screened \
as relevant to {ORG}.

CATEGORIES:
- REPUTATIONAL: public backlash, boycott coordination, executive defamation, negative viral \
brand trends, and abusive / harassing / defamatory content directed at {ORG} or its staff. \
Negative sentiment about {ORG} that does not fit another category belongs here, with severity \
scaled to intensity (abusive/defamatory/viral = HIGH or MEDIUM; mild criticism = LOW).
- COMPLIANCE_CONDUCT: insiders sharing unauthorized info, policy violations, unethical \
behavior, misrepresentation to clients, harassment.
- MARKET_ABUSE: suspicious trading discussion, insider-information leakage, market \
manipulation, pump-and-dump coordination, leaked financial metrics ahead of disclosure.
- CYBER_OPERATIONAL: data-leak mentions, credential/key exposure, system vulnerabilities, \
coordinated cyberattack planning, leaked internal infrastructure, exploited outages.
- NONE: no actionable risk.

SEVERITY:
- HIGH: high-confidence MARKET_ABUSE, CYBER_OPERATIONAL (cyber), or severe \
COMPLIANCE_CONDUCT. Immediate action.
- MEDIUM: significant negative-sentiment spikes, sustained operational critique, or \
moderate conduct concerns. Priority review.
- LOW: general negative sentiment with no actionable compliance/operational threat.
- NONE: not a risk.

JUDGEMENT RULES:
- Weigh context, sarcasm, humor, and intent. Jokes, hypotheticals, news commentary, and \
satire are usually NOT risks — lower your confidence for ambiguous content to minimize \
false positives.
- Only assign HIGH when the evidence in the text genuinely supports immediate action.
- Ground your rationale in specific wording from the content. Do not invent facts.

SENTIMENT: also judge the overall sentiment the content expresses TOWARD {ORG}: \
"positive", "neutral", or "negative". This is independent of risk — praise is positive, \
factual/news is neutral, criticism/complaints/abuse are negative.

LANGUAGE: the main language the content is written in, as an English name \
(e.g. "English", "German", "French", "Italian"). Swiss German counts as German.

AUTHOR TYPE: classify the AUTHOR account from its name and the content: \
"brand" (a company, insurer, shop or other business account, including {ORG} itself), \
"media" (a news outlet, journalist or publication), \
"creator" (an influencer, vlogger, educator, job/finance page or other content creator \
publishing to an audience), "individual" (a private person), or "other".

OUTPUT: respond with ONLY a JSON object matching this schema:
{"is_risk": boolean, "category": one of [REPUTATIONAL, COMPLIANCE_CONDUCT, MARKET_ABUSE, \
CYBER_OPERATIONAL, NONE], "severity": one of [HIGH, MEDIUM, LOW, NONE], \
"sentiment": one of [positive, neutral, negative], \
"language": "English name of the language", \
"author_type": one of [individual, creator, media, brand, other], \
"confidence": number between 0 and 1, "rationale": "short, grounded explanation", \
"indicators": ["matched signal", ...]}
If is_risk is false, category and severity must both be "NONE"."""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class RiskClassifier:
    def __init__(
        self,
        model: str | None = None,
        models: list[str] | None = None,
        max_tokens: int = 1024,
        requests_per_minute: int = 25,
        max_retries: int = 3,
        target_name: str = "the organization",
        cfg: dict | None = None,
    ) -> None:
        # {ORG} substituted via str.replace (NOT .format) — the prompt has literal JSON braces.
        self._system_prompt = SYSTEM_PROMPT.replace("{ORG}", target_name)
        self._cfg = cfg or {}
        self._target_name = target_name
        self.provider = llm.provider(self._cfg)   # defaults to Amazon Bedrock
        # Ordered fallback chain: if a model's quota is hit, roll over to the next.
        chain = list(models) if models else []
        if model and model not in chain:
            chain.insert(0, model)
        self.models = chain or ["llama-3.3-70b-versatile"]
        self.max_tokens = max_tokens
        self._min_interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._max_retries = max_retries
        self._last_call = 0.0
        self._exhausted: set[str] = set()
        if self.provider == "bedrock":
            # Amazon Bedrock: one In-Region text model; credentials come from the task role.
            self.models = [llm.text_model(self._cfg)]
            return
        # One or more Groq API keys. Rotating across keys multiplies the free-tier daily
        # quota: GROQ_API_KEY (primary) plus optional GROQ_API_KEY_2, _3, ... and/or a
        # comma-separated GROQ_API_KEYS. When every model is exhausted on the current key
        # we advance to the next key and reset the exhausted-model set.
        self._keys = self._collect_keys()
        if not self._keys:
            raise RuntimeError(
                "No Groq API key found. Set GROQ_API_KEY (and optionally GROQ_API_KEY_2, "
                "GROQ_API_KEY_3 or GROQ_API_KEYS) in .env."
            )
        self._key_idx = 0
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("groq not installed; pip install groq") from exc
        self._Groq = Groq
        self._client = Groq(api_key=self._keys[0])

    @staticmethod
    def _collect_keys() -> list[str]:
        keys: list[str] = []
        primary = env("GROQ_API_KEY")
        if primary:
            keys.append(primary.strip())
        for extra in (env("GROQ_API_KEYS") or "").split(","):
            extra = extra.strip()
            if extra and extra not in keys:
                keys.append(extra)
        idx = 2
        while True:
            k = env(f"GROQ_API_KEY_{idx}")
            if not k:
                break
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
            idx += 1
        return keys

    def _rotate_key(self) -> bool:
        """Advance to the next API key, resetting exhausted models. False if none left."""
        if self._key_idx + 1 >= len(self._keys):
            return False
        self._key_idx += 1
        self._client = self._Groq(api_key=self._keys[self._key_idx])
        self._exhausted.clear()
        log.warning(
            "Rotating to Groq API key #%d of %d (previous key's quota exhausted).",
            self._key_idx + 1, len(self._keys),
        )
        return True

    @property
    def active_model(self) -> str | None:
        for m in self.models:
            if m not in self._exhausted:
                return m
        return None

    def classify(self, post: Post) -> RiskAssessment:
        meta = post.raw_meta or {}
        user_content = (
            f"CHANNEL: {post.channel}\n"
            f"SOURCE: {post.source}\n"
            f"AUTHOR: {meta.get('author_name') or post.author_id}\n"
            f"TIMESTAMP: {post.timestamp.isoformat()}\n"
            f"CONTENT:\n{post.text}"
        )
        try:
            raw = self._call_with_retry(user_content)
            try:
                assessment = self._parse(raw)
            except ValueError as exc:            # json.JSONDecodeError is a ValueError
                # At temperature 0 the model gives the same broken answer every time (e.g.
                # stray characters in the middle of the JSON), so retrying later cannot help:
                # ask once more, sampling slightly differently, for the JSON only.
                if self.provider != "bedrock":
                    raise
                log.warning("Unreadable answer for %s/%s (%s); asking again", post.channel, post.message_id, exc)
                self._throttle()
                try:
                    raw = llm.bedrock_text(
                        self._cfg, self._system_prompt,
                        user_content + "\n\nReply with ONLY the JSON object, in plain ASCII text.",
                        max_tokens=self.max_tokens, temperature=0.3, model=self.models[0])
                finally:
                    self._last_call = time.monotonic()
                assessment = self._parse(raw)
            assessment.language = clean_language(assessment.language, post.text)
            return assessment
        except Exception as exc:
            log.error(
                "Risk classification failed for %s/%s: %s",
                post.channel, post.message_id, exc,
            )
            return RiskAssessment(
                is_risk=False, category="NONE", severity="NONE",
                confidence=0.0, rationale=f"classifier error: {exc}", indicators=[],
                language=clean_language(None, post.text), failed=True,
            )

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _call_with_retry(self, user_content: str) -> str:
        if self.provider == "bedrock":
            # botocore's adaptive retry handles throttling; the local throttle just keeps
            # a long scan within the account's requests-per-minute quota.
            self._throttle()
            try:
                return llm.bedrock_text(self._cfg, self._system_prompt, user_content,
                                        max_tokens=self.max_tokens, model=self.models[0])
            finally:
                self._last_call = time.monotonic()
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]
        attempt = 0
        while True:
            model = self.active_model
            if model is None:
                raise RuntimeError(
                    f"All configured models exhausted: {', '.join(self.models)}."
                )
            self._throttle()
            # gpt-oss models reason before answering; keep that short so the JSON fits.
            extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                    **extra,
                )
                self._last_call = time.monotonic()
                return resp.choices[0].message.content or ""
            except Exception as exc:
                self._last_call = time.monotonic()
                if self._is_daily_quota(exc):
                    self._exhausted.add(model)
                    nxt = self.active_model
                    if nxt:
                        log.warning("Model '%s' daily quota hit; falling back to '%s'.", model, nxt)
                        attempt = 0
                        continue
                    # Every model exhausted on this key — try the next API key.
                    if self._rotate_key():
                        attempt = 0
                        continue
                    log.error("All models exhausted on all API keys (last: '%s').", model)
                    raise
                # gpt-oss occasionally writes a number as a word ("confidence": 0. nine); Groq
                # rejects that, but returns the answer, which is usable once repaired.
                if "json_validate_failed" in str(exc):
                    repaired = _repair_failed_generation(exc)
                    if repaired:
                        return repaired
                # Otherwise invalid JSON in json mode — ask again.
                if "json_validate_failed" in str(exc) and attempt < self._max_retries:
                    attempt += 1
                    continue
                if self._is_rate_limit(exc) and attempt < self._max_retries:
                    delay = self._retry_delay(exc, attempt)
                    log.warning(
                        "Groq rate-limited on '%s' (attempt %d/%d); retrying in %.1fs",
                        model, attempt + 1, self._max_retries, delay,
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        s = str(exc).lower()
        return "429" in s or "rate limit" in s or "rate_limit" in s or "ratelimit" in s

    @staticmethod
    def _is_daily_quota(exc: Exception) -> bool:
        s = str(exc).lower()
        return "per day" in s or "rpd" in s or "tokens per day" in s or "tpd" in s

    @staticmethod
    def _retry_delay(exc: Exception, attempt: int) -> float:
        match = _RETRY_DELAY_RE.search(str(exc))
        if match:
            return float(match.group(1)) + 1.0
        return min(2.0 ** attempt, 60.0)

    def _parse(self, raw: str) -> RiskAssessment:
        match = _JSON_RE.search(raw)
        if not match:
            raise ValueError(f"No JSON object in model response: {raw[:200]!r}")
        data = json.loads(match.group(0))

        category = str(data.get("category", "NONE")).upper()
        severity = str(data.get("severity", "NONE")).upper()
        if category not in RISK_CATEGORIES:
            category = "NONE"
        if severity not in SEVERITIES:
            severity = "NONE"
        is_risk = bool(data.get("is_risk", False)) and category != "NONE"
        if not is_risk:
            category, severity = "NONE", "NONE"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        sentiment = str(data.get("sentiment", "neutral")).lower()
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = "neutral"

        return RiskAssessment(
            is_risk=is_risk,
            category=category,
            severity=severity,
            confidence=round(confidence, 3),
            rationale=str(data.get("rationale", "")).strip(),
            indicators=[str(i) for i in data.get("indicators", [])][:10],
            sentiment=sentiment,
            language=str(data.get("language", "")).strip(),
            author_type=clean_author_type(data.get("author_type")),
        )


def make_classifier(cfg: dict, target_name: str | None = None, **overrides) -> RiskClassifier:
    """Build the classifier from config.yaml -> analysis (provider, models, rate limits)."""
    a = cfg.get("analysis", {})
    bedrock = llm.provider(cfg) == "bedrock"
    rpm = a.get("bedrock", {}).get("requests_per_minute", 60) if bedrock else a.get("requests_per_minute", 25)
    kwargs = dict(
        model=a.get("model"),
        models=a.get("models"),
        max_tokens=a.get("max_tokens", 1024),
        requests_per_minute=rpm,
        max_retries=a.get("max_retries", 3),
        target_name=target_name or cfg.get("target", {}).get("name", "the organization"),
        cfg=cfg,
    )
    kwargs.update(overrides)
    return RiskClassifier(**kwargs)


_DIGIT_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def _repair_failed_generation(exc: Exception) -> str | None:
    """The model's answer from a Groq json_validate_failed error, with numbers written as
    words ("0. nine", "0.nine") turned back into digits; None if it still is not JSON."""
    body = getattr(exc, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else {}
    text = err.get("failed_generation") if isinstance(err, dict) else None
    if not text:
        return None
    fixed = re.sub(r"(\d)\.\s*(zero|one|two|three|four|five|six|seven|eight|nine)\b",
                   lambda m: f"{m.group(1)}.{_DIGIT_WORDS[m.group(2)]}", text, flags=re.I)
    try:
        json.loads(_JSON_RE.search(fixed).group(0))
    except (AttributeError, ValueError):
        return None
    return fixed

