#!/usr/bin/env python3
from __future__ import annotations
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
REPO_DIR = Path(os.getenv("AUTOCOMMIT_REPO_DIR", str(Path.home() / "auto")))
COMMIT_MSG = os.getenv("AUTOCOMMIT_MSG", "\U0001f916 autocommit: script heartbeat")
BRANCH = os.getenv("AUTOCOMMIT_BRANCH", "main")
REMOTE_NAME = os.getenv("AUTOCOMMIT_REMOTE", "origin")
REMOTE_URL = os.getenv("AUTOCOMMIT_REMOTE_URL", "https://github.com/Tony46117/auto.git")
INTERVAL_SEC = int(os.getenv("AUTOCOMMIT_INTERVAL", "120"))
TOKEN_ENV_KEYS = ("AUTOCOMMIT_GIT_TOKEN", "GITHUB_TOKEN")
TOKEN_FILE_CANDIDATES = (
    Path.home() / "apis" / "apis.txt",
    Path(__file__).resolve().parent / "apis" / "apis.txt",
    Path(__file__).resolve().parent / "apis.txt",
    Path.home() / "Documents" / "DETAIL" / "apis.txt",
)
TOKEN_FILE_RE = re.compile(r"ghp_[A-Za-z0-9]{20,}")
STAMP_MARKER = "# >>> AUTOCOMMIT-HEARTBEAT >>>"
STAMP_END = "# <<< AUTOCOMMIT-HEARTBEAT <<<"
STAMP_BLOCK_RE = re.compile(
    rf"^{re.escape(STAMP_MARKER)}$.*?^{re.escape(STAMP_END)}$",
    re.DOTALL | re.MULTILINE,
)
_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "echo",
    "GCM_INTERACTIVE": "never",
}
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def _stamp_block() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"\n{STAMP_MARKER}\n# last-run-utc = {stamp}\n{STAMP_END}\n"
def load_token() -> str:
    for key in TOKEN_ENV_KEYS:
        value = os.getenv(key, "").strip()
        if value:
            return value
    for candidate in TOKEN_FILE_CANDIDATES:
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace")
            match = TOKEN_FILE_RE.search(text)
            if match:
                return match.group(0)
    raise FileNotFoundError(
        "No GitHub token found: set AUTOCOMMIT_GIT_TOKEN or GITHUB_TOKEN, "
        "or place a file containing ghp_... at one of: "
        + ", ".join(str(c) for c in TOKEN_FILE_CANDIDATES)
    )
def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        check=check,
    )
def _ensure_repo(repo: Path) -> None:
    if not (repo / ".git").is_dir():
        print(f"[{_now()}] Initialising git repo in {repo}")
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init")
        _git(repo, "checkout", "-b", BRANCH)
        if REMOTE_URL:
            try:
                _git(repo, "remote", "add", REMOTE_NAME, REMOTE_URL)
            except subprocess.CalledProcessError:
                _git(repo, "remote", "set-url", REMOTE_NAME, REMOTE_URL)
    _git(repo, "config", "user.email", "toxicmuchacho@gmail.com")
    _git(repo, "config", "user.name", "Antony Gitau Kihara")
def _sync_with_remote(repo: Path) -> None:
    try:
        _git(repo, "fetch", REMOTE_NAME)
    except subprocess.CalledProcessError as exc:
        print(f"[{_now()}] fetch failed (offline?): {exc.stderr.strip()}")
        return
    head = f"{REMOTE_NAME}/{BRANCH}"
    exists = _git(repo, "rev-parse", "--verify", "--quiet", head, check=False)
    if exists.returncode == 0:
        reset = _git(repo, "reset", "--hard", head, check=False)
        if reset.returncode != 0:
            print(f"[{_now()}] reset failed: {reset.stderr.strip()}")
    else:
        print(f"[{_now()}] remote branch {head} not found; starting fresh history")
def _stamp_repo_copy(repo_copy: Path) -> bool:
    text = repo_copy.read_text(encoding="utf-8")
    replacement = _stamp_block().rstrip("\n")
    if STAMP_MARKER in text:
        new_text, count = STAMP_BLOCK_RE.subn(replacement, text, count=1)
        if count == 1:
            if new_text == text:
                return False
            repo_copy.write_text(new_text, encoding="utf-8")
            return True
    if not text.endswith("\n"):
        text += "\n"
    repo_copy.write_text(text + _stamp_block(), encoding="utf-8")
    return True
def _copy_runner(repo: Path, runner_path: Path) -> bool:
    repo_copy = repo / "autocommit.py"
    if runner_path.resolve() != repo_copy.resolve():
        shutil.copy(runner_path, repo_copy)
    return _stamp_repo_copy(repo_copy)
def _commit_and_push(repo: Path, runner_path: Path) -> bool:
    _sync_with_remote(repo)
    changed = _copy_runner(repo, runner_path)
    _git(repo, "add", "-A")
    status = _git(repo, "status", "--porcelain")
    if not status.stdout.strip():
        return False
    if not changed:
        print(f"[{_now()}] skipping commit: no heartbeat change (staying in sync)")
        return False
    _git(repo, "commit", "-m", COMMIT_MSG)
    print(f"[{_now()}] committed: {COMMIT_MSG}")
    push = _git(repo, "push", REMOTE_NAME, BRANCH, check=False)
    if push.returncode != 0:
        print(f"[{_now()}] push failed: {push.stderr.strip()}")
        return False
    print(f"[{_now()}] pushed to {REMOTE_NAME}/{BRANCH}")
    return True
_shutdown = False
def _handle_signal(signum, frame) -> None:
    global _shutdown
    _shutdown = True
    print(f"\n[{_now()}] shutdown signal received, finishing cycle...")
def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        load_token()
    except FileNotFoundError as exc:
        print(f"[{_now()}] FATAL: {exc}")
        return 1
    repo = REPO_DIR
    runner_path = Path(__file__).resolve()
    print(f"[{_now()}] autocommit starting — repo={repo}, interval={INTERVAL_SEC}s")
    print(f"[{_now()}] remote={REMOTE_URL}")
    print(f"[{_now()}] token sourced from env or token file (never hard-coded)")
    print(f"[{_now()}] press Ctrl+C to stop")
    try:
        while not _shutdown:
            try:
                _ensure_repo(repo)
                _commit_and_push(repo, runner_path)
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"")
                print(f"[{_now()}] git command failed: {exc.cmd}")
                if stderr:
                    print(f"[{_now()}] stderr: {stderr}")
            except Exception as exc:
                print(f"[{_now()}] ERROR: {exc}")
            if not _shutdown:
                for _ in range(INTERVAL_SEC):
                    if _shutdown:
                        break
                    time.sleep(1)
    finally:
        print(f"[{_now()}] autocommit stopped")
    return 0
if __name__ == "__main__":
    sys.exit(main())











































































# >>> AUTOCOMMIT-HEARTBEAT >>>
# last-run-utc = 2026-09-22T09:41:01Z
# <<< AUTOCOMMIT-HEARTBEAT <<<
