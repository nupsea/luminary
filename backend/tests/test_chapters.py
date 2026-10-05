"""Chapter detection (#231): chapters from heading text first, document size second."""

from app.services.chapters import (
    WHOLE_DOCUMENT_CHARS,
    WINDOW_CHARS,
    SectionExtent,
    detect_chapters,
)


def _sections(*specs: tuple[str, int], pages: bool = False) -> list[SectionExtent]:
    out = []
    page = 1
    for i, (heading, chars) in enumerate(specs):
        span = max(1, chars // 2000)
        out.append(
            SectionExtent(
                id=f"s{i}",
                heading=heading,
                first_chunk=i * 10,
                chars=chars,
                page_start=page if pages else 0,
                page_end=page + span - 1 if pages else 0,
            )
        )
        page += span
    return out


BIG = WHOLE_DOCUMENT_CHARS


def test_chapter_marks_open_chapters_and_front_matter_is_left_out():
    chapters = detect_chapters(
        _sections(
            ("Preface", 5000),
            ("Chapter 1. Introduction", BIG),
            ("What a model is", 9000),
            ("Chapter 2. Foundation Models", BIG),
        ),
        "AI Engineering",
    )
    assert [c.title for c in chapters] == [
        "Chapter 1. Introduction",
        "Chapter 2. Foundation Models",
    ]
    assert chapters[0].section_ids == ["s1", "s2"]
    assert chapters[0].id == "s1"


def test_a_part_heading_ends_the_chapter_before_it():
    chapters = detect_chapters(
        _sections(
            ("Chapter 1. Reliability", BIG),
            ("Part II. Distributed Data", 4000),
            ("Chapter 2. Replication", BIG),
        ),
        "DDIA",
    )
    assert [c.title for c in chapters] == [
        "Chapter 1. Reliability",
        "Part II. Distributed Data",
        "Chapter 2. Replication",
    ]


def test_numbered_headings_are_chapters_only_when_they_count_up():
    roman = detect_chapters(
        _sections(*((f"{n} — Part", 15000) for n in ("I", "II", "III", "IV"))), "time_machine"
    )
    assert [c.title for c in roman] == ["I — Part", "II — Part", "III — Part", "IV — Part"]

    listicles = detect_chapters(
        _sections(
            ("9 best practices for microservices", 15000),
            ("10 Good Coding Principles", 15000),
            ("15 Open-Source Projects", 15000),
            ("8 Key Data Structures", 15000),
            ("4 Ways Netflix Uses Caching", 15000),
        ),
        "SysDesign",
    )
    # Windowed by size, not one chapter per listicle.
    assert [c.section_ids for c in listicles] == [["s0", "s1"], ["s2", "s3"], ["s4"]]


def test_a_subsection_number_is_not_a_chapter_mark():
    chapters = detect_chapters(
        _sections(("1.1 Processors", 20000), ("1.2 Overview", 20000), ("1.3 Notation", 20000)),
        "manual",
    )
    assert [c.section_ids for c in chapters] == [["s0", "s1"], ["s2"]]


def test_a_short_document_is_one_chapter_named_by_its_title():
    chapters = detect_chapters(
        _sections(("1. Intro", 2000), ("2. Method", 2000), ("3. Results", 2000)), "ml_notes"
    )
    assert [(c.title, c.section_ids) for c in chapters] == [("ml_notes", ["s0", "s1", "s2"])]


def test_unmarked_long_document_is_windowed_by_pages():
    sections = _sections(*((f"Topic {i}", 6000) for i in range(20)), pages=True)
    chapters = detect_chapters(sections, "thinkpython2")
    assert len(chapters) == 4
    assert all(c.title.startswith("Pages ") for c in chapters)
    assert all(c.chars >= WINDOW_CHARS for c in chapters[:-1])


def test_a_window_without_pages_takes_its_first_topical_heading():
    specs = [("Summary", 6000), ("Dropout", 6000)] + [(f"Topic {i}", 6000) for i in range(8)]
    chapters = detect_chapters(_sections(*specs), "d2l")
    assert chapters[0].title == "Dropout"


def test_a_page_label_the_pages_cannot_hold_is_not_shown():
    sections = [
        SectionExtent("a", "Logic", 0, 60000, page_start=9, page_end=9),
        SectionExtent("b", "Nature", 1, 60000, page_start=44, page_end=44),
    ]
    assert [c.title for c in detect_chapters(sections, "Hegel")] == ["Logic", "Nature"]


def test_back_matter_ends_the_last_chapter():
    chapters = detect_chapters(
        _sections(("Chapter 1. A", BIG), ("Chapter 2. B", BIG), ("Index", 9000)), "book"
    )
    assert chapters[-1].section_ids == ["s1"]


def test_sections_are_read_in_chunk_order_not_section_order():
    sections = [
        SectionExtent("late", "II — The Machine", 50, BIG),
        SectionExtent("early", "I — Introduction", 0, BIG),
        SectionExtent("last", "III — Returns", 90, BIG),
    ]
    assert [c.id for c in detect_chapters(sections, "time_machine")] == ["early", "late", "last"]
