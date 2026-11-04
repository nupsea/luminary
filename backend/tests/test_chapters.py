"""Chapter detection (#231): chapters from heading text first, document size second."""

from app.services.chapters import (
    WHOLE_DOCUMENT_CHARS,
    WINDOW_CHARS,
    SectionExtent,
    detect_chapters,
    with_parts,
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


_THINKPYTHON2_FRONT = (
    ("", 1500),  # title page
    ("", 1500),  # copyright
    ("Preface", 4000),
    ("The strange history of this book", 5000),
    ("Acknowledgments", 2000),
    ("Contributor List", 12000),
)


def test_an_unmarked_book_does_not_open_on_its_preface():
    """#252: thinkpython2's chapter 1 was the title pages, preface and contributor list."""
    body = [(f"Topic {i}", 6000) for i in range(30)]
    sections = _sections(*_THINKPYTHON2_FRONT, *body, pages=True)
    chapters = detect_chapters(sections, "thinkpython2")
    assert chapters[0].id == "s6"
    assert not {"s0", "s1", "s2", "s3", "s4", "s5"} & {s for c in chapters for s in c.section_ids}


def test_front_matter_does_not_move_a_marked_book():
    marks = [("Chapter 1. Introduction", BIG), ("Chapter 2. Foundation Models", BIG)]
    plain = detect_chapters(_sections(*marks), "AI Engineering")
    fronted = detect_chapters(_sections(*_THINKPYTHON2_FRONT, *marks), "AI Engineering")
    assert [(c.title, c.chars) for c in fronted] == [(c.title, c.chars) for c in plain]


def test_an_untitled_opening_alone_is_kept():
    """A paper's abstract is parsed as an untitled preamble, and it is the paper."""
    chapters = detect_chapters(_sections(("", 3000), ("1 Introduction", 9000)), "chexnet")
    assert chapters[0].section_ids == ["s0", "s1"]


def test_front_matter_names_past_the_opening_are_kept():
    body = [(f"Topic {i}", 6000) for i in range(20)]
    sections = _sections(("Preface", 3000), *body, ("Acknowledgments", 3000), *body[:2])
    chapters = detect_chapters(sections, "book")
    assert chapters[0].id == "s1"
    assert "s21" in {s for c in chapters for s in c.section_ids}


def test_sections_are_read_in_chunk_order_not_section_order():
    sections = [
        SectionExtent("late", "II — The Machine", 50, BIG),
        SectionExtent("early", "I — Introduction", 0, BIG),
        SectionExtent("last", "III — Returns", 90, BIG),
    ]
    assert [c.id for c in detect_chapters(sections, "time_machine")] == ["early", "late", "last"]


def test_a_preface_takes_its_subsections_with_it():
    """Think Stats: "Preface" is followed only by its own level-2 subsections, the second
    holding the contributor list, so cutting at the last named section kept them in chapter 1."""
    front = [
        SectionExtent("title", "", 0, 2000, level=1),
        SectionExtent("preface", "Preface", 10, 1500, level=1),
        SectionExtent("how", "How I wrote this book", 20, 3000, level=2),
        SectionExtent("code", "Using the code", 30, 9000, level=2),
    ]
    body = [SectionExtent(f"b{i}", f"Topic {i}", 100 + i * 10, 6000, level=1) for i in range(30)]
    chapters = detect_chapters(front + body, "thinkstats2")
    assert chapters[0].id == "b0"
    assert not {"title", "preface", "how", "code"} & {s for c in chapters for s in c.section_ids}


def test_a_preface_over_a_book_of_deeper_chapters_takes_only_itself():
    """A markdown book whose chapters are all "##" under one "# Preface" is not front matter."""
    front = [SectionExtent("preface", "Preface", 0, 3000, level=1)]
    body = [
        SectionExtent(f"c{i}", f"Chapter topic {i}", 10 + i * 10, 6000, level=2) for i in range(30)
    ]
    chapters = detect_chapters(front + body, "book")
    assert chapters[0].id == "c0"
    assert "c29" in {s for c in chapters for s in c.section_ids}


def test_letters_and_numbered_papers_are_chapter_marks():
    """Frankenstein opens on four Letters before Chapter 1 (#332); the Federalist Papers are
    headed "FEDERALIST No. N" (#333). Unmarked, the Letters fell outside every chapter."""
    novel = detect_chapters(
        _sections(("Letter 1", BIG), ("Letter 2", BIG), ("Chapter 1", BIG), ("Chapter 2", BIG)),
        "Frankenstein",
    )
    papers = detect_chapters(
        _sections(*((f"FEDERALIST No. {n} — A Subject", BIG) for n in range(1, 4))), "Federalist"
    )

    assert [c.title for c in novel] == ["Letter 1", "Letter 2", "Chapter 1", "Chapter 2"]
    assert [c.title for c in papers] == [f"FEDERALIST No. {n} — A Subject" for n in range(1, 4)]


def _tree(*specs: tuple[str, int, int]) -> list[SectionExtent]:
    """(heading, level, chars) in reading order; chars 0 is a title over the sections after it."""
    parts = with_parts([(h, level, chars > 0) for h, level, chars in specs])
    return [
        SectionExtent(f"s{i}", h, i * 10, chars, level=level, part=part)
        for i, ((h, level, chars), part) in enumerate(zip(specs, parts, strict=True))
        if chars
    ]


def test_with_parts_names_the_empty_heading_each_section_sits_under():
    sections = [
        ("PART I", 1, False),
        ("CHAPTER I", 2, True),
        ("PART II", 1, False),
        ("CHAPTER I", 2, True),
        ("EPILOGUE", 1, True),
    ]

    assert with_parts(sections) == ["", "PART I", "", "PART II", ""]


def test_with_parts_reads_a_run_of_empty_headings_as_contents():
    sections = [("PART I", 1, False), ("PART II", 1, False), ("CHAPTER I", 2, True)]

    assert with_parts(sections) == ["", "", ""]


def test_with_parts_takes_the_nearest_of_nested_empty_headings():
    sections = [("PART I", 1, False), ("BOOK 1", 2, False), ("CHAPTER I", 3, True)]

    assert with_parts(sections) == ["", "", "BOOK 1"]


def test_a_titled_chapter_keeps_its_title_under_a_numbered_part():
    """War of the Worlds-shaped: numbered books over numbered, titled chapters."""
    books = [("I. THE COMING", 1, 0), ("II. THE EARTH UNDER THE MARTIANS", 1, 0)]
    chapters = detect_chapters(
        _tree(
            books[0],
            *((f"{n} CHAPTER {n}.", 2, BIG) for n in ("I", "II")),
            books[1],
            *((f"{n} CHAPTER {n}.", 2, BIG) for n in ("III", "IV")),
        ),
        "War of the Worlds",
    )

    assert [c.title for c in chapters] == [f"{n} CHAPTER {n}." for n in ("I", "II", "III", "IV")]


def test_a_repeated_chapter_title_is_named_by_its_part():
    """Gulliver's four parts each open on "CHAPTER I"; the chapter list read as twelve
    indistinguishable rows (#334)."""
    chapters = detect_chapters(
        _tree(
            ("PART I. A VOYAGE TO LILLIPUT", 1, 0),
            ("CHAPTER I", 2, BIG),
            ("CHAPTER II", 2, BIG),
            ("PART II. A VOYAGE TO BROBDINGNAG", 1, 0),
            ("CHAPTER I", 2, BIG),
            ("CHAPTER III", 2, BIG),
        ),
        "Gulliver",
    )

    assert [c.title for c in chapters] == [
        "PART I. A VOYAGE TO LILLIPUT — CHAPTER I",
        "CHAPTER II",
        "PART II. A VOYAGE TO BROBDINGNAG — CHAPTER I",
        "CHAPTER III",
    ]


def test_a_chapter_split_into_numbered_parts_is_one_chapter():
    """Sherlock's "I. A SCANDAL IN BOHEMIA" is one story in three parts, "I" to "III" (#334)."""
    chapters = detect_chapters(
        _tree(
            ("I. A SCANDAL IN BOHEMIA", 1, 0),
            ("I", 2, BIG),
            ("II", 2, BIG),
            ("III", 2, BIG),
            ("II. THE RED-HEADED LEAGUE", 1, BIG),
            ("III. A CASE OF IDENTITY", 1, BIG),
            ("IV. THE BOSCOMBE VALLEY MYSTERY", 1, BIG),
            ("V. THE FIVE ORANGE PIPS", 1, BIG),
        ),
        "Sherlock",
    )

    assert [(c.title, c.section_ids) for c in chapters] == [
        ("I. A SCANDAL IN BOHEMIA", ["s1", "s2", "s3"]),
        ("II. THE RED-HEADED LEAGUE", ["s4"]),
        ("III. A CASE OF IDENTITY", ["s5"]),
        ("IV. THE BOSCOMBE VALLEY MYSTERY", ["s6"]),
        ("V. THE FIVE ORANGE PIPS", ["s7"]),
    ]


def test_ordinal_books_are_parts_only_as_the_whole_heading():
    """Meditations is twelve "THE FIRST BOOK".."THE TWELFTH BOOK" (#334); the Bible's "The First
    Book of Moses: Called Genesis" names a book inside its text, not a division."""
    books = ("FIRST", "SECOND", "THIRD", "FOURTH")
    meditations = detect_chapters(
        _sections(*((f"THE {n} BOOK", 15000) for n in books)), "Meditations"
    )
    bible = detect_chapters(
        _sections(
            *(
                (f"The {n} Book of Moses: Called {name}", 15000)
                for n, name in (
                    ("First", "Genesis"),
                    ("Second", "Exodus"),
                    ("Third", "Leviticus"),
                    ("Fourth", "Numbers"),
                )
            )
        ),
        "Bible",
    )

    assert [c.title for c in meditations] == [f"THE {n} BOOK" for n in books]
    # Windowed by size, not one chapter per heading.
    assert [c.section_ids for c in bible] == [["s0", "s1"], ["s2", "s3"]]


def test_bare_roman_numerals_are_numbered_chapters():
    """The Great Gatsby's chapters are headed "I" to "IX" alone (#334); a bare "2" stays a list
    item."""
    numerals = ("I", "II", "III", "IV")
    gatsby = detect_chapters(_sections(*((n, 15000) for n in numerals)), "Gatsby")
    titled = detect_chapters(
        _tree(("THE GREAT GATSBY", 1, 0), *((n, 2, 15000) for n in numerals)), "Gatsby"
    )
    digits = detect_chapters(_sections(*((n, 15000) for n in ("1", "2", "3", "4"))), "list")

    assert [c.title for c in gatsby] == list(numerals)
    assert [c.title for c in titled] == list(numerals)
    assert [c.section_ids for c in digits] == [["s0", "s1"], ["s2", "s3"]]


_VOYAGES = (("I", "LILLIPUT"), ("II", "BROBDINGNAG"))
# Three chapters a part: under five chapters the topic list keeps the parts too.
_GULLIVER = [
    spec
    for p, place in _VOYAGES
    for spec in [(f"PART {p}. A VOYAGE TO {place}", 1, 0)]
    + [(f"CHAPTER {c}", 2, BIG) for c in ("I", "II", "III")]
]
_GULLIVER_TITLES = [
    f"PART {p}. A VOYAGE TO {place} — CHAPTER {c}"
    for p, place in _VOYAGES
    for c in ("I", "II", "III")
]


async def _store(factory, doc_id: str, specs: list[tuple[str, int, int]]) -> None:
    """Sections as stored, with text only through their chunks, as ingestion writes them."""
    from tests.factories import make_chunk, make_document, make_section

    async with factory() as s:
        s.add(make_document(id=doc_id, format="txt", file_path="/x", stage="complete"))
        for i, (heading, level, chars) in enumerate(specs):
            sid = f"{doc_id}-s{i}"
            s.add(
                make_section(
                    id=sid, document_id=doc_id, heading=heading, level=level, section_order=i
                )
            )
            if chars:
                s.add(
                    make_chunk(
                        id=f"{doc_id}-c{i}",
                        document_id=doc_id,
                        section_id=sid,
                        chunk_index=i,
                        text="x" * chars,
                    )
                )
        await s.commit()


async def test_a_stored_book_names_its_chapters_by_part(memory_db):
    from app.services.chapters import chapters_for_document

    await _store(memory_db.factory, "g", _GULLIVER)
    async with memory_db.factory() as session:
        chapters = await chapters_for_document("g", "Gulliver", session)

    assert [c.title for c in chapters] == _GULLIVER_TITLES


async def test_a_stored_book_names_its_topics_by_part(memory_db, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    import app.services.graph as graph_module
    from app.main import app

    monkeypatch.setattr(graph_module, "_graph_service", None)
    await _store(memory_db.factory, "g", _GULLIVER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/study/topics/g")).json()

    assert body["source"] == "sections"
    assert [t["title"] for t in body["topics"]] == _GULLIVER_TITLES


def test_a_contents_list_over_numbered_chapters_is_not_their_part():
    """A Time Machine stored by an older parse kept ten empty contents entries above its
    chapters; read as a part, the last one titled and merged all sixteen (#334)."""
    numerals = ("I", "II", "III", "IV", "V")
    chapters = detect_chapters(
        _tree(
            *((f"{n} Entry", 1, 0) for n in numerals),
            *((f"{n} — Chapter {n}", 2, 15000) for n in numerals),
        ),
        "time_machine",
    )

    assert [c.title for c in chapters] == [f"{n} — Chapter {n}" for n in numerals]


def test_a_bare_numeral_beside_titled_ones_is_a_part_of_its_chapter():
    """A Sherlock stored without its first story's title: the parts "I", "II" sit among the
    stories "II. THE RED-HEADED LEAGUE" .., and are not chapters of their own (#334)."""
    stories = ("II. THE LEAGUE", "III. THE IDENTITY", "IV. THE MYSTERY", "V. THE PIPS")
    chapters = detect_chapters(
        _tree(("I", 2, BIG), ("II", 2, BIG), *((t, 1, BIG) for t in stories), ("I", 2, BIG)),
        "Sherlock",
    )

    assert [(c.title, len(c.section_ids)) for c in chapters] == [
        *((t, 1) for t in stories[:-1]),
        (stories[-1], 2),
    ]
