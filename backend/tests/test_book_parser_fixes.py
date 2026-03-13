from pathlib import Path

import pytest

from app.services.book_parser import BookParser

bp = BookParser()
DATA_BOOKS = Path("DATA/books")

def test_alice_chapter_xi_subtitle():
    path = DATA_BOOKS / "alice_in_wonderland.txt"
    if not path.exists():
        pytest.skip("alice_in_wonderland.txt not found")
    
    result = bp.parse(path, "txt")
    assert result is not None
    # Chapter XI is usually the 11th chapter (index 10)
    # but there might be a preface or something.
    # Let's find it by heading.
    ch11 = next((s for s in result.sections if "CHAPTER XI" in s.heading), None)
    assert ch11 is not None
    assert "Who Stole the Tarts?" in ch11.heading
