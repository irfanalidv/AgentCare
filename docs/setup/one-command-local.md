# One-Command Local Setup

## 1) Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[web,postgres,email,semantic]"
```

## 2) Configure

```bash
cp .env.example .env
```

Fill at least:
- `BOLNA_API_KEY`
- `MISTRAL_API_KEY`

## 3) Start stack

```bash
python3 -m agentcare up
```

Dry run:

```bash
python3 -m agentcare up --dry-run
```

Alternative helper:

```bash
bash scripts/dev_up.sh
```
