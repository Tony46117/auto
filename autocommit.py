#!/usr/bin/env python3
from __future__ import annotations
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
REPO_DIR       = os.getenv("AUTOCOMMIT_REPO_DIR", str(Path.home() / "auto-repo"))
COMMIT_MSG     = os.getenv(
    "AUTOCOMMIT_MSG",
    "autocommit: script heartbeat"
)
BRANCH         = os.getenv("AUTOCOMMIT_BRANCH", "main")
REMOTE_NAME    = os.getenv("AUTOCOMMIT_REMOTE", "origin")
REMOTE_URL     = "https://github.com/Tony46117/auto.git"
INTERVAL_SEC   = int(os.getenv("AUTOCOMMIT_INTERVAL", "120"))
GIT_TOKEN      = None
TOKEN_STORE_ENV = "AUTOCOMMIT_GIT_TOKEN"
STAMP_MARKER    = "# >>> AUTOCOMMIT-HEARTBEAT >>>"
CLOSE_MARKER    = "# <<< AUTOCOMMIT-HEARTBEAT <<<"
def _token_source_key() -> str:
    return "x-access-token"
def _load_token_from_file() -> str:
    apis_path = Path(__file__).resolve().parent / "apis.txt"
    if not apis_path.exists():
        apis_path = Path.home() / "Documents" / "DETAIL" / "apis.txt"
    if not apis_path.exists():
        raise FileNotFoundError(
            "GITHUB_TOKEN env var not set and apis.txt not found. "
            "Set GITHUB_TOKEN or place apis.txt next to this script."
        )
    for line in apis_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("github-token"):
            return line.split("=", 1)[1].strip()
    raise ValueError("github-token not found in apis.txt")
def _store_credential(token: str) -> None:
    cred_file = Path.home() / ".git-credentials"
    entry = f"https://{_token_source_key()}:{token}@github.com"
    existing = cred_file.read_text().splitlines() if cred_file.exists() else []
    if entry not in existing:
        existing.append(entry)
        cred_file.write_text("\n".join(existing) + "\n")
    cred_file.chmod(0o600)
def _ensure_remote(repo: Path, token: str) -> None:
    try:
        subprocess.run(
            ["git", "remote", "set-url", REMOTE_NAME, REMOTE_URL],
            cwd=repo, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "remote", "add", REMOTE_NAME, REMOTE_URL],
            cwd=repo, check=True, capture_output=True,
        )
    _store_credential(token)
def _repo_autocommit_path(repo: Path) -> Path:
    return repo / "autocommit.py"
def _stamp_block() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        "\n"
        + STAMP_MARKER + "\n"
        + f"last-run-utc = {now}\n"
        + CLOSE_MARKER + "\n"
    )
def _stamp_repo_copy(repo_copy: Path) -> None:
    text = repo_copy.read_text(encoding="utf-8")
    if STAMP_MARKER in text:
        pattern = re.compile(
            rf"^{re.escape(STAMP_MARKER)}$.*?^{re.escape(CLOSE_MARKER)}$",
            re.DOTALL | re.MULTILINE,
        )
        replacement = _stamp_block().strip()
        new_text, n = pattern.subn(replacement, text, count=1)
        if n == 1 and new_text != text:
            repo_copy.write_text(new_text, encoding="utf-8")
            return
    if not text.endswith("\n"):
        text += "\n"
    repo_copy.write_text(text + _stamp_block(), encoding="utf-8")
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def _commit_and_push(repo: Path, token: str, runner_path: Path) -> None:
    _ensure_remote(repo, token)
    subprocess.run(["git", "fetch", REMOTE_NAME], cwd=repo, check=True)
    subprocess.run(["git", "reset", "--hard", f"{REMOTE_NAME}/{BRANCH}"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", BRANCH], cwd=repo, check=True)
    repo_copy = _repo_autocommit_path(repo)
    shutil.copy(runner_path, repo_copy)
    _stamp_repo_copy(repo_copy)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        print(f"[{_now()}] Nothing to commit, skipping.")
        return
    subprocess.run(
        ["git", "commit", "-m", COMMIT_MSG],
        cwd=repo, check=True,
    )
    print(f"[{_now()}] Committed: {COMMIT_MSG}")
    subprocess.run(
        ["git", "push", "--force-with-lease", REMOTE_NAME, BRANCH],
        cwd=repo, check=True,
    )
    print(f"[{_now()}] Pushed to {REMOTE_NAME}/{BRANCH}")
def main() -> None:
    global GIT_TOKEN
    if GIT_TOKEN is None:
        GIT_TOKEN = os.getenv(TOKEN_STORE_ENV) or _load_token_from_file()
    repo_path = Path(REPO_DIR)
    repo_path.mkdir(parents=True, exist_ok=True)
    runner_path = Path(__file__).resolve()
    print(f"[{_now()}] Autocommit starting — repo={repo_path}, interval={INTERVAL_SEC}s")
    print(f"[{_now()}] Target remote={REMOTE_NAME} {REMOTE_URL}")
    print(f"[{_now()}] Token sourced from env or apis.txt (not stored in script).")
    print(f"[{_now()}] Runner={runner_path}")
    print(f"[{_now()}] Press Ctrl+C to stop.")
    shutdown = False
    def _signal_handler(signum, frame):
        nonlocal shutdown
        print(f"\n[{_now()}] Shutdown signal received, finishing current cycle...")
        shutdown = True
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    while not shutdown:
        try:
            if not (repo_path / ".git").exists():
                print(f"[{_now()}] Initialising git repo in {repo_path}")
                subprocess.run(["git", "init"], cwd=repo_path, check=True)
                subprocess.run(
                    ["git", "branch", "-m", BRANCH],
                    cwd=repo_path, check=True,
                )
                subprocess.run(
                    ["git", "config", "user.email", "toxicmuchacho@gmail.com"],
                    cwd=repo_path, check=True,
                )
                subprocess.run(
                    ["git", "config", "user.name", "Antony Gitau Kihara"],
                    cwd=repo_path, check=True,
                )
            _commit_and_push(repo_path, GIT_TOKEN, runner_path)
        except subprocess.CalledProcessError as exc:
            print(f"[{_now()}] Git command failed: {exc}")
            if exc.stderr:
                print(f"[{_now()}] stderr: {exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr}")
        except Exception as exc:
            print(f"[{_now()}] ERROR: {exc}")
        if not shutdown:
            time.sleep(INTERVAL_SEC)
    print(f"[{_now()}] Autocommit stopped.")
if __name__ == "__main__":
    main()
last-run-utc = 2026-09-16T20:45:19Z
