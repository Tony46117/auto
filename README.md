# auto

A tiny self-updating heartbeat repository: a Python script commits and pushes
itself to GitHub every 2 minutes, proving the repo, its token, and the
machine's git tooling are alive — useful as an uptime signal or keep-alive
commits.

## How it works

1. [`autocommit.py`](autocommit.py) copies itself into this repository.
2. It appends/rewrites a small private `AUTOCOMMIT-HEARTBEAT` metadata block
   (a UTC timestamp) at the bottom of the copy — this guarantees
   there is always something new to commit.
3. It commits with the message `🤖 autocommit: script heartbeat`, then pushes
   to `main` with `git push --force-with-lease` and repeats every
   `AUTOCOMMIT_INTERVAL` seconds (default 120).

Before each push it runs `git fetch` + `git reset --hard origin/main`, so the
remote always wins and merge conflicts are impossible.

## Requirements

- Python 3.7+
- `git`
- A GitHub personal access token with **repo** scope (fine-grained token with
  *Contents: Read and write* on the target repo also works).

## Setup

1. Put your token on one line in a local file named `apis.txt` next to the
   runner, using this format:

   ```
   github-token = ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

   The file must live next to `autocommit.py` (e.g. `~/apis.txt`), or in
   `~/Documents/DETAIL/apis.txt`. It is *not* stored in this repository.

2. Clone/create the target repo (default `~/auto-repo`, pointing at
   `https://github.com/Tony46117/auto.git`).

3. Start the runner:

   ```bash
   python3 ~/autocommit.py
   ```

   Or keep it running after logout:

   ```bash
   nohup python3 ~/autocommit.py > ~/autocommit.log 2>&1 &
   ```

## Configuration (environment variables)

| Variable                | Default                          | Purpose                          |
|-------------------------|----------------------------------|----------------------------------|
| `AUTOCOMMIT_GIT_TOKEN`  | –                                | Token; overrides `apis.txt`      |
| `AUTOCOMMIT_REPO_DIR`   | `~/auto-repo`                    | Path to the target repo          |
| `AUTOCOMMIT_MSG`        | `🤖 autocommit: script heartbeat`| Commit message                   |
| `AUTOCOMMIT_BRANCH`     | `main`                           | Branch to push                   |
| `AUTOCOMMIT_REMOTE`     | `origin`                         | Remote name                      |
| `AUTOCOMMIT_INTERVAL`   | `120`                            | Seconds between pushes           |

## Repository layout

| File                    | Purpose                                              |
|-------------------------|------------------------------------------------------|
| `autocommit.py`         | Current copy of the runner + heartbeat metadata block |
| `apis.txt`              | Empty placeholder — the real token file lives locally |
| `.gitkeep`              | Keeps the empty repo init-able                        |
| `.autocommit-heartbeat` | Runner marker file                                    |
| `.heartbeat_now`        | Runner marker file                                    |

## Security notes

- The token is read at runtime from `AUTOCOMMIT_GIT_TOKEN` (preferred) or a
  local `apis.txt`; it is never hard-coded into the script or committed.
  No token material — not even a hash — lands in the repo.
- The token *is* embedded in the local repo's git remote URL by design —
  anyone with read access to this machine can see it in
  `git remote -v` / `.git/config`. Treat the local clone as a secret.

## Stopping / uninstalling

- Stop the loop: `pkill -f autocommit.py` (or Ctrl+C in the foreground).
- Delete the repo locally: `rm -rf ~/auto-repo`; on GitHub, just delete the
  `auto` repository.

## Disclaimer

This repository exists purely as a heartbeat — the commits carry no data
other than a timestamp. Don't point it at a repo with real
history you care about; the runner force-pushes over it every cycle.
