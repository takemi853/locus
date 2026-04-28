"""
Locus auto-sync — push locus-private (data repo) to GitHub so the laptop
can read the latest knowledge.

Architecture:
    Mac mini (main server) ─push→ GitHub ─pull→ Laptop (read-only)

The Mac mini generates data continuously (news collection, compile output,
lint reports, knowledge edits). Without this script that data sits in the
working tree forever and the laptop sees stale content.

Behavior:
    1. cd to data repo (settings.yaml > data_dir)
    2. git pull --ff-only           — abort on conflict (don't paper over)
    3. git add knowledge/ reports/  — only auto-generated areas
    4. exit 0 if nothing to commit
    5. git commit  with a date-stamped generic message
    6. git push
    7. notify on failure (osascript on macOS)

Usage:
    uv run python scripts/sync.py            # live run
    uv run python scripts/sync.py --dry-run  # show what would happen
    uv run python scripts/sync.py --message "..."  # override commit msg

Exit codes:
    0   success / nothing to do
    1   pull conflict / network error / push rejected
    2   misconfiguration (data_dir not a git repo etc.)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import DATA_DIR


# Directories within data_dir that auto-sync is allowed to commit.
# Anything else (manually-edited scripts, dotfiles) is left alone — the
# user commits those themselves.
SYNC_DIRS = ["knowledge", "reports"]


def _run(cmd: list[str], cwd: Path, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command, raise CalledProcessError on failure."""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=True,
        capture_output=capture,
        text=True,
    )


def _notify(title: str, message: str, sound: str = "Basso") -> None:
    """macOS notification (best-effort)."""
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}" sound name "{sound}"',
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def _has_staged_changes(cwd: Path) -> bool:
    """True if there are staged changes ready to commit."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(cwd),
    )
    return result.returncode != 0


def _is_git_repo(p: Path) -> bool:
    return (p / ".git").exists()


def sync(data_dir: Path, dry_run: bool, message: str | None) -> int:
    if not data_dir.exists():
        print(f"[error] data_dir does not exist: {data_dir}", file=sys.stderr)
        return 2
    if not _is_git_repo(data_dir):
        print(f"[error] data_dir is not a git repo: {data_dir}", file=sys.stderr)
        return 2

    label = "[dry-run]" if dry_run else "[sync]"

    # ── Step 1: pull ─────────────────────────────────────────────
    # `--rebase --autostash` handles the common laptop ↔ mini case:
    #   • behind-only      → linear rebase
    #   • dirty work tree  → autostash, rebase, pop
    #   • conflict         → rebase aborts cleanly (no half-applied state)
    print(f"{label} cd {data_dir}")
    print(f"{label} git pull --rebase --autostash")
    if not dry_run:
        try:
            _run(["git", "pull", "--rebase", "--autostash"], data_dir)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            # Best-effort: abort any half-completed rebase so we don't
            # leave the repo in MERGING/REBASING state.
            subprocess.run(["git", "rebase", "--abort"], cwd=str(data_dir), capture_output=True)
            print(f"[abort] git pull --rebase failed: {stderr}", file=sys.stderr)
            _notify("Locus sync failed", "git rebase conflict — manual merge needed")
            return 1

    # ── Step 2: stage ────────────────────────────────────────────
    existing_dirs = [d for d in SYNC_DIRS if (data_dir / d).exists()]
    if not existing_dirs:
        print(f"{label} no SYNC_DIRS exist — nothing to sync")
        return 0

    print(f"{label} git add {' '.join(existing_dirs)}")
    if dry_run:
        # Show what would be staged WITHOUT actually staging.
        status = subprocess.run(
            ["git", "status", "--short", "--", *existing_dirs],
            cwd=str(data_dir),
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            lines = status.stdout.rstrip().splitlines()
            print(f"{label} would stage {len(lines)} file(s):")
            for line in lines[:20]:
                print(f"  {line}")
            if len(lines) > 20:
                print(f"  ... and {len(lines) - 20} more")
            print(f"{label} (would commit and push)")
        else:
            print(f"{label} no changes to commit")
        return 0

    try:
        _run(["git", "add", "--", *existing_dirs], data_dir)
    except subprocess.CalledProcessError as e:
        print(f"[abort] git add failed: {e.stderr}", file=sys.stderr)
        return 1

    # Show what was actually staged.
    diff = subprocess.run(
        ["git", "diff", "--cached", "--stat"],
        cwd=str(data_dir),
        capture_output=True,
        text=True,
    )
    if diff.stdout.strip():
        print(diff.stdout.rstrip())
    else:
        print(f"{label} no changes to commit")
        return 0

    # In live mode, double-check there are staged changes (paranoia).
    if not _has_staged_changes(data_dir):
        print(f"{label} nothing staged after add — exiting")
        return 0

    # ── Step 3: commit ───────────────────────────────────────────
    if message is None:
        message = f"auto: nightly sync ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    print(f"{label} git commit -m {message!r}")
    try:
        _run(["git", "commit", "-m", message], data_dir)
    except subprocess.CalledProcessError as e:
        print(f"[abort] git commit failed: {e.stderr}", file=sys.stderr)
        return 1

    # ── Step 4: push ─────────────────────────────────────────────
    print(f"{label} git push")
    try:
        _run(["git", "push"], data_dir)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        print(f"[abort] git push failed: {stderr}", file=sys.stderr)
        _notify("Locus sync failed", "git push failed — check network/auth")
        return 1

    print(f"{label} done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--message", help="Override commit message")
    args = parser.parse_args()
    return sync(DATA_DIR, args.dry_run, args.message)


if __name__ == "__main__":
    sys.exit(main())
