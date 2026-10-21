"""Query-filter extraction: kind keywords + relative/absolute dates."""

from datetime import date

from app.services.query_understanding import parse_query_filters

NOW = date(2026, 7, 13)


def test_the_motivating_example():
    f = parse_query_filters("Generate a story from my daily thoughts notes in this month", NOW)
    assert f.kinds == ["notes"]
    assert (f.date_from, f.date_to) == (date(2026, 7, 1), date(2026, 7, 31))


def test_last_month_and_meeting():
    f = parse_query_filters("what did we decide in the sync meeting last month", NOW)
    assert "conversation" in f.kinds
    assert (f.date_from, f.date_to) == (date(2026, 6, 1), date(2026, 6, 30))


def test_absolute_month_year_and_paper():
    f = parse_query_filters("summarize the chess paper from July 2024", NOW)
    assert "paper" in f.kinds
    assert (f.date_from, f.date_to) == (date(2024, 7, 1), date(2024, 7, 31))


def test_past_n_weeks():
    f = parse_query_filters("notes from the past 2 weeks", NOW)
    assert f.kinds == ["notes"]
    assert (f.date_from, f.date_to) == (date(2026, 6, 29), NOW)


def test_no_filters_on_plain_question():
    f = parse_query_filters("who is the king of Ithaca", NOW)
    assert not f.has_filter


def test_an_article_names_no_kind():
    # "Article 4" of a treaty read as a request for technical articles.
    assert not parse_query_filters("Quote Article 4 of the treaty", NOW).kinds
