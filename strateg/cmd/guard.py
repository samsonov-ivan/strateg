"""Сканеры внедрений и секретов, обезличивание. T04."""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
from collections.abc import Iterator
from functools import cache
from pathlib import Path

from strateg.lib import paths
from strateg.lib.out import CliError, Result


@cache
def _patterns(name: str, flags: int) -> list[tuple[str, re.Pattern]]:
    cfg = paths.load_config(name)
    return [(p["id"], re.compile(p["regex"], flags)) for p in cfg["patterns"]]


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def scan_injection(text: str) -> list[dict]:
    found = []
    for pid, rx in _patterns("injection_patterns", re.IGNORECASE | re.MULTILINE):
        for m in rx.finditer(text):
            s = max(0, m.start() - 20)
            excerpt = " ".join(text[s:m.end() + 40].split())[:120]
            found.append({"pattern_id": pid, "line": _line_of(text, m.start()), "excerpt": excerpt})
    return found


def scan_secrets(text: str) -> list[dict]:
    found = []
    for pid, rx in _patterns("secret_patterns", 0):
        for m in rx.finditer(text):
            v = m.group(0)
            found.append({"pattern_id": pid, "line": _line_of(text, m.start()), "excerpt_masked": v[:4] + "*" * (len(v) - 4)})
    return found


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)")
HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{3,}")
DOC = re.compile(r"(?<!\d)\d{4}\s?\d{6}(?!\d)")


def redact(text: str, names: list[str] | None = None) -> tuple[str, dict[str, int]]:
    counts = {"EMAIL": 0, "ТЕЛЕФОН": 0, "НИК": 0, "ДОКУМЕНТ": 0, "ИМЯ": 0}

    def sub(rx: re.Pattern, label: str, t: str) -> str:
        t, n = rx.subn(f"[{label}]", t)
        counts[label] += n
        return t

    text = sub(EMAIL, "EMAIL", text)
    text = sub(PHONE, "ТЕЛЕФОН", text)
    text = sub(HANDLE, "НИК", text)
    text = sub(DOC, "ДОКУМЕНТ", text)
    for i, name in enumerate([n.strip() for n in (names or []) if n.strip()], 1):
        parts = []
        for w in name.split():
            stem = w[: max(3, len(w) - 2)]
            parts.append(re.escape(stem) + r"\w*")
        rx = re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.IGNORECASE)
        text, n = rx.subn(f"[ИМЯ-{i}]", text)
        # отдельные части имени (фамилия длиннее 3 букв) тоже убираем
        for w in name.split():
            if len(w) > 3:
                rx1 = re.compile(r"\b" + re.escape(w[: max(3, len(w) - 2)]) + r"\w*\b", re.IGNORECASE)
                text, n1 = rx1.subn(f"[ИМЯ-{i}]", text)
                n += n1
        counts["ИМЯ"] += n
    return text, counts


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CliError("NOT_FOUND", f"Файл не найден: {path}") from None
    except (UnicodeDecodeError, OSError) as e:
        raise CliError("IO_ERROR", f"Не удалось прочитать {path}: {e}") from None


def cli_scan_injection(args: argparse.Namespace) -> Result:
    flags = scan_injection(_read(args.path))
    if flags:
        return Result({"flags": flags}, exit_code=1, message=f"Найдено подозрительных фрагментов: {len(flags)}")
    return Result({"flags": []})


def _git(*argv: str) -> str:
    try:
        return subprocess.run(["git", *argv], cwd=paths.code_dir(), capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise CliError("IO_ERROR", f"git недоступен: {e}") from None


def _ignored(rel: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) for g in globs) or rel.endswith(".env.example")


def _archive_files(root: Path, globs: list[str]) -> Iterator[Path]:
    def report_error(error: OSError) -> None:
        raise CliError("IO_ERROR", f"Не удалось прочитать каталог: {error.filename}") from None

    for current, dirs, files in os.walk(root, onerror=report_error):
        parent = Path(current)
        # В поставку не входят служебные данные Git и локальное окружение запуска.
        dirs[:] = [name for name in dirs if name not in {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
                   and not (parent / name / "pyvenv.cfg").is_file()
                   and not _ignored((parent / name).relative_to(root).as_posix() + "/", globs)]
        for name in files:
            candidate = parent / name
            if not candidate.is_symlink() and candidate.is_file():
                yield candidate


def cli_secrets(args: argparse.Namespace) -> Result:
    globs = paths.load_config("secret_patterns").get("ignore_paths", [])
    root = paths.code_dir()
    git_checkout = (root / ".git").exists()
    if (args.staged or args.history) and not git_checkout:
        raise CliError("IO_ERROR", "Для проверки индекса или истории нужна папка проекта с Git.")
    findings = []
    if args.history:
        cur = ""
        for line in _git("log", "-p", "--all", "--no-color").splitlines():
            if line.startswith("+++ b/"):
                cur = line[6:]
            if line.startswith("+") and not line.startswith("+++") and not _ignored(cur, globs):
                for f in scan_secrets(line):
                    findings.append({"file": cur, **f, "line": None})
        data = {"scope": "history", "findings": findings}
    else:
        if args.paths:
            scope = "paths"
            files = [Path(p) for p in args.paths]
        elif args.staged:
            scope = "staged_worktree"
            files = [root / p for p in _git("diff", "--cached", "--diff-filter=ACMRT", "--name-only", "-z").split("\0") if p]
        elif git_checkout:
            scope = "tracked"
            files = [root / p for p in _git("ls-files", "-z").split("\0") if p]
        else:
            scope = "archive"
            files = _archive_files(root, globs)
        scanned = 0
        binary = 0
        for f in files:
            try:
                rel = f.absolute().relative_to(root).as_posix()
            except ValueError:
                rel = str(f)
            if not args.paths and (_ignored(rel, globs) or f.is_symlink()):
                continue
            try:
                raw = f.read_bytes()
            except OSError as e:
                raise CliError("IO_ERROR", f"Не удалось прочитать файл: {rel} ({e.strerror})") from None
            if b"\x00" in raw[:4096]:
                binary += 1
                continue
            scanned += 1
            for x in scan_secrets(raw.decode("utf-8", errors="ignore")):
                findings.append({"file": rel, **x})
        data = {"scope": scope, "files_scanned": scanned, "binary_skipped": binary, "findings": findings}
    if findings:
        return Result(data, exit_code=1, message=f"Найдены возможные секреты: {len(findings)}")
    return Result(data)


def cli_redact(args: argparse.Namespace) -> Result:
    src = Path(args.path)
    text, counts = redact(_read(src), (args.names or "").split(",") if args.names else [])
    out = Path(args.out) if args.out else src.with_name(src.name + ".redacted.md")
    out.write_text(text, encoding="utf-8")
    return Result({"out": str(out), "replacements": counts})
