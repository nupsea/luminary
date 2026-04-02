"""Tests for naming convention utilities (S199)."""


from app.services.naming import normalize_collection_name, normalize_tag_slug

# ---------------------------------------------------------------------------
# normalize_collection_name
# ---------------------------------------------------------------------------


class TestNormalizeCollectionName:
    def test_spaces_to_hyphens(self):
        assert normalize_collection_name("my notes") == "MY-NOTES"

    def test_underscores_to_hyphens(self):
        assert normalize_collection_name("machine_learning") == "MACHINE-LEARNING"

    def test_strip_whitespace(self):
        assert normalize_collection_name("  DDIA  Book  ") == "DDIA-BOOK"

    def test_empty_string(self):
        assert normalize_collection_name("") == ""

    def test_only_spaces(self):
        assert normalize_collection_name("   ") == ""

    def test_unicode(self):
        assert normalize_collection_name("cafe latte") == "CAFE-LATTE"

    def test_numbers(self):
        assert normalize_collection_name("phase 3 notes") == "PHASE-3-NOTES"

    def test_trailing_hyphens(self):
        assert normalize_collection_name("--hello--world--") == "HELLO-WORLD"

    def test_already_normalized(self):
        assert normalize_collection_name("MY-NOTES") == "MY-NOTES"

    def test_mixed_separators(self):
        assert normalize_collection_name("my_reading  notes") == "MY-READING-NOTES"

    def test_single_word(self):
        assert normalize_collection_name("python") == "PYTHON"


# ---------------------------------------------------------------------------
# normalize_tag_slug
# ---------------------------------------------------------------------------


class TestNormalizeTagSlug:
    def test_hierarchy_case(self):
        assert normalize_tag_slug("Science/Biology") == "science/biology"

    def test_spaces_to_hyphens(self):
        assert normalize_tag_slug("Machine Learning") == "machine-learning"

    def test_hierarchy_underscores(self):
        assert normalize_tag_slug("science/Cell_Division") == "science/cell-division"

    def test_empty_string(self):
        assert normalize_tag_slug("") == ""

    def test_only_spaces(self):
        assert normalize_tag_slug("   ") == ""

    def test_preserves_hierarchy(self):
        assert normalize_tag_slug("a/b/c") == "a/b/c"

    def test_multiple_segments(self):
        result = normalize_tag_slug("Science/Biology/Cell_Division")
        assert result == "science/biology/cell-division"

    def test_trailing_slash(self):
        # Trailing slash should not produce empty segment
        assert normalize_tag_slug("science/") == "science"

    def test_leading_slash(self):
        assert normalize_tag_slug("/science") == "science"

    def test_already_normalized(self):
        assert normalize_tag_slug("machine-learning") == "machine-learning"

    def test_mixed_separators_in_segment(self):
        assert normalize_tag_slug("my_tag name") == "my-tag-name"

    def test_unicode_preserved(self):
        result = normalize_tag_slug("cafe/latte")
        assert result == "cafe/latte"
