#!/usr/bin/env bash
set -euo pipefail

# Guardrail: scan tracked files for likely hardcoded secrets.
# Intentionally skips `.env` because it is local/dev-only.

python3 - <<'PY'
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], text=True)
    files = []
    for raw in out.splitlines():
        p = Path(raw)
        if p.name == ".env" or p == Path("scripts/check_no_secrets.sh"):
            continue
        files.append(p)
    return files


PATTERNS = [
    ("Bolna key", re.compile(r"\bbn[-_][A-Za-z0-9]{16,}\b")),
    ("Resend key", re.compile(r"\bre_[A-Za-z0-9_-]{16,}\b")),
    ("Cal key", re.compile(r"\bcal_live_[A-Za-z0-9]{16,}\b")),
    ("Supabase publishable key", re.compile(r"\bsb_publishable_[A-Za-z0-9_-]{12,}\b")),
    ("Mistral key assignment", re.compile(r"MISTRAL_API_KEY\s*=\s*['\"][^'\"]{16,}['\"]")),
    ("Postgres URL with inline password", re.compile(r"postgresql://[^:\s/]+:[^@\s]+@[^\"'\s]+")),
]

# Placeholder fragments we allow in templates/docs.
ALLOW_FRAGMENTS = (
    "xxxxxxxx",
    "your_",
    "example",
    "placeholder",
    "onboarding@resend.dev",
    "<cal_api_key>",
)

hits: list[str] = []
for file_path in tracked_files():
    try:
        text = file_path.read_text("utf-8")
    except Exception:
        continue
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in PATTERNS:
            for match in pattern.finditer(line):
                token = match.group(0).lower()
                if any(fragment in token for fragment in ALLOW_FRAGMENTS):
                    continue
                hits.append(f"{file_path}:{lineno}: {label}: {line.strip()}")

if hits:
    print("Potential secrets detected (review before commit):")
    print("")
    for hit in hits:
        print(hit)
    print("")
    print("If any is a true secret, rotate it and replace with a placeholder.")
    sys.exit(1)

print("OK: no obvious hardcoded secrets found in tracked files.")
PY
