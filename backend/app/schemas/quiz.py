from datetime import datetime

from pydantic import BaseModel, Field

from app.types import (
    QuizConfidence,
    QuizDifficulty,
    QuizKind,
    QuizKinds,
    QuizLevel,
    QuizMode,
    QuizOutcome,
    QuizScopeType,
)


class QuizCreateRequest(BaseModel):
    document_id: str
    scope_type: QuizScopeType = "document"
    # A chapter's or section's id; the document's own id (or nothing) for the whole document.
    scope_ref: str | None = None
    difficulty: QuizDifficulty = "adaptive"
    mode: QuizMode = "practice"
    question_count: int = Field(10, ge=1, le=20)
    question_kinds: QuizKinds = "mixed"


class QuizOption(BaseModel):
    id: str
    text: str
    # Set once the option is revealed: after the answer in practice, after the finish in exam.
    is_correct: bool | None = None
    explanation: str | None = None
    quote: str | None = None
    trap: str | None = None


class QuizAnswerView(BaseModel):
    selected_option_ids: list[str]
    confidence: QuizConfidence | None
    outcome: QuizOutcome
    score: float


class QuizQuestion(BaseModel):
    position: int
    item_id: str
    kind: QuizKind
    level: QuizLevel
    stem: str
    # How many to pick, shown on a multi-answer question except at hard.
    select_count: int | None
    origin: str
    support_check: str
    section_id: str | None
    revealed: bool
    options: list[QuizOption]
    answer: QuizAnswerView | None = None


class QuizCalibration(BaseModel):
    confidence: QuizConfidence
    answered: int
    correct: int


class QuizTrapStat(BaseModel):
    trap: str
    shown: int
    picked: int


class QuizRevisit(BaseModel):
    section_id: str
    heading: str
    missed: int


class QuizResults(BaseModel):
    answered: int
    total: int
    correct: int
    score_pct: float | None
    calibration: list[QuizCalibration]
    traps: list[QuizTrapStat]
    revisit: list[QuizRevisit]
    retake_count: int


class QuizResponse(BaseModel):
    id: str
    document_id: str
    scope_type: QuizScopeType
    scope_ref: str
    difficulty: QuizDifficulty
    mode: QuizMode
    question_count: int
    question_kinds: QuizKinds
    status: str
    error: str | None
    retake_of: str | None
    created_at: datetime
    completed_at: datetime | None
    questions: list[QuizQuestion]
    results: QuizResults | None = None


class QuizAnswerRequest(BaseModel):
    position: int = Field(ge=0)
    selected_option_ids: list[str] = Field(min_length=1)
    confidence: QuizConfidence | None = None
    time_ms: int | None = Field(None, ge=0)


class QuizAnswerResponse(BaseModel):
    outcome: QuizOutcome
    score: float
    # Missed, partly right, or right on a guess: it joins the retake round.
    retake: bool
    # A linked card was reset to `again` (a right answer never extends one).
    card_reset: bool
    question: QuizQuestion


class QuizItemCardResponse(BaseModel):
    flashcard_id: str
    question: str
    answer: str
