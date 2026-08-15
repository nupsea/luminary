"""Does routing generalise, or was it fitted to `golden/intents.jsonl`?

The routing golden is 50 hand-written rows naming entities from the dev corpus
(Penelope, the White Sphinx). Scoring 1.0000 on it proves nothing about a
document the classifier has never seen: a keyword added to catch one golden row
scores the same as a rule that actually generalises.

These tests hold the phrasing and vary everything else. Routing keys on how a
question is asked, never on what it is about, so substituting subjects must not
change the route -- and a paraphrase built from the same shape must route the
same way even though the exact string appears in no golden.
"""

import pytest

from app.services.intent import classify_intent_heuristic

# Deliberately alien to the dev corpus: two invented technical subjects, two
# invented people, two ordinary objects. If a route depends on the subject rather
# than the phrasing, one of these columns breaks and the others do not.
SUBJECT_PAIRS = [
    ("the Vantari protocol", "the Ostrek cipher"),
    ("Dr Halbrecht", "Professor Nkemi"),
    ("the copper kettle", "the iron stove"),
    ("quantisation", "distillation"),
]


def _instantiate(template: str) -> list[str]:
    return [template.format(a=a, b=b) for a, b in SUBJECT_PAIRS]


COMPARATIVE_TEMPLATES = [
    "How are {a} and {b} different?",
    "What is the difference between {a} and {b}?",
    "Compare {a} and {b}",
    "Similarities between {a} and {b}",
    "{a} versus {b}",
    "Is {a} better than {b}?",
    "What distinguishes {a} from {b}?",
]

RELATIONAL_TEMPLATES = [
    "What is the relationship between {a} and {b}?",
    "What connects {a} to {b}?",
    "What ties {a} to {b}?",
    "How is {a} related to {b}?",
    "What links {a} and {b}?",
]

SUMMARY_TEMPLATES = [
    "What is this book about?",
    "What is this paper about?",
    "What is that report about?",
    "Recap the document",
    "Give me the gist",
    "What are the main themes?",
    "Summarize this",
]


@pytest.mark.parametrize("template", COMPARATIVE_TEMPLATES)
def test_comparative_phrasings_route_by_shape_not_subject(template):
    for question in _instantiate(template):
        assert classify_intent_heuristic(question)[0] == "comparative", question


@pytest.mark.parametrize("template", RELATIONAL_TEMPLATES)
def test_relational_phrasings_route_by_shape_not_subject(template):
    for question in _instantiate(template):
        assert classify_intent_heuristic(question)[0] == "relational", question


@pytest.mark.parametrize("question", SUMMARY_TEMPLATES)
def test_summary_phrasings_route_by_shape(question):
    """"What is <this|that> <any noun> about" is matched as a shape. The noun is
    whatever the user calls their document, so it cannot be enumerated."""
    assert classify_intent_heuristic(question)[0] == "summary", question


def test_the_same_question_routes_the_same_way_for_every_subject():
    """The sharpest form of the rule: one template, every subject pair, one route.
    A keyword tuned to a corpus entity fails here and nowhere else."""
    for template in COMPARATIVE_TEMPLATES + RELATIONAL_TEMPLATES:
        routes = {classify_intent_heuristic(q)[0] for q in _instantiate(template)}
        assert len(routes) == 1, f"{template} routed {routes} depending on its subjects"


def test_summary_shape_does_not_swallow_a_factual_question_about_a_topic():
    """The shape must stay tight: asking what one thing is, is not asking what the
    document is about."""
    assert classify_intent_heuristic("Who is Dr Halbrecht?")[0] != "summary"
    assert classify_intent_heuristic("When was the Vantari protocol written?")[0] != "summary"


# Negation: a keyword only routes when nothing in front of it cancels it.
#
# "I don't need the whole overview, just tell me what year it was published"
# asked for a fact and routed to summary. The fix is a rule about the sentence,
# not four more phrases: any negation marker governing any keyword suppresses
# that occurrence. These cases hold that rule across the cross-product, because
# a fix that only handles "don't need the overview" is a fix to one row.

NEGATIONS = [
    "I don't need {kw}",
    "I do not want {kw}",
    "No {kw} please",
    "Skip {kw}",
    "Forget {kw}",
    "Rather than {kw}",
    "Instead of {kw}",
    "Without {kw}",
]

# One per family in _SUMMARY_KWS: an explicit request word, a themes phrase, a
# big-picture phrase, and one of the informal words.
SUMMARY_KEYWORDS = ["a summary", "an overview", "the main points", "the big picture", "the gist"]

# The relational and comparative sets go through the same matcher, so the rule
# has to hold for them too or it is a summary-only patch wearing a general name.
RELATIONAL_KEYWORDS = ["the relationship between them", "how they connect"]
COMPARATIVE_KEYWORDS = ["a comparison", "the differences between them"]


@pytest.mark.parametrize("negation", NEGATIONS)
@pytest.mark.parametrize("keyword", SUMMARY_KEYWORDS)
def test_a_negated_summary_keyword_does_not_route_to_summary(negation, keyword):
    question = f"{negation.format(kw=keyword)}, tell me what year the Vantari protocol shipped."
    assert classify_intent_heuristic(question)[0] != "summary", question


