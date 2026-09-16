#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from github import Github, GithubException
__all__ = ["main"]
COMMIT_MESSAGE = "chore: strip comments (automated)"
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".ogg",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
    ".pyc", ".pyo", ".class", ".jar", ".lock",
    ".min.js", ".min.css",
}
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", ".next", ".nuxt", "target", "vendor", "bower_components",
    ".idea", ".vscode", ".gradle", ".mvn",
}
CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".sh", ".bash", ".zsh", ".pl", ".lua", ".r", ".m", ".mm",
    ".css", ".scss", ".sass", ".less",
    ".html", ".htm", ".xml",
    ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg",
}
PROTECTED_PATTERNS = [
    re.compile(r"^#!"),
    re.compile(r"coding[:=]\s*[-\w.]+"),
    re.compile(r"^\s*#\s*(noqa|type:\s*ignore|pylint:|flake8:|mypy:)"),
    re.compile(r"^\s*//\s*(eslint-disable|@ts-ignore|@ts-expect-error|prettier-ignore)"),
    re.compile(r"^\s*<!--\s*(license|licence|copyright)", re.I),
]
TOKEN = None
def load_token() -> str:
    global TOKEN
    env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env_token:
        TOKEN = env_token
        return TOKEN
    apis_path = Path(__file__).resolve().parent / "apis.txt"
    if not apis_path.exists():
        apis_path = Path.home() / "Documents" / "DETAIL" / "apis.txt"
    if not apis_path.exists():
        apis_path = Path.home() / ".config" / "apis.txt"
    if apis_path.exists():
        for line in apis_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("github-token"):
                TOKEN = line.split("=", 1)[1].strip()
                break
    if not TOKEN:
        print("ERROR: no GitHub token found in GITHUB_TOKEN env var or apis.txt")
        sys.exit(1)
    return TOKEN
def setup_git_credential(token: str, repo_dir: Path) -> None:
    cred_file = Path.home() / ".git-credentials"
    entry = f"https://x-access-token:{token}@github.com"
    existing = cred_file.read_text().splitlines() if cred_file.exists() else []
    if entry not in existing:
        existing.append(entry)
        cred_file.write_text("\n".join(existing) + "\n")
    cred_file.chmod(0o600)
def run(cmd, cwd=None, check=True, capture=True):
    return subprocess.run(
        cmd, cwd=cwd, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
def is_probably_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
    except Exception:
        return True
    if b"\x00" in chunk:
        return True
    return False
def is_protected(line: str) -> bool:
    return any(p.search(line) for p in PROTECTED_PATTERNS)
def _strip_hash_comment(line: str) -> str:
    in_s = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_s:
            if ch == "\\":
                i += 2
                continue
            if ch == in_s:
                in_s = None
        else:
            if ch in ("'", '"'):
                in_s = ch
            elif ch == "#":
                return line[:i]
        i += 1
    return line
def strip_python(text: str) -> str:
    out_lines = []
    in_triple = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if in_triple:
            if in_triple in line:
                in_triple = None
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) >= 2 and len(stripped) > 3:
                continue
            in_triple = quote
            continue
        if is_protected(line):
            out_lines.append(line)
            continue
        new_line = _strip_hash_comment(line)
        if new_line.strip():
            out_lines.append(new_line.rstrip())
    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")
def strip_slash_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_s = None
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_s:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if ch == in_s:
                in_s = None
            i += 1
            continue
        if ch == "/" and nxt == "/":
            eol = text.find("\n", i)
            if eol == -1:
                eol = n
            comment_line = text[i:eol]
            if any(p.search(comment_line) for p in PROTECTED_PATTERNS):
                out.append(comment_line)
            i = eol
            continue
        if ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                break
            out.append(" ")
            i = end + 2
            continue
        if ch in ("'", '"', "`"):
            in_s = ch
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    result = "".join(out)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result
def strip_html_xml(text: str) -> str:
    return re.sub(r"<!--(?!\[if).*?-->", "", text, flags=re.DOTALL)
