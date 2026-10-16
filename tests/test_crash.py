"""Crash logging (livereact/crash.py), each case in a child interpreter so the
hooks and faulthandler it arms never touch pytest's own."""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _run(code: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=60)


def _crash_files(cwd: Path) -> list[str]:
    return glob.glob(str(cwd / "logs" / "crash-*.log"))


def test_a_segfault_leaves_every_threads_stack_in_the_crash_log(tmp_path):
    proc = _run("from livereact import crash; crash.install('logs'); "
                "import faulthandler; faulthandler._sigsegv()", tmp_path)
    assert proc.returncode != 0
    [path] = _crash_files(tmp_path)
    text = Path(path).read_text()
    assert "Segmentation fault" in text
    assert "most recent call first" in text


def test_an_uncaught_thread_exception_is_kept(tmp_path):
    proc = _run("from livereact import crash; crash.install('logs')\n"
                "import threading\n"
                "def boom(): raise ValueError('engine blew up')\n"
                "t = threading.Thread(target=boom, name='show-engine'); t.start(); t.join()\n", tmp_path)
    assert proc.returncode == 0
    [path] = _crash_files(tmp_path)
    text = Path(path).read_text()
    assert "Uncaught exception in thread show-engine" in text
    assert "ValueError: engine blew up" in text


def test_a_clean_exit_removes_its_empty_crash_log(tmp_path):
    proc = _run("from livereact import crash; crash.install('logs')", tmp_path)
    assert proc.returncode == 0
    assert _crash_files(tmp_path) == []


def test_a_demo_run_arms_the_crash_log_and_cleans_up(tmp_path):
    proc = _run("from livereact.__main__ import main; "
                "raise SystemExit(main(['--demo', '--duration', '0.5', '--log-level', 'INFO']))", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "Crash log armed" in proc.stderr
    assert _crash_files(tmp_path) == []


def test_python_314_gets_a_warning(monkeypatch):
    from livereact import crash

    monkeypatch.setattr(sys, "version_info", (3, 14, 0, "final", 0))
    assert "3.13" in crash.python_warning()
    monkeypatch.setattr(sys, "version_info", (3, 13, 9, "final", 0))
    assert crash.python_warning() is None
