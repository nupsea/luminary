"""Structure-aware chunking for research papers, and its fallback gate."""

from app.services.paper_chunker import (
    chunk_paper_section,
    is_references_heading,
    looks_like_paper,
    segment_section,
    unwrap_prose,
)


def _sections(*headings: str) -> list[dict]:
    return [{"heading": h, "text": "body text"} for h in headings]


class TestStructureGate:
    def test_imrad_paper_is_recognised(self):
        assert looks_like_paper(
            _sections("Abstract", "Introduction", "Methods", "Results", "Conclusion")
        )

    def test_numbered_sections_with_anchor_are_recognised(self):
        assert looks_like_paper(
            _sections("Abstract", "1. Background", "2.1 Model", "3. Evaluation")
        )

    def test_numbered_headings_without_paper_anchor_fall_back(self):
        """Manuals use numbered headings too; they must not take the paper path."""
        assert not looks_like_paper(
            _sections("1. Getting Started", "2. Installing", "3. Troubleshooting")
        )

    def test_too_few_headings_falls_back(self):
        assert not looks_like_paper(_sections("Abstract", "Introduction"))

    def test_empty_sections_fall_back(self):
        assert not looks_like_paper([])


class TestReferencesDetection:
    def test_variants_are_detected(self):
        for heading in ("References", "REFERENCES", "Bibliography", "7. References"):
            assert is_references_heading(heading), heading

    def test_body_headings_are_not_references(self):
        for heading in ("Results", "Reference Architecture", ""):
            assert not is_references_heading(heading)


class TestSegmentation:
    def test_vertical_token_run_is_noise(self):
        """PDF text layers emit figure axis labels one token per line."""
        text = "Real prose here that continues.\n" + "\n".join(
            ["The", "Law", "will", "never", "be", "perfect", "just"]
        )
        kinds = [k for k, _ in segment_section(text)]
        assert "noise" in kinds

    def test_short_token_run_is_not_noise(self):
        text = "Prose paragraph.\n" + "\n".join(["one", "two", "three"])
        assert "noise" not in [k for k, _ in segment_section(text)]

    def test_caption_is_its_own_segment(self):
        text = "Body prose sentence.\n\nFigure 3: A schematic of the system.\n\nMore prose."
        assert ("caption", "Figure 3: A schematic of the system.") in segment_section(text)

    def test_caption_does_not_swallow_following_pages(self):
        """Without a bound, a caption runs to the next blank line -- which PDF
        text layers often never emit."""
        body = "\n".join(f"continuation line {i} of ordinary prose" for i in range(40))
        segments = segment_section(f"Figure 1: Short caption\n{body}")
        caption = next(t for k, t in segments if k == "caption")
        assert len(caption) < 700


class TestUnwrapProse:
    def test_wrapped_lines_are_rejoined(self):
        assert unwrap_prose("the model uses\nself-attention layers") == (
            "the model uses self-attention layers"
        )

    def test_sentence_end_starts_a_new_line(self):
        assert unwrap_prose("First sentence.\nSecond sentence") == (
            "First sentence.\nSecond sentence"
        )

    def test_hyphenated_break_is_rejoined_without_hyphen(self):
        assert unwrap_prose("atten-\ntion") == "attention"

    def test_blank_lines_are_preserved(self):
        assert unwrap_prose("para one\n\npara two") == "para one\n\npara two"


class TestChunking:
    def test_figure_noise_never_reaches_chunks(self):
        text = "Prose that is long enough to matter here.\n" + "\n".join(
            ["The", "Law", "will", "never", "be", "perfect", "<EOS>", "<pad>"]
        )
        joined = " ".join(chunk_paper_section(text, 900, 150))
        assert "<EOS>" not in joined
        assert "<pad>" not in joined

    def test_caption_is_emitted_whole(self):
        caption = "Figure 2: The encoder maps an input sequence to a continuous representation."
        chunks = chunk_paper_section(f"Some prose.\n\n{caption}\n\nMore prose.", 900, 150)
        assert caption in chunks

    def test_chunks_respect_size_budget(self):
        text = " ".join(f"Sentence number {i} carries some content." for i in range(400))
        assert all(len(c) <= 900 for c in chunk_paper_section(text, 900, 150))

    def test_chunks_do_not_start_with_split_punctuation(self):
        text = " ".join(f"Sentence number {i} carries some content." for i in range(200))
        assert not any(c.lstrip().startswith(".") for c in chunk_paper_section(text, 300, 50))

    def test_empty_text_yields_no_chunks(self):
        assert chunk_paper_section("   \n\n  ", 900, 150) == []
