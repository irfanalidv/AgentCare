from __future__ import annotations

import json

from agentcare._jsonio import read_json, write_json_atomic


def test_missing_file_returns_default(tmp_path):
    assert read_json(tmp_path / "nope.json", [], expected=list) == []


def test_roundtrip_is_atomic(tmp_path):
    path = tmp_path / "sub" / "rows.json"
    write_json_atomic(path, [{"a": 1}])
    assert read_json(path, [], expected=list) == [{"a": 1}]
    assert [p.name for p in path.parent.iterdir()] == ["rows.json"]  # no temp files left


def test_corrupt_file_is_moved_aside_not_overwritten(tmp_path, caplog):
    path = tmp_path / "customers.json"
    path.write_text('[{"customer_id": "cust_000001"', encoding="utf-8")  # truncated
    with caplog.at_level("WARNING"):
        assert read_json(path, [], expected=list) == []
    backups = list(tmp_path.glob("customers.json.corrupt-*"))
    assert len(backups) == 1
    assert "cust_000001" in backups[0].read_text(encoding="utf-8")
    assert "moved aside" in caplog.text


def test_wrong_top_level_type_is_quarantined(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert read_json(path, [], expected=list) == []
    assert not path.exists()
