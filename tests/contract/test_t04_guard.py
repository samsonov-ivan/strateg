"""T04: сканеры и обезличивание."""
import re
import shutil

from strateg.cmd import guard
from tests.conftest import FIX


def test_scan_injection_finds_ru_and_en():
    flags = guard.scan_injection((FIX / "poisoned" / "page.html").read_text(encoding="utf-8"))
    ids = {f["pattern_id"] for f in flags}
    assert {"ignore_prev_ru", "ignore_prev_en"} <= ids
    assert all(len(f["excerpt"]) <= 120 and f["line"] >= 1 for f in flags)


def test_scan_injection_clean_text():
    assert guard.scan_injection((FIX / "snapshots" / "sample.html").read_text(encoding="utf-8")) == []


def test_scan_secrets_masks():
    text = (FIX / "secrets" / "leak.txt").read_text(encoding="utf-8")
    found = guard.scan_secrets(text)
    assert found and found[0]["pattern_id"] in {"anthropic", "generic_assignment"}
    key = re.search(r"sk-ant-\S+", text).group(0)
    assert all(key not in f["excerpt_masked"] for f in found)


def test_cli_secrets_exit_codes(cli, root):
    clean, leak = root / "clean.txt", root / "leak.txt"
    shutil.copy(FIX / "secrets" / "clean.txt", clean)
    shutil.copy(FIX / "secrets" / "leak.txt", leak)
    assert cli("guard", "secrets", clean)[0] == 0
    code, r = cli("guard", "secrets", leak)
    assert code == 1 and r["ok"] is False


def test_redact_removes_pii(cli, root):
    src = root / "interview.md"
    shutil.copy(FIX / "data" / "interview.md", src)
    code, r = cli("guard", "redact", src, "--names", "Иван Петров")
    assert code == 0
    out = (root / "interview.md.redacted.md").read_text(encoding="utf-8")
    assert "@example.com" not in out and "345-67-89" not in out and "345 67 89" not in out
    assert "Петров" not in out and "@ivanp" not in out and "123456" not in out
    assert "[EMAIL]" in out and "[ТЕЛЕФОН]" in out and "[ИМЯ-1]" in out
    assert r["data"]["replacements"]["ТЕЛЕФОН"] == 2


def test_cli_scan_injection(cli, root):
    f = root / "p.html"
    shutil.copy(FIX / "poisoned" / "page.html", f)
    assert cli("guard", "scan-injection", f)[0] == 1
