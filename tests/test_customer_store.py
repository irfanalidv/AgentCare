from __future__ import annotations

from pathlib import Path

from agentcare.customer import CustomerMemoryStore, get_customer_store
from agentcare.customer.memory import _database_url_with_ssl, _lexical_lookup
from agentcare.settings import settings


def test_upsert_creates_then_merges_by_email(tmp_path):
    store = CustomerMemoryStore(tmp_path / "c.json")
    first = store.upsert_from_interaction(name="Ava", email="AVA@x.com", note="call1")
    second = store.upsert_from_interaction(email="ava@x.com", phone_e164="+15550001", note="call2")
    assert first.customer_id == second.customer_id == "cust_000001"
    assert second.interaction_count == 2
    assert second.name == "Ava"
    assert second.notes == ["call1", "call2"]
    assert store.find_exact(phone_e164="+15550001").customer_id == "cust_000001"
    assert store.find_exact(email="nobody@x.com") is None


def test_rows_with_null_email_do_not_crash(tmp_path):
    store = CustomerMemoryStore(tmp_path / "c.json")
    store.upsert_from_interaction(phone_e164="+1555")
    assert store.find_exact(email="a@b.com") is None
    assert store.upsert_from_interaction(email="a@b.com").customer_id == "cust_000002"


def test_corrupt_store_is_preserved(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("[{broken", encoding="utf-8")
    store = CustomerMemoryStore(path)
    store.upsert_from_interaction(email="new@x.com")
    assert len(list(tmp_path.glob("c.json.corrupt-*"))) == 1
    assert [p.email for p in store.get_all()] == ["new@x.com"]


def test_lexical_lookup():
    rows = [
        {"customer_id": "c1", "name": "Ava Patel", "last_summary": "knee pain", "notes": []},
        {"customer_id": "c2", "name": "Ravi", "last_summary": "skin rash", "notes": []},
    ]
    hit = _lexical_lookup(rows, "rash follow up")
    assert hit["found"] and hit["customer"]["customer_id"] == "c2"
    assert not _lexical_lookup(rows, "zzz")["found"]
    assert not _lexical_lookup([], "x")["found"]


def test_semantic_lookup_falls_back_to_lexical(tmp_path):
    store = CustomerMemoryStore(tmp_path / "c.json")
    store.upsert_from_interaction(name="Ava", email="ava@x.com", summary="knee pain")
    out = store.semantic_lookup("knee")
    assert out["found"]
    assert out["customer"]["email"] == "ava@x.com"


def test_ssl_mode_is_appended_once():
    assert _database_url_with_ssl("postgres://h/db") == "postgres://h/db?sslmode=require"
    assert _database_url_with_ssl("postgres://h/db?a=1").endswith("&sslmode=require")
    assert _database_url_with_ssl("postgres://h/db?sslmode=disable").endswith("disable")


def test_placeholder_database_url_falls_back_to_json(offline, monkeypatch):
    monkeypatch.setattr(settings, "customer_store_backend", "auto")
    monkeypatch.setattr(settings, "database_url", "postgresql://u:[YOUR-PASSWORD]@h/db")
    store = get_customer_store()
    assert isinstance(store, CustomerMemoryStore)
    assert store.path == Path(settings.customer_store_path)
