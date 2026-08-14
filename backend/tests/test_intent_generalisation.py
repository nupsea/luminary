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
