"""Исправления по первому демо-прогону."""
import shutil

from tests.conftest import FIX, advance, state
from tests.contract.test_t13_t15_route_hooks_doctor import _hook


def test_dataset_snapshot_is_summary(cli, project, root):
    f = root / "profile.csv"
    shutil.copy(FIX / "data" / "profile.csv", f)
    code, r = cli("source", "add", "--file", f)
    assert code == 0
    snap = (root / "projects" / project / r["data"]["snapshot"]).read_text(encoding="utf-8")
    assert "Строк: 6, колонок: 5" in snap and "strateg data profile" in snap
    assert state(root, project, "sources")[0]["kind"] == "dataset"


def test_session_attached_on_first_tool(cli, root):
    cli("project", "new", "h-proj", "--title", "Хуки")
    for _ in range(2):
        _hook("post_tool_log", {"hook_event_name": "PostToolUse", "session_id": "sess-late", "tool_name": "Bash",
                                "tool_input": {"command": "ls"}}, root)
    starts = [e for e in state(root, "h-proj", "journal") if e["kind"] == "session_start"]
    assert len(starts) == 1 and starts[0]["data"]["session_id"] == "sess-late"


def test_kb_ignores_template_hints(cli, project):
    hits = cli("kb", "search", "список каналов узнать понять", "--scope", "all")[1]["data"]
    assert hits and all(h["kind"] == "knowledge" and "templates" not in h["ref"] for h in hits)


def test_v08_ignores_untouched_templates(cli, project, root):
    advance(cli, "S1")
    warns = [x for x in cli("validate")[1]["data"]["checks"] if x["check"] == "V08" and x["level"] == "warn"]
    assert not any(x["ref"] in ("options.md", "strategy_product.md", "strategy_comms.md") for x in warns)


def test_g3_opinion_recorded_before_recommendation(cli, project, root):
    advance(cli, "S2")
    assert cli("project", "gate", "G3", "--status", "opinion")[0] == 2
    code, _ = cli("project", "gate", "G3", "--status", "opinion", "--note", "Откатил бы v2")
    assert code == 0
    st = cli("project", "status")[1]["data"]
    assert st["gates"]["G3"] == "pending" and st["opinions"]["G3"] == "Откатил бы v2"
    cli("project", "gate", "G3", "--status", "approved", "--note", "O-003")
    assert not any(x["check"] == "V14" for x in cli("validate")[1]["data"]["checks"])


def test_guard_blocks_code_edits_via_bash_and_edit(root):
    import os

    from strateg import hooks
    os.environ.pop("STRATEG_DEV", None)
    blocked = ["sed -i '' 's/a/b/' strateg/cmd/validate.py",
               "python3 -c \"open('strateg/lib/store.py','w').write('')\"",
               "echo x >> projects/demo/state/claims.jsonl",
               "cp /tmp/x tests/conftest.py"]
    allowed = ["sed -n 1,20p strateg/cmd/validate.py", "grep -n V06 strateg/cmd/validate.py 2>&1 | head",
               ".venv/bin/python -m strateg validate > /dev/null", "cat CLAUDE.md 2>/dev/null",
               "cat > projects/demo/out/analysis.py <<'X'\nprint(1)\nX"]
    for cmd in blocked:
        assert hooks.pre_tool_guard({"tool_name": "Bash", "tool_input": {"command": cmd}})[0] == 2, cmd
    for cmd in allowed:
        assert hooks.pre_tool_guard({"tool_name": "Bash", "tool_input": {"command": cmd}})[0] == 0, cmd
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(root / "strateg" / "cmd" / "validate.py"), "new_string": "x"}}
    assert hooks.pre_tool_guard(edit)[0] == 2


def test_source_add_file_already_in_inbox_relative(cli, project, root, monkeypatch):
    inbox = root / "projects" / project / "materials" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / "data" / "profile.csv", inbox / "p.csv")
    monkeypatch.chdir(root)
    code, r = cli("source", "add", "--file", f"projects/{project}/materials/inbox/p.csv")
    assert code == 0 and state(root, project, "sources")[0]["file"] == "materials/inbox/p.csv"


def test_review_future_metric_trigger_and_clear_flag(cli, project, monkeypatch):
    cli("claim", "add", "--type", "hypothesis", "--text", "H")
    cli("option", "add", "--title", "Изменить", "--kind", "change", "--summary", "s", "--based-on", "C-001")
    cli("decision", "add", "--option", "O-001", "--rationale", "r", "--owner", "РП", "--by", "РП",
        "--metric", "удержание|53|62|2027-02-15", "--trigger", "metric:отмены выше 35% на 10.01.2099",
        "--trigger", "metric:жалобы выросли")
    trig = cli("review", "--today", "2026-11-11")[1]["data"]["triggered"]
    assert [t["value"] for t in trig] == ["жалобы выросли"]
    cli("claim", "update", "C-001", "--text", "H2", "--reason", "новые данные")
    cli("impact", "--changed", "C-001", "--apply")
    assert any(n["id"] == "O-001" for n in cli("review")[1]["data"]["needs_review"])
    assert cli("project", "status")[1]["data"]["needs_review"] == len(cli("review")[1]["data"]["needs_review"]) > 0
    cli("option", "set", "O-001", "--status", "active", "--reason", "пересмотрен: вывод не меняется")
    assert not any(n["id"] == "O-001" for n in cli("review")[1]["data"]["needs_review"])
    assert cli("project", "status")[1]["data"]["needs_review"] == len(cli("review")[1]["data"]["needs_review"])
