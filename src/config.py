"""Configuration + secrets loading.

`config/config.yaml` holds non-secret runtime settings; secrets come from the environment:
`.env` for local development, or AWS Systems Manager Parameter Store on AWS (the ECS task
definition injects them, or SSM_PARAMETER_PATH loads every parameter under a path).
Secrets are never read from the YAML.

Deployment settings (storage backend, AI provider, auth mode, table names, ...) live in
config.yaml with AWS defaults; each can be overridden by an environment variable (see
_ENV_OVERRIDES) so the same image runs on AWS and on a developer machine.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"
CASES_DIR = DATA_DIR / "cases"
STATE_DIR = DATA_DIR / "state"

# env var -> (config path, type). Applied after the YAML is read.
_ENV_OVERRIDES: dict[str, tuple[tuple[str, ...], Any]] = {
    "AWS_REGION": (("aws", "region"), str),
    "STORAGE_BACKEND": (("storage", "backend"), str),
    "DYNAMODB_TABLE": (("storage", "table"), str),
    "DYNAMODB_AUDIT_TABLE": (("storage", "audit_table"), str),
    "POST_RETENTION_DAYS": (("storage", "post_retention_days"), int),
    "AI_PROVIDER": (("analysis", "provider"), str),
    "BEDROCK_TEXT_MODEL": (("analysis", "bedrock", "text_model"), str),
    "BEDROCK_VISION_MODEL": (("analysis", "bedrock", "vision_model"), str),
    "TRANSCRIBE_PROVIDER": (("transcription", "provider"), str),
    "AUTH_MODE": (("auth", "mode"), str),
    "ADMIN_GROUP": (("auth", "admin_group"), str),
    "SESSION_HOURS": (("auth", "session_hours"), float),
    "SCAN_LAUNCH": (("scan", "launch"), str),
    "SCAN_DAILY_AT": (("scan", "daily_at"), str),
    "SCAN_MANUAL_PER_DAY": (("scan", "manual_per_day"), int),
    "DASHBOARD_URL": (("escalation", "dashboard_url"), str),
    "FEATURE_MEDIA_COMPLIANCE": (("features", "media_compliance"), lambda v: v.strip().lower() in ("1", "true", "yes", "on")),
}

_ssm_loaded = False


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML runtime config, secrets (.env / Parameter Store) and env overrides."""
    load_dotenv(PROJECT_ROOT / ".env")
    _load_ssm_parameters()
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    for name, (keys, cast) in _ENV_OVERRIDES.items():
        val = os.environ.get(name)
        if val not in (None, ""):
            node = cfg
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = cast(val)
    if storage_backend(cfg) == "local":
        _ensure_dirs()
    return cfg


def storage_backend(cfg: dict) -> str:
    return str(cfg.get("storage", {}).get("backend", "local")).lower()


def aws_region(cfg: dict | None = None) -> str:
    return os.environ.get("AWS_REGION") or (cfg or {}).get("aws", {}).get("region") or "eu-central-2"


def _load_ssm_parameters() -> None:
    """Load every parameter under SSM_PARAMETER_PATH (e.g. /sympany-socmon/) into
    the environment, using the parameter's last path segment as the variable name
    (/sympany-socmon/APIFY_TOKEN -> APIFY_TOKEN). Values already set in the
    environment (e.g. injected by the ECS task definition) win. No-op when unset."""
    global _ssm_loaded
    prefix = os.environ.get("SSM_PARAMETER_PATH", "").strip()
    if _ssm_loaded or not prefix:
        return
    _ssm_loaded = True
    try:
        import boto3

        client = boto3.client("ssm", region_name=aws_region())
        paginator = client.get_paginator("get_parameters_by_path")
        count = 0
        for page in paginator.paginate(Path=prefix, Recursive=True, WithDecryption=True):
            for p in page.get("Parameters", []):
                name = p["Name"].rstrip("/").rsplit("/", 1)[-1]
                if name and not os.environ.get(name):
                    os.environ[name] = p["Value"]
                    count += 1
        log.info("Loaded %d secret(s) from Parameter Store path %s", count, prefix)
    except Exception as exc:  # noqa: BLE001 — a missing permission must not crash startup
        log.warning("Could not load Parameter Store path %s: %s", prefix, exc)


def _ensure_dirs() -> None:
    for d in (DATA_DIR, CASES_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)


# Values that mark a secret as "not provided yet". The Parameter Store entries are created
# with PLACEHOLDER until the real provider keys arrive; such a value counts as unset, so the
# channel that needs it is skipped with a warning instead of calling the API with it.
_PLACEHOLDERS = {"placeholder", "changeme", "change_me", "change-me", "todo", "tbd", "none", "null", "-"}


def is_placeholder(val: str | None) -> bool:
    v = (val or "").strip()
    return not v or v.lower() in _PLACEHOLDERS or (v.startswith("<") and v.endswith(">"))


def env(name: str, required: bool = False, default: str | None = None) -> str | None:
    """Read an environment variable, optionally requiring it. Placeholder values count as unset."""
    val = os.environ.get(name, default)
    if is_placeholder(val):
        val = default if not is_placeholder(default) else None
    if required and not val:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Add it to your .env file (see .env.example)."
        )
    return val
