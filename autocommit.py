#!/usr/bin/env python3
"""
Autocommit script — commits and pushes itself every 2 minutes
to a designated git repository.

Design notes:
- The real GitHub token is read from apis.txt (or an env var) at runtime
  and used to set the push remote URL. The raw token is never written into
  the script itself or into any committed file.
- Each run copies the current runner into the target repo and then makes one
  small, safe, deterministic edit to that copied script so the repo always has
  something new to commit. The edit is only to a private metadata block at the
  bottom of the file, so the functional parts of the script are not mangled.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration — read from environment (preferred) or fallback files
# ---------------------------------------------------------------------------
REPO_DIR       = os.getenv("AUTOCOMMIT_REPO_DIR", str(Path.home() / "auto-repo"))
COMMIT_MSG     = os.getenv(
    "AUTOCOMMIT_MSG",
    "🤖 autocommit: script heartbeat"
)
BRANCH         = os.getenv("AUTOCOMMIT_BRANCH", "main")
REMOTE_NAME    = os.getenv("AUTOCOMMIT_REMOTE", "origin")
REMOTE_URL     = "https://github.com/Tony46117/auto.git"
INTERVAL_SEC   = int(os.getenv("AUTOCOMMIT_INTERVAL", "120"))  # 2 minutes
GIT_TOKEN      = None  # set lazily in main()

# ---------------------------------------------------------------------------
# Private token chain used only for auth, never written back into script
# ---------------------------------------------------------------------------
TOKEN_STORE_ENV = "AUTOCOMMIT_GIT_TOKEN"
STAMP_MARKER    = "# >>> AUTOCOMMIT-HEARTBEAT >>>"


def _token_source_key() -> str:
    """Stable placeholder used in the git remote URL instead of the token."""
    return "x-access-token"


def _load_token_from_file() -> str:
    """Fallback: read GitHub token from apis.txt-style file."""
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


def _tokenised_remote_url(token: str) -> str:
    """Return a push URL that embeds the token once in git config only."""
    base = REMOTE_URL
    if not base.startswith("https://"):
        raise ValueError(f"REMOTE_URL must start with https://, got {base!r}")
    return base.replace(
        "https://",
        f"https://{_token_source_key()}:{token}@",
        1,
    )


def _ensure_remote(repo: Path, token: str) -> None:
    """Set the push remote URL with the token embedded in git config only.

    The raw token is not stored in this script or in any committed file.
    It lives only in the local repo's git config and in memory while running.
    """
    remote_url_with_token = _tokenised_remote_url(token)
    try:
        subprocess.run(
            ["git", "remote", "set-url", REMOTE_NAME, remote_url_with_token],
            cwd=repo, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "remote", "add", REMOTE_NAME, remote_url_with_token],
            cwd=repo, check=True, capture_output=True,
        )


def _repo_autocommit_path(repo: Path) -> Path:
    return repo / "autocommit.py"


def _stamp_repo_copy(repo_copy: Path, token: str) -> None:
    """Rewrite a small, private metadata block at the end of the repo copy.

    The rest of the file is left untouched. This is what guarantees that there
    is always a new commit without changing the script's behavior.
    """
    text = repo_copy.read_text(encoding="utf-8")
    if STAMP_MARKER in text:
        pattern = re.compile(
            rf"^({re.escape(STAMP_MARKER)}.*?)$",
            re.DOTALL | re.MULTILINE,
        )
        replacement = _stamp_block(token)
        new_text, n = pattern.subn(replacement, text, count=1)
        if n == 1 and new_text != text:
            repo_copy.write_text(new_text, encoding="utf-8")
            return
    # Append block if missing entirely
    if not text.endswith("\n"):
        text += "\n"
    repo_copy.write_text(text + _stamp_block(token), encoding="utf-8")


def _stamp_block(token: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return (
        "\n"
        + STAMP_MARKER + "\n"
        + f"# last-run-utc = {now}\n"
        + f"# token-hash  = {digest}\n"
        + "# <<< AUTOCOMMIT-HEARTBEAT <<<\n"
    )


def _commit_and_push(repo: Path, token: str, runner_path: Path) -> None:
    """Stage all changes in the repo and push the current branch.

    Each run copies the current runner into the target repo and then makes one
    small, safe metadata edit to that copy so the repo always has something new
    to commit. The edit is only to the AUTOCOMMIT-HEARTBEAT block.
    """
    _ensure_remote(repo, token)

    repo_copy = _repo_autocommit_path(repo)
    shutil.copy(runner_path, repo_copy)

    # Tiny safe mutation: rewrite only the private heartbeat block
    _stamp_repo_copy(repo_copy, token)

    # Stage everything
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    # Only commit if there's something to commit
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        print(f"[{_now()}] Nothing to commit, skipping.")
        return

    # Commit
    subprocess.run(
        ["git", "commit", "-m", COMMIT_MSG],
        cwd=repo, check=True,
    )
    print(f"[{_now()}] Committed: {COMMIT_MSG}")

    # Push
    subprocess.run(
        ["git", "push", REMOTE_NAME, BRANCH],
        cwd=repo, check=True,
    )
    print(f"[{_now()}] Pushed to {REMOTE_NAME}/{BRANCH}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
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

    while True:
        try:
            if not (repo_path / ".git").exists():
                print(f"[{_now()}] Initialising git repo in {repo_path}")
                subprocess.run(["git", "init"], cwd=repo_path, check=True)
                subprocess.run(
                    ["git", "branch", "-m", BRANCH],
                    cwd=repo_path, check=True,
                )
                # First-time author config (adjust as needed)
                subprocess.run(
                    ["git", "config", "user.email", "toxicmuchacho@gmail.com"],
                    cwd=repo_path, check=True,
                )
                subprocess.run(
                    ["git", "config", "user.name", "Antony Gitau Kihara"],
                    cwd=repo_path, check=True,
                )
            _commit_and_push(repo_path, GIT_TOKEN, runner_path)
        except Exception as exc:
            print(f"[{_now()}] ERROR: {exc}")

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()

# >>> AUTOCOMMIT-HEARTBEAT >>>
# last-run-utc = 2026-09-11T10:17:58Z
# token-hash  = 78fa6dab71eeb8eb
# <<< AUTOCOMMIT-HEARTBEAT <<<
