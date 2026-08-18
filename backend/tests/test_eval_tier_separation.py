"""The matrix must not report a separation it did not check.

Two limits found by the 2026-08-16 four-model run, both of which let the
instrument look sharper than it is:

- the separation block compared `arms[0]` against `arms[1]` and silently ignored
  every other pair, so a run could print SEPARATED while two of its candidates
  were indistinguishable;
- a question the model repeated inside one request was dropped before delivery,
  so `cards_generated` absorbed it -- llama3.2 lost 1 card and gemma3 lost 2 with
  nothing reporting it. A model repeating itself is exactly the structural
  weakness this tier exists to show.
"""

from app.services.eval_tiers import STRUCTURAL, separation, structural_metrics, tier


class TestDuplicateQuestionsAreStructural:
    def test_a_repeated_question_is_a_structural_metric(self):
        assert tier("duplicate_question_rate") == "structural"
        assert tier("duplicate_questions") == "structural"

    def test_it_reaches_the_structural_view(self):
        assert "duplicate_question_rate" in structural_metrics(
            {"duplicate_question_rate": 0.2, "faithfulness": 0.5}
        )

    def test_the_factuality_gate_counts_are_structural_but_the_judged_score_is_not(self):
        """The checker's verdict is a count of the contract being met, not an
        opinion about style -- unlike `factuality`, which a judge produces."""
        assert tier("factuality_reject_rate") == "structural"
        assert tier("factuality_unsupported") == "structural"
        assert tier("factuality") == "quality"


class TestSeparation:
    def test_a_metric_that_moves_separates(self):
        verdict = separation(
            {"duplicate_question_rate": 0.02}, {"duplicate_question_rate": 0.40}
        )
        assert verdict["separated"]
        assert verdict["separating_metrics"] == ["duplicate_question_rate"]

    def test_identical_metrics_do_not_separate(self):
        verdict = separation({"generation_rate": 1.0}, {"generation_rate": 1.0})
        assert not verdict["separated"], (
            "two models scoring alike is a finding about the instrument, and "
            "reporting it as a separation is how a blind matrix picks a model"
        )

    def test_a_quality_metric_alone_never_separates(self):
        """Cross-model deltas on judged scores are style artifacts; this repo has
        already paid for a model decision made on one."""
        verdict = separation({"faithfulness": 0.20}, {"faithfulness": 0.90})
        assert not verdict["separated"]
        assert verdict["compared"] == []


def test_every_structural_metric_is_named_not_inferred():
    """Membership is an explicit set, so a new metric is a decision rather than a
    default. A metric that quietly lands in `other` gates nothing."""
    for name in ("duplicate_question_rate", "factuality_reject_rate", "card_reject_rate"):
        assert name in STRUCTURAL
