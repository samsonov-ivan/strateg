"""T13: каскад маршрутизации. T14: хуки. T15: doctor."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from strateg.lib.out import CliError
from strateg.route import cascade
from strateg.route.clients import FakeClient
from tests.conftest import state

Q = {"claim_type": {"type": "choice", "instructions": "Тип?", "criteria": {"fact": "f", "hypothesis": "h"}}}
HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"


def test_cascade_primary_and_escalations(cli, project, root):
    hi = FakeClient({"claim_type": "fact"}, 0.95, cost_usd=0.001, name="jev")
    lo = FakeClient({"claim_type": "fact"}, 0.40, cost_usd=0.001, name="jev")
    bad = FakeClient({}, 0.0, fail=True, name="jev")
    fb = FakeClient({"claim_type": "hypothesis"}, 0.90, cost_usd=0.01, name="claude-haiku")
    r1 = cascade.decide(project, "claim_type", "C-001", {"text": "x"}, Q, hi, fb, 0.8)
    r2 = cascade.decide(project, "claim_type", "C-002", {"text": "y"}, Q, lo, fb, 0.8)
    r3 = cascade.decide(project, "claim_type", "C-003", {"text": "z"}, Q, bad, fb, 0.8)
    assert r1["record"]["route"] == "primary" and r1["answers"]["claim_type"]["answer"] == "fact"
    assert (r2["record"]["escalated"], r2["record"]["escalation_reason"]) == (True, "low_confidence")
    assert r2["record"]["cost_usd"] == pytest.approx(0.011)
    assert r3["record"]["escalation_reason"] == "error" and r3["answers"]["claim_type"]["answer"] == "hypothesis"
    assert len(state(root, project, "routing")) == 3
    with pytest.raises(CliError):
        cascade.decide(project, "claim_type", "C-004", {}, Q, bad, FakeClient({}, 0, fail=True), 0.8)


def test_correct_and_stats(cli, project, root):
    hi = FakeClient({"claim_type": "fact"}, 0.95, name="jev")
    fb = FakeClient({"claim_type": "fact"}, 0.9, name="claude-haiku")
    for i in range(4):
        cascade.decide(project, "claim_type", f"C-00{i}", {}, Q, hi, fb, 0.8)
    assert cli("route", "correct", "R-001", "--answer", "hypothesis", "--reason", "это предположение")[0] == 0
    s = cli("route", "stats")[1]["data"]
    row = s["claim_type"] if isinstance(s, dict) else [x for x in s if x["task"] == "claim_type"][0]
    assert row["n"] == 4 and row["error_rate"] == pytest.approx(0.25) and row["escalation_rate"] == 0


def _hook(name, payload, root, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k != "STRATEG_DEV"}
    env.update({"STRATEG_ROOT": str(root), **(extra_env or {})})
    return subprocess.run([sys.executable, str(HOOKS / f"{name}.py")], input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True, env=env, timeout=10)


def test_session_start(cli, root):
    r = _hook("session_start", {"session_id": "s1", "cwd": str(root), "source": "startup"}, root)
    assert r.returncode == 0 and "Активного проекта нет" in r.stdout
    cli("project", "new", "h-proj", "--title", "Хуки")
    r = _hook("session_start", {"session_id": "s2", "cwd": str(root), "source": "resume"}, root)
    assert r.returncode == 0 and "Постановка задачи" in r.stdout and len(r.stdout.splitlines()) <= 40
    assert any(e["kind"] == "session_start" and e["data"]["session_id"] == "s2" for e in state(root, "h-proj", "journal"))


def test_pre_tool_guard(cli, root):
    cli("project", "new", "h-proj", "--title", "Хуки")
    blocked = [
        {"tool_name": "Edit", "tool_input": {"file_path": str(root / "CLAUDE.md"), "new_string": "x"}},
        {"tool_name": "Write", "tool_input": {"file_path": str(root / "knowledge" / "m.md"), "content": "x"}},
        {"tool_name": "Write", "tool_input": {"file_path": str(root / "projects/h-proj/state/claims.jsonl"), "content": "{}"}},
        {"tool_name": "Write", "tool_input": {"file_path": str(root / "notes.md"), "content": "key sk-ant-" + "Ab1" * 10}},
        {"tool_name": "WebFetch", "tool_input": {"url": "http://wiki.corp/plan", "prompt": "x"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf projects/h-proj"}},
    ]
    for p in blocked:
        r = _hook("pre_tool_guard", {"hook_event_name": "PreToolUse", **p}, root)
        assert r.returncode == 2 and r.stderr.strip(), p
    doc = str(root / "projects/h-proj/docs/situation.md")
    ok = {"tool_name": "Write", "tool_input": {"file_path": doc, "content": "## Что известно"}}
    assert _hook("pre_tool_guard", {"hook_event_name": "PreToolUse", **ok}, root).returncode == 0
    dev = {"tool_name": "Edit", "tool_input": {"file_path": str(root / "CLAUDE.md"), "new_string": "x"}}
    assert _hook("pre_tool_guard", {"hook_event_name": "PreToolUse", **dev}, root, {"STRATEG_DEV": "1"}).returncode == 0


def test_post_tool_log_and_stop(cli, root):
    cli("project", "new", "h-proj", "--title", "Хуки")
    _hook("session_start", {"session_id": "s1", "source": "startup"}, root)
    _hook("post_tool_log", {"hook_event_name": "PostToolUse", "tool_name": "WebFetch",
                            "tool_input": {"url": "https://example.org"}, "tool_response": {}}, root)
    _hook("post_tool_log", {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_input": {"file_path": "x"}}, root)
    _hook("post_tool_log", {"hook_event_name": "PostToolUseFailure", "tool_name": "WebFetch",
                            "tool_input": {"url": "https://down.example"}, "error": "timeout"}, root)
    ev = state(root, "h-proj", "journal")
    assert [e["kind"] for e in ev if e["kind"] in ("tool", "error")] == ["tool", "error"]
    assert "example.org" in [e for e in ev if e["kind"] == "tool"][0]["summary"]
    assert _hook("stop_check", {"hook_event_name": "Stop", "stop_hook_active": True}, root).returncode == 0
    # ворота S1 пройдены без документов этапа S0 → валидатор находит ошибки → стоп блокируется
    cli("project", "gate", "G1", "--status", "approved", "--note", "ok")
    cli("project", "stage", "S1")
    r = _hook("stop_check", {"hook_event_name": "Stop", "stop_hook_active": False}, root)
    assert r.returncode == 2 and "V07" in r.stderr
    assert any(e["kind"] == "stop" for e in state(root, "h-proj", "journal"))


def test_doctor(cli):
    code, r = cli("doctor")
    checks = {c["check"]: c for c in (r.get("data") or {}).get("checks", [])}
    assert checks, r
    assert all(c["status"] in ("ok", "warn", "fail") and "fix" in c for c in checks.values())
    assert any("Python" in k for k in checks)
