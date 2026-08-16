"""A prompt is a contract plus the compensations a particular model still needs.

Luminary could not tell an invariant of the domain from an accommodation for a
model: both were prose in the same string, with the same authority. So
accommodations never expired, and one that never expires is a ceiling — the
prompts are written for the weakest model and every model inherits the crutches,
which is one of the four mechanisms that flattened the last model comparison.

A `PromptSpec` separates the two:

  contract        what the task wants, stated once and true of every model.
  accommodations  each one typed, attributed to the model it was added for, with
                  the observation that justified it and the condition under which
                  it can go.

`render(spec, profile)` emits the contract plus only what that model still needs.
Today that is everything: no registry entry has `accommodations_measured` set,
because Phase 6 has not run, and unmeasured means keep. The shortcut that looked
available — dropping format policing for a model that declares
`supports_json_schema` — is measurably wrong: that flag is set on
qwen2.5:14b-instruct, which wrapped every one of 40 flashcard generations in
prose.

The bright line for tagging, when it is unclear whether something is an
accommodation: anything that exists because of observed model behaviour rather
than a product requirement is an accommodation. If nobody can name the
observation, it is dead code — delete it rather than tag it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.model_registry import ModelProfile

AccommodationKind = Literal[
    # English that polices output format: "return only JSON", escape hints.
    "format",
    # A worked example. Carries the register of whatever it was written from,
    # which a stronger model regresses toward.
    "example",
    # If-then rules the model should be deciding for itself.
    "routing",
    # STEP 1 / STEP 2 decomposition of a task the model could plan.
    "decomposition",
]


@dataclass(frozen=True)
class Accommodation:
    id: str
    kind: AccommodationKind
    text: str
    # The model whose behaviour prompted it. Names a model, never "local models".
    introduced_for: str
    # The observation. An accommodation nobody can justify is dead code.
    because: str
    # When it can be removed, in terms someone can check.
    drop_when: str

    def needed_by(self, profile: ModelProfile | None) -> bool:
        """Whether this model still needs it.

        Kept unless the matrix has run against this model AND found it
        unnecessary. A capability flag is not evidence about behaviour:
        qwen2.5:14b-instruct declares `supports_json_schema` and still wrapped
        every one of 40 flashcard generations in prose. What a model can do and
        what it does are different measurements, and only the second licenses
        removing a compensation.
        """
        if profile is None or not profile.accommodations_measured:
            return True
        return self.id in profile.accommodations_needed


@dataclass(frozen=True)
class PromptSpec:
    """What the task wants, and what each model needs to deliver it."""

    task: str
    contract: str
    accommodations: tuple[Accommodation, ...] = field(default_factory=tuple)

    def for_profile(self, profile: ModelProfile | None) -> tuple[Accommodation, ...]:
        return tuple(a for a in self.accommodations if a.needed_by(profile))


# Compensations that appear in five or more prompts. Declared once: they are one
# accommodation with one observation behind them, and copying the sentence into
# every prompt is what made them look like part of each task's contract.

NO_FENCES = Accommodation(
    id="no_fences",
    kind="format",
    text="No explanation, no preamble, no markdown fences.",
    introduced_for="ollama/llama3.2",
    because=(
        "local models wrap JSON in prose or a ```json fence; measured on "
        "qwen2.5:14b-instruct, 40 of 40 flashcard generations needed the "
        "surrounded_by_prose repair"
    ),
    drop_when="the matrix shows the raw parse rate holding without it",
)


def tag_spec(subject: str) -> PromptSpec:
    """The tagging prompt, one spec for documents and notes.

    These were the same sentence twice, differing only in the noun, so the
    format policing had to be changed in two files or the two drifted.
    """
    return PromptSpec(
        task=f"tags_{subject}",
        contract=(
            f"You are a tagging assistant. Given a {subject}, suggest up to 5 short, "
            "lowercase tags that best describe its topics. Tags should be 1-3 words, "
            "no punctuation. Output a JSON array of strings."
        ),
        accommodations=(
            Accommodation(
                id="tag_example",
                kind="example",
                text='For example: ["machine learning", "python"].',
                introduced_for="ollama/llama3.2",
                because="tags came back as a prose sentence rather than a JSON array",
                drop_when="the matrix shows schema conformance holding without it",
            ),
            NO_FENCES,
        ),
    )


def step_decomposition(text: str, *, introduced_for: str, because: str) -> Accommodation:
    """A STEP 1 / STEP 2 breakdown of a task the model could plan itself."""
    return Accommodation(
        id="step_decomposition",
        kind="decomposition",
        text=text,
        introduced_for=introduced_for,
        because=because,
        drop_when="the matrix shows the same output quality from the contract alone",
    )


def render(spec: PromptSpec, profile: ModelProfile | None) -> str:
    """The prompt this model gets: the contract, then only what it still needs."""
    parts = [spec.contract.rstrip()]
    parts.extend(a.text.strip() for a in spec.for_profile(profile))
    return "\n".join(p for p in parts if p) + "\n"


def describe(spec: PromptSpec, profile: ModelProfile | None) -> list[dict[str, str]]:
    """Each accommodation and whether this model gets it.

    What `make prompt-dump` prints. The refactor makes the real prompt exist only
    at runtime, which is a genuine loss for anyone doing prompt work; this is the
    replacement, and it ships with the refactor rather than after it.
    """
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "applied": "yes" if a.needed_by(profile) else "no",
            "introduced_for": a.introduced_for,
            "because": a.because,
            "drop_when": a.drop_when,
        }
        for a in spec.accommodations
    ]
