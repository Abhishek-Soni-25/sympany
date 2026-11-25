"""Authentication.

auth.mode: password (AWS, default)
    The application signs users in itself — no Cognito, no SSO. Accounts come from the
    APP_USERS secret (Parameter Store), one "username:pbkdf2-hash" entry per user,
    comma-separated; create entries with `python -m tools.create_app_user <username>`.
    POST /api/login checks the password and sets an HMAC-signed, HttpOnly session cookie
    (key: SESSION_SECRET, shared by every web task). Failed logins are rate-limited per
    username and per client address.

auth.mode: alb (AWS, optional)
    The ALB's authenticate-cognito rule signs the user in (Cognito managed login, optionally
    federated to Sympany's IdP over SAML / OIDC) and forwards every request with:
      x-amzn-oidc-data         ES256 JWT signed by the ALB — the user's claims
      x-amzn-oidc-accesstoken  the Cognito access token (carries cognito:groups)
    Every /api request (except /api/health) must carry a valid x-amzn-oidc-data token:
    the signature is checked against the ALB public key for its `kid`
    (https://public-keys.auth.elb.<region>.amazonaws.com/<kid>), the `signer` must equal
    ALB_ARN when set, and the token must not be expired. Group membership is read from the
    access token after verifying it against the user pool's JWKS (COGNITO_USER_POOL_ID).
    If auth.admin_group / ADMIN_GROUP is set, the administrative endpoints (run a scan,
    edit keywords, change the Do's and Don'ts) require that group.

auth.mode: none (local development)
    No verification; the frontend shows its local sign-in screen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import aws_region, env

log = logging.getLogger(__name__)

_ALB_KEY_URL = "https://public-keys.auth.elb.{region}.amazonaws.com/{kid}"
_JWKS_URL = "https://cognito-idp.{region}.amazonaws.com/{pool}/.well-known/jwks.json"
_key_cache: dict[str, Any] = {}
_jwks_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


class AuthError(Exception):
    pass


@dataclass
class User:
    sub: str
    email: str = ""
    name: str = ""
    groups: list[str] = field(default_factory=list)
    is_admin: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"sub": self.sub, "email": self.email, "name": self.name,
                "groups": self.groups, "is_admin": self.is_admin}


def mode(cfg: dict) -> str:
    return str(cfg.get("auth", {}).get("mode", "password")).lower()


# ---------------------------------------------------------------------------------------
# auth.mode: password — application-managed accounts and signed session cookies
# ---------------------------------------------------------------------------------------

SESSION_COOKIE = "sympany_session"
_PBKDF2_ITERATIONS = 600_000
_MAX_FAILURES = 5                     # failed logins allowed per window ...
_FAILURE_WINDOW = 15 * 60             # ... per username and per client address
_failures: dict[str, list[float]] = {}


def hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """PBKDF2-SHA256 hash in the form pbkdf2_sha256$<iterations>$<salt>$<hash>."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def _check_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt, expected = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _b64(salt), int(iterations))
        return hmac.compare_digest(digest, _b64(expected))
    except Exception:  # noqa: BLE001 — a malformed entry never authenticates
        return False


# Verified against when the username is unknown, so a wrong username costs the same time
# as a wrong password (no username enumeration by timing).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16), iterations=_PBKDF2_ITERATIONS)


def _users() -> dict[str, str]:
    """APP_USERS: "alice:pbkdf2_sha256$...,bob:pbkdf2_sha256$..." -> {username: hash}."""
    users: dict[str, str] = {}
    for entry in (env("APP_USERS") or "").replace("\n", ",").split(","):
        name, sep, encoded = entry.strip().partition(":")
        if sep and name.strip() and encoded.strip():
            users[name.strip().lower()] = encoded.strip()
    return users


def _session_key() -> bytes:
    secret = env("SESSION_SECRET") or ""
    if len(secret) < 32:
        raise AuthError("sign-in is not configured (SESSION_SECRET missing or shorter than 32 characters)")
    return secret.encode("utf-8")


def _limited(keys: list[str]) -> bool:
    now = time.time()
    with _lock:
        for k in keys:
            recent = [t for t in _failures.get(k, []) if now - t < _FAILURE_WINDOW]
            _failures[k] = recent
            if len(recent) >= _MAX_FAILURES:
                return True
    return False


def _record_failure(keys: list[str]) -> None:
    now = time.time()
    with _lock:
        if len(_failures) > 10_000:              # bound memory under a password-spraying run
            for k in [k for k, ts in _failures.items() if not ts or now - ts[-1] >= _FAILURE_WINDOW]:
                del _failures[k]
        for k in keys:
            _failures.setdefault(k, []).append(now)


def login(username: str, password: str, client: str) -> str:
    """Check a username/password; return the username or raise AuthError."""
    name = (username or "").strip().lower()
    keys = [f"user:{name}", f"addr:{client}"]
    if _limited(keys):
        raise AuthError("too many failed sign-in attempts — try again in 15 minutes")
    encoded = _users().get(name)
    ok = _check_password(password or "", encoded or _DUMMY_HASH) and encoded is not None
    if not ok:
        _record_failure(keys)
        log.warning("failed sign-in for %r from %s", name, client)
        raise AuthError("incorrect username or password")
    with _lock:
        for k in keys:
            _failures.pop(k, None)
    log.info("signed in: %s from %s", name, client)
    return name


