"""T01: хранилище, ID, журнал, схемы."""
import threading

from strateg.lib import clock, ids, journal, schema, store


def test_next_id_empty_and_max(tmp_path):
    p = tmp_path / "c.jsonl"
    assert ids.next_id(p, "C") == "C-001"
    store.append_jsonl(p, {"id": "C-001"})
    store.append_jsonl(p, {"id": "C-005"})
    assert ids.next_id(p, "C") == "C-006"
    assert ids.next_id(tmp_path / "e.jsonl", "E", width=6) == "E-000001"


def test_append_is_atomic_under_threads(tmp_path):
    p = tmp_path / "x.jsonl"
    ts = [threading.Thread(target=store.append_jsonl, args=(p, {"id": f"X-{i:03d}", "pad": "я" * 500})) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    recs = store.read_jsonl(p)
    assert len(recs) == 20 and {r["id"] for r in recs} == {f"X-{i:03d}" for i in range(20)}


def test_read_missing_is_empty(tmp_path):
    assert store.read_jsonl(tmp_path / "none.jsonl") == []


def test_op_id_deterministic():
    a = ids.op_id("claim add", {"text": "x", "type": "fact", "json": True, "project": "p"})
    b = ids.op_id("claim add", {"type": "fact", "text": "x"})
    c = ids.op_id("claim add", {"type": "fact", "text": "y"})
    assert a == b and a != c and len(a) == 16


def test_update_record_keeps_history(tmp_path):
    p = tmp_path / "c.jsonl"
    store.append_jsonl(p, {"id": "C-001", "text": "a", "updated_at": "2026-01-01T00:00:00Z"})
    rec = store.update_record(p, "C-001", {"text": "b"}, reason="уточнение", actor="human")
    assert rec["text"] == "b"
    h = rec["history"][-1]
    assert (h["field"], h["old"], h["new"], h["reason"], h["actor"]) == ("text", "a", "b", "уточнение", "human")
    assert store.read_jsonl(p)[0]["text"] == "b"


def test_write_json_roundtrip(tmp_path):
    p = tmp_path / "d" / "p.json"
    store.write_json(p, {"а": 1})
    assert store.read_json(p) == {"а": 1}
    assert "а" in p.read_text(encoding="utf-8")


def test_journal_idempotent(project, root, monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: "2026-11-10T09:00:00Z")
    e1 = journal.log(project, "note", "проверка", {"k": 1}, op_id="op-fixed-0001")
    e2 = journal.log(project, "note", "проверка", {"k": 1}, op_id="op-fixed-0001")
    assert e1["id"] == e2["id"]
    notes = [e for e in journal.read(project) if e["kind"] == "note"]
    assert len(notes) == 1 and notes[0]["at"] == "2026-11-10T09:00:00Z"
    assert schema.validate(notes[0], "event") == []


def test_schema_reports_errors():
    errs = schema.validate({"id": "C-001"}, "claim")
    assert errs and all(isinstance(e, str) for e in errs)
