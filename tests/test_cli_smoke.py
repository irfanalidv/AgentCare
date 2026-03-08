from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agentcare", *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_help_smoke() -> None:
    proc = _run("--help")
    assert proc.returncode == 0
    assert "AgentCare CLI" in proc.stdout


def test_cli_up_dry_run_smoke() -> None:
    proc = _run("up", "--dry-run")
    assert proc.returncode == 0
    assert '"dry_run": true' in proc.stdout.lower()
