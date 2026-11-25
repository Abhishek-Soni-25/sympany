"""Create a dashboard sign-in account (auth.mode: password).

    python -m tools.create_app_user sympany.admin                  # generates a strong password
    python -m tools.create_app_user sympany.admin --prompt         # type the password yourself
    python -m tools.create_app_user sympany.admin --existing "<current APP_USERS value>"

Prints the password once (when generated) and the APP_USERS value to store in the
SecureString parameter /sympany-socmon/APP_USERS. Only the PBKDF2 hash is stored; the
password itself is never written anywhere — hand it to the user over a separate,
secure channel. Running it again for the same username replaces that user's password.
"""

from __future__ import annotations

import argparse
import getpass
import re
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.auth import hash_password  # noqa: E402

_NAME = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,63}$")
_ALPHABET = string.ascii_letters + string.digits + "!#%+-=?@^_"


def _generate(length: int = 20) -> str:
    while True:
        pw = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw)):
            return pw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username", help="sign-in name, e.g. sympany.admin (lower-case letters, digits, . _ @ -)")
    ap.add_argument("--prompt", action="store_true", help="type the password instead of generating one")
    ap.add_argument("--existing", default="", help="current APP_USERS value, to add/replace a user in it")
    args = ap.parse_args()

    name = args.username.strip().lower()
    if not _NAME.match(name):
        ap.error("username must be 3-64 characters: lower-case letters, digits, '.', '_', '@' or '-'")

    if args.prompt:
        pw = getpass.getpass("Password (min 14 characters): ")
        if len(pw) < 14:
            ap.error("password must be at least 14 characters")
        if getpass.getpass("Repeat password: ") != pw:
            ap.error("passwords do not match")
        generated = False
    else:
        pw, generated = _generate(), True

    entries = [e.strip() for e in args.existing.replace("\n", ",").split(",") if e.strip()]
    entries = [e for e in entries if e.partition(":")[0].strip().lower() != name]
    entries.append(f"{name}:{hash_password(pw)}")

    print()
    print(f"Username : {name}")
    if generated:
        print(f"Password : {pw}")
        print("           (shown once — give it to the user over a secure channel)")
    print()
    print("Store this value in the SecureString parameter /sympany-socmon/APP_USERS:")
    print(",".join(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
