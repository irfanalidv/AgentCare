# Contributing to AgentCare

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[web,postgres,email,semantic]"
```

## Development workflow

1. Create a feature branch.
2. Run tests and lint checks before opening a PR.
3. Keep changes focused; include docs updates for user-visible behavior.

## Quality checks

```bash
python3 -m compileall src services
pytest -q
python3 -m build
twine check dist/*
```

## Pull requests

- Include a clear problem statement and implementation summary.
- Add/adjust tests for changed behavior.
- Update `README.md` and `ARCHITECTURE.md` when architecture or setup changes.