def issue_session(username: str, hours: float) -> str:
    """Signed session token: base64url(json claims) + "." + base64url(HMAC-SHA256)."""
    now = int(time.time())
    body = base64.urlsafe_b64encode(json.dumps(
        {"sub": username, "iat": now, "exp": now + int(hours * 3600)}, separators=(",", ":"),
    ).encode()).decode().rstrip("=")
    sig = hmac.new(_session_key(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def verify_session(token: str) -> dict:
    try:
        body, sig = token.split(".")
    except ValueError as exc:
        raise AuthError("malformed session") from exc
    expected = hmac.new(_session_key(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64(sig)):
        raise AuthError("bad session signature")
    claims = json.loads(_b64(body))
    if int(claims.get("exp", 0)) < time.time():
        raise AuthError("session expired")
    # A user removed from APP_USERS loses access at their next request.
    if str(claims.get("sub", "")).lower() not in _users():
        raise AuthError("account no longer exists")
    return claims


def _b64(part: str) -> bytes:
    """Base64 / base64url decode, tolerant of missing or extra padding (the ALB pads)."""
    part = part.strip().replace("-", "+").replace("_", "/").rstrip("=")
    return base64.b64decode(part + "=" * (-len(part) % 4))


def _split(token: str) -> tuple[dict, dict, bytes, bytes]:
    try:
        h, p, s = token.split(".")
        return json.loads(_b64(h)), json.loads(_b64(p)), f"{h}.{p}".encode(), _b64(s)
    except Exception as exc:  # noqa: BLE001
        raise AuthError(f"malformed token: {exc}") from exc


def _alb_public_key(kid: str, region: str):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    with _lock:
        if kid in _key_cache:
            return _key_cache[kid]
    url = _ALB_KEY_URL.format(region=region, kid=kid)
    with urllib.request.urlopen(url, timeout=10) as resp:
        key = load_pem_public_key(resp.read())
    with _lock:
        _key_cache[kid] = key
    return key


def verify_alb_token(token: str, region: str, alb_arn: str | None = None) -> dict:
    """Verify the ALB-signed x-amzn-oidc-data JWT and return its claims."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    header, claims, signed, sig = _split(token)
    if header.get("alg") != "ES256" or not header.get("kid"):
        raise AuthError("unexpected token algorithm")
    if alb_arn and header.get("signer") != alb_arn:
        raise AuthError("token not signed by this load balancer")
    if int(header.get("exp") or claims.get("exp") or 0) < time.time():
        raise AuthError("token expired")
    key = _alb_public_key(header["kid"], region)
    if len(sig) == 64:                         # raw r||s -> DER
        sig = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
    try:
        key.verify(sig, signed, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise AuthError("bad token signature") from exc
    return claims


def _jwks(pool_id: str, region: str) -> dict:
    with _lock:
        hit = _jwks_cache.get(pool_id)
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
    with urllib.request.urlopen(_JWKS_URL.format(region=region, pool=pool_id), timeout=10) as resp:
        data = json.loads(resp.read())
    keys = {k["kid"]: k for k in data.get("keys", [])}
    with _lock:
        _jwks_cache[pool_id] = (time.time(), keys)
    return keys


def verify_cognito_token(token: str, pool_id: str, region: str) -> dict:
    """Verify a Cognito (RS256) access token against the user pool JWKS; return claims."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    header, claims, signed, sig = _split(token)
    jwk = _jwks(pool_id, region).get(header.get("kid", ""))
    if not jwk or header.get("alg") != "RS256":
        raise AuthError("unknown access-token key")
    n = int.from_bytes(_b64(jwk["n"]), "big")
    e = int.from_bytes(_b64(jwk["e"]), "big")
    try:
        rsa.RSAPublicNumbers(e, n).public_key().verify(sig, signed, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise AuthError("bad access-token signature") from exc
    if int(claims.get("exp", 0)) < time.time():
        raise AuthError("access token expired")
    if not str(claims.get("iss", "")).endswith(f"/{pool_id}"):
        raise AuthError("access token from another user pool")
    return claims


def authenticate(headers, cfg: dict, cookies: dict | None = None) -> User:
    """Return the signed-in user for a request, or raise AuthError."""
    if mode(cfg) == "password":
        token = (cookies or {}).get(SESSION_COOKIE)
        if not token:
            raise AuthError("not signed in")
        name = str(verify_session(token).get("sub", ""))
        return User(sub=name, email=name, name=name)
    if mode(cfg) != "alb":
        return User(sub="local", email="local-user", name="Local user")
    region = aws_region(cfg)
    data = headers.get("x-amzn-oidc-data")
    if not data:
        raise AuthError("not signed in")
    claims = verify_alb_token(data, region, os.environ.get("ALB_ARN") or None)

    groups: list[str] = []
    pool = os.environ.get("COGNITO_USER_POOL_ID", "").strip()
    access = headers.get("x-amzn-oidc-accesstoken")
    if pool and access:
        try:
            groups = list(verify_cognito_token(access, pool, region).get("cognito:groups") or [])
        except AuthError as exc:
            log.warning("access token rejected: %s", exc)

    admin_group = str(cfg.get("auth", {}).get("admin_group", "") or "").strip()
    return User(
        sub=str(claims.get("sub", "")),
        email=str(claims.get("email") or claims.get("username") or ""),
        name=str(claims.get("name") or claims.get("given_name") or claims.get("email") or ""),
        groups=groups,
        is_admin=(not admin_group) or admin_group in groups,
    )


# ALB session cookies to clear on sign-out (the ALB shards the cookie up to 4 parts).
SESSION_COOKIES = [f"AWSELBAuthSessionCookie-{i}" for i in range(4)]
