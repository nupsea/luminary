"""Doc gardener: checks that key docs/ files have been updated recently.

Runs after each ralph iteration. Prints STALE DOC warnings for files not modified
in the last 10 commits. Always exits 0 (advisory only).

Run: python scripts/ralph/doc_gardener.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

WATCHED_DOCS = [
    "docs/QUALITY_SCORE.md",
    "docs/exec-plans/tech-debt-tracker.md",
    "docs/ARCHITECTURE.md",
]


def was_modified_recently(filepath: str, n_commits: int = 10) -> bool:
    """Return True if the file was modified in the last n_commits commits.

    Uses HEAD~N..HEAD range. Falls back to checking the full log if the
    repo has fewer than n_commits commits total.
    """
    # Try the range-based check first
    result = subprocess.run(
        ["git", "log", "--oneline", f"HEAD~{n_commits}..HEAD", "--", filepath],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode == 0:
        return bool(result.stdout.strip())

    # If HEAD~N doesn't exist (shallow repo), fall back to all commits
    result = subprocess.run(
        ["git", "log", "--oneline", "--", filepath],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return bool(result.stdout.strip())


def main() -> int:
    stale: list[str] = []
    for doc in WATCHED_DOCS:
        if not was_modified_recently(doc):
            stale.append(doc)
            print(
                f"STALE DOC: {doc} has not been updated in the last 10 commits. "
                f"Update it to reflect current implementation status."
            )

    if not stale:
        print("doc_gardener: all watched docs updated recently.")

    return 0  # advisory only


if __name__ == "__main__":
    sys.exit(main())