@pytest.mark.parametrize("keyword", SUMMARY_KEYWORDS)
def test_the_same_keyword_unnegated_still_routes_to_summary(keyword):
    """The control. A suppression rule that also suppresses the real request has
    traded one misroute for another."""
    assert classify_intent_heuristic(f"Give me {keyword}")[0] == "summary", keyword


@pytest.mark.parametrize("negation", NEGATIONS)
@pytest.mark.parametrize("keyword", RELATIONAL_KEYWORDS + COMPARATIVE_KEYWORDS)
def test_negation_applies_to_every_keyword_family(negation, keyword):
    question = f"{negation.format(kw=keyword)}, quote the line about the Ostrek cipher."
    assert classify_intent_heuristic(question)[0] not in {"relational", "comparative"}, question


def test_negation_stops_at_its_own_clause():
    """The negation governs `understand`, and the request after the comma is
    exactly the one the sentence makes. Reaching past the clause boundary would
    turn every apologetic preamble into a suppression."""
    assert (
        classify_intent_heuristic(
            "I don't understand this document, can you summarize it?"
        )[0]
        == "summary"
    )
    assert (
        classify_intent_heuristic("I don't like it, but summarize the document anyway")[0]
        == "summary"
    )


def test_one_negated_mention_does_not_cancel_a_second_real_one():
    """Every occurrence has to be negated for the mention to be suppressed."""
    assert (
        classify_intent_heuristic(
            "No summary of chapter 1, give me the summary of chapter 2"
        )[0]
        == "summary"
    )


def test_negation_far_from_the_keyword_does_not_reach_it():
    """Five words inside one clause, not the whole sentence: a negation about
    something else earlier on must not silence a request made later."""
    assert (
        classify_intent_heuristic(
            "I do not have much time this afternoon so give me an overview"
        )[0]
        == "summary"
    )


def test_summary_keywords_still_match_their_own_inflections():
    """The negation rule must not quietly become a word-boundary rule. These
    keywords are written singular and are meant to catch the plural: tightening
    the match drops every one of them, which is a matching change disguised as a
    negation fix. It happened once -- 'What are the central themes?' stopped
    routing to summary and the gated golden fell from 1.0000 to 0.9800."""
    for question in (
        "What are the central themes?",
        "What are the main ideas covered?",
        "Give me the outlines",
    ):
        assert classify_intent_heuristic(question)[0] == "summary", question


# Shapes for the two families that had perfect precision and poor recall: they
# fired on their own keyword and nothing else, so an intent stated without that
# word fell through to search. Each template below is a structure with subject
# slots, instantiated against every subject pair.

COMPARATIVE_SHAPE_TEMPLATES = [
    "Which of {a} and {b} does the author favour?",
    "Which one of {a} or {b} is stronger?",
    "Is {a} or {b} the better fit here?",
    "Should I use {a} or {b}?",
    "If I had to choose between {a} and {b}, which does the text argue for?",
    "Where do {a} and {b} disagree?",
    "The points where {a} and {b} diverge",
]

RELATIONAL_SHAPE_TEMPLATES = [
    "What sits between {a} and {b} in the chain?",
    "What does {a} have to do with {b}?",
    "How does {a} lead into {b}?",
    "Trace the thread from {a} through to {b}",
    "Does {a} feed into {b}?",
]


@pytest.mark.parametrize("template", COMPARATIVE_SHAPE_TEMPLATES)
def test_a_comparison_without_the_word_compare_still_routes_comparative(template):
    for question in _instantiate(template):
        assert classify_intent_heuristic(question)[0] == "comparative", question


@pytest.mark.parametrize("template", RELATIONAL_SHAPE_TEMPLATES)
def test_a_relation_without_the_word_connect_still_routes_relational(template):
    for question in _instantiate(template):
        assert classify_intent_heuristic(question)[0] == "relational", question


@pytest.mark.parametrize(
    "template", COMPARATIVE_SHAPE_TEMPLATES + RELATIONAL_SHAPE_TEMPLATES
)
def test_shape_routes_do_not_depend_on_their_subjects(template):
    routes = {classify_intent_heuristic(q)[0] for q in _instantiate(template)}
    assert len(routes) == 1, f"{template} routed {routes} depending on its subjects"


@pytest.mark.parametrize(
    "question",
    [
        "Show me the sections from page 5 to page 10",
        "What happened from 1920 to 1930?",
        "Which page mentions the Vantari protocol?",
        "What did Dr Halbrecht say about the copper kettle?",
        "Who was Professor Nkemi?",
    ],
)
def test_shapes_do_not_swallow_ordinary_lookups(question):
    """A range and a plain lookup are searches. `from X to Y` is deliberately not
    a relational shape for this reason -- it is how pages and dates are written."""
    assert classify_intent_heuristic(question)[0] not in {"relational", "comparative"}, question


def test_a_keyword_outranks_a_shape_from_the_other_family():
    """A keyword names the intent; a shape infers it. 'the difference between X
    and Y' carries both, and the statement wins over the inference."""
    question = "What is the difference between the Vantari protocol and the Ostrek cipher?"
    assert classify_intent_heuristic(question)[0] == "comparative"
