"""Хук Claude Code: session_start. Логика — strateg/hooks.py. Вход — JSON в stdin."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_VENV = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if _VENV.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
    os.execv(str(_VENV), [str(_VENV), __file__])  # зависимости стоят в .venv


def main() -> int:
    try:
        from strateg.hooks import session_start

        payload = json.loads(sys.stdin.read() or "{}")
        code, out, err = session_start(payload)
    except Exception as e:  # хук не должен ломать сессию
        print(f"strateg hook session_start: {e}", file=sys.stderr)
        return 0
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
