#!/usr/bin/env python3
"""
Autocommit script — commits and pushes itself every 5 minutes
to a designated git repository.
"""

import os
import subprocess
import time
from datetime import datetime
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


def _token_source_key() -> str:
    """Stable placeholder used in the git remote URL instead of the token."""
    return "x-access-token"


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

def _commit_and_push(repo: Path, token: str) -> None:
    """Stage all changes in the repo and push the current branch."""
    _ensure_remote(repo, token)

    # Copy self into the repo so it commits its own source
    import shutil
    shutil.copy(__file__, repo / "autocommit.py")

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

    print(f"[{_now()}] Autocommit starting — repo={repo_path}, interval={INTERVAL_SEC}s")
    print(f"[{_now()}] Target remote={REMOTE_NAME} {REMOTE_URL}")
    print(f"[{_now()}] Token sourced from env or apis.txt (not stored in script).")
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
                    ["git", "config", "user.email", "autocommit@local"],
                    cwd=repo_path, check=True,
                )
                subprocess.run(
                    ["git", "config", "user.name", "Autocommit Bot"],
                    cwd=repo_path, check=True,
                )
            _commit_and_push(repo_path, GIT_TOKEN)
        except Exception as exc:
            print(f"[{_now()}] ERROR: {exc}")

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
