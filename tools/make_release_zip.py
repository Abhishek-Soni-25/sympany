"""Build the release zip that is uploaded to AWS (S3 → CodeBuild).

    python tools/make_release_zip.py            # -> ../sympany-socmon-<date>.zip

Packs the source the Docker build needs and leaves out everything that must not leave
this machine or is rebuilt in the image: .env (secrets), virtualenvs, node_modules, the
built frontend, git metadata, local cursor state and caches.
"""

from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {".venv", "node_modules", "dist", ".git", "__pycache__", ".claude", "state", ".pytest_cache"}
EXCLUDE_FILES = {".env", "live1.json", "live2.json"}
EXCLUDE_SUFFIXES = {".pyc", ".log", ".zip", ".session", ".session-journal", ".tsbuildinfo"}


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
        return False
    if rel.name in EXCLUDE_FILES or (rel.name.startswith(".env") and rel.name != ".env.example"):
        return False
    return path.suffix not in EXCLUDE_SUFFIXES


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / f"sympany-socmon-{datetime.now():%Y%m%d-%H%M}.zip"
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and included(p))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())
    secrets = [p for p in files if p.name == ".env"]
    assert not secrets, "refusing to ship .env"
    print(f"{out}  ({len(files)} files, {out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
