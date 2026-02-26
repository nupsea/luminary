#!/usr/bin/env bash
# setup_books.sh — download and verify the three canonical corpus books.
# Usage: ./scripts/corpus/setup_books.sh
# Exits 0 when all books are present and meet minimum word counts.
# Exits 1 on any missing or truncated file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOOKS_DIR="${REPO_ROOT}/DATA/books"

mkdir -p "${BOOKS_DIR}"

# ── helpers ────────────────────────────────────────────────────────────────────
verify_book() {
    local name="$1"
    local filepath="${REPO_ROOT}/$2"
    local url="$3"
    local min_words="$4"

    echo "==> ${name}"

    if [[ ! -f "${filepath}" ]]; then
        echo "    Downloading from ${url} ..."
        curl -fsSL "${url}" -o "${filepath}"
    else
        echo "    Already present: ${filepath}"
    fi

    local word_count
    word_count=$(wc -w < "${filepath}" | tr -d ' ')
    echo "    Word count: ${word_count} (minimum: ${min_words})"

    if [[ "${word_count}" -lt "${min_words}" ]]; then
        echo "ERROR: ${name} word count ${word_count} is below minimum ${min_words}. File may be truncated." >&2
        return 1
    fi

    echo "    OK"
}

# ── books ──────────────────────────────────────────────────────────────────────
verify_book \
    "The Time Machine" \
    "DATA/books/time_machine.txt" \
    "https://www.gutenberg.org/cache/epub/35/pg35.txt" \
    30000

verify_book \
    "Alice in Wonderland" \
    "DATA/books/alice_in_wonderland.txt" \
    "https://www.gutenberg.org/cache/epub/11/pg11.txt" \
    25000

verify_book \
    "The Odyssey" \
    "DATA/books/the_odyssey.txt" \
    "https://www.gutenberg.org/cache/epub/1727/pg1727.txt" \
    100000

echo ""
echo "All three corpus books verified successfully."
