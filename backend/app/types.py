from dataclasses import dataclass, field


@dataclass
class Section:
    heading: str
    level: int
    text: str
    page_start: int
    page_end: int


@dataclass
class ParsedDocument:
    title: str
    format: str
    pages: int
    word_count: int
    sections: list[Section] = field(default_factory=list)
    raw_text: str = ""