def strip_sql(text: str) -> str:
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text
def strip_shell(text: str) -> str:
    out = []
    for line in text.splitlines():
        if is_protected(line):
            out.append(line); continue
        s = line.lstrip()
        if s.startswith("#"):
            continue
        out.append(_strip_hash_comment(line).rstrip())
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")
def strip_file(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext not in CODE_EXTENSIONS:
        return False
    if is_probably_binary(path):
        return False
    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    if ext == ".py":
        new = strip_python(original)
    elif ext in {".sh", ".bash", ".zsh", ".pl", ".r", ".yaml", ".yml",
                  ".toml", ".ini", ".cfg", ".rb"}:
        new = strip_shell(original)
    elif ext in {".html", ".htm", ".xml"}:
        new = strip_html_xml(original)
    elif ext == ".sql":
        new = strip_sql(original)
    else:
        new = strip_slash_comments(original)
    if new != original:
        path.write_text(new, encoding="utf-8")
        return True
    return False
def process_repo_dir(root: Path) -> int:
    changed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            p = Path(dirpath) / fname
            try:
                if strip_file(p):
                    changed += 1
            except Exception as e:
                print(f"    ! error on {p}: {e}")
    return changed
def clone_repo(clone_url: str, dest: Path, token: str) -> None:
    setup_git_credential(token, dest)
    run(["git", "clone", "--depth", "1", clone_url, str(dest)])
def commit_and_push(repo_dir: Path, branch: str, token: str) -> bool:
    run(["git", "config", "user.email", "bot@example.com"], cwd=repo_dir)
    run(["git", "config", "user.name", "Comment Stripper Bot"], cwd=repo_dir)
    run(["git", "add", "-A"], cwd=repo_dir)
    diff = run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir, check=False)
    if diff.returncode == 0:
        return False
    run(["git", "commit", "-m", COMMIT_MESSAGE], cwd=repo_dir)
    run(["git", "push", "--force-with-lease", "origin", branch], cwd=repo_dir)
    return True
def strip_repo(repo_name: str, repo_clone_url: str, branch: str, token: str) -> bool:
    workdir = Path(tempfile.mkdtemp(prefix="strip_comments_"))
    dest = workdir / repo_name
    try:
        print(f"    cloning {repo_name} ...")
        clone_repo(repo_clone_url, dest, token)
        changed = process_repo_dir(dest)
        if changed == 0:
            print(f"    no comments removed")
            return False
        print(f"    {changed} files modified, committing ...")
        pushed = commit_and_push(dest, branch, token)
        print(f"    pushed={pushed}")
        return pushed
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
def main() -> int:
    ap = argparse.ArgumentParser(prog="striper.py",
                                  description="strip comments from GitHub repos")
    ap.add_argument("--repo", default=None,
                    help="target a specific repo (e.g. Tony46117/auto)")
    ap.add_argument("--dry-run", action="store_true",
                    help="clone and strip but do not push")
    args = ap.parse_args()
    token = load_token()
    print(f"Authenticated with token: {token[:6]}...{token[-4:]}")
    g = Github(token)
    user = g.get_user()
    print(f"Authenticated as: {user.login}\n")
    if args.repo:
        repos = [g.get_repo(args.repo)]
    else:
        repos = list(user.get_repos())
    print(f"Targeting {len(repos)} repository/repositories.\n")
    workdir = Path(tempfile.mkdtemp(prefix="strip_comments_"))
    try:
        for repo in repos:
            name = repo.full_name if hasattr(repo, "full_name") else repo.name
            print(f"==> {name}")
            if args.repo:
                if repo.archived:
                    print("    skipped (archived)\n")
                    continue
                repo_obj = repo
            else:
                if repo.archived:
                    print("    skipped (archived)\n")
                    continue
                repo_obj = repo
            try:
                branch = repo_obj.default_branch
                clone_url = repo_obj.clone_url.replace(
                    "https://", f"https://x-access-token:{token}@"
                )
                changed = strip_repo(name, clone_url, branch, token)
                if not changed:
                    print(f"    no changes\n")
                print()
            except GithubException as e:
                print(f"    GitHub error: {e}\n")
            except subprocess.CalledProcessError as e:
                print(f"    git error: {e.stderr or e}\n")
            except Exception:
                print("    unexpected error:")
                traceback.print_exc()
                print()
            if args.dry_run:
                break
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        print("Done.")
    return 0
if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Fatal: {e}")
        sys.exit(1)
