"""Flashcard prompt strings and system-prompt builders.

Extracted from ``flashcard.py`` so the generation service is not dominated
by prompt boilerplate. Pure module: no I/O, no DB, no LLM calls.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.prompt_spec import (
    NO_FENCES,
    Accommodation,
    PromptSpec,
    render_for,
    step_decomposition,
)

if TYPE_CHECKING:
    from app.models import DocumentModel


FLASHCARD_SYSTEM = (
    "You are a learning assistant that writes flashcards for active recall. Each card is a "
    "self-contained question testing understanding of exactly one idea, plus the shortest "
    "complete answer -- both grounded only in the provided text.\n"
    "QUESTION: match it to the knowledge type -- causal knowledge asks why or what causes; a "
    "comparison asks how two things differ; a role/process asks what X enables in Y; a "
    "definition asks what X is. Name the concept directly and prefer why/how/apply over recall. "
    "AVOID trivia about wording, yes/no questions, answers that are a bare list, and asking "
    "which specific example or analogy the text used. The question must stand alone -- never "
    "say 'in this passage', 'according to the text', or 'the author'; it must make sense "
    "without the source.\n"
    "ANSWER: one sentence, the shortest that is still complete. If the text lists several "
    "items, write one card per item rather than one card listing them -- an answer carrying a "
    "list is several cards wearing a single question, and it is the hardest kind to recall. "
    "Two sentences only when the question compares two things and both sides must be stated. "
    "Every claim must be supported by the text: if you cannot point at the sentence that "
    "backs it, leave it out. No filler, no chapter/section reference.\n"
    'Include a "bloom_level" integer 1-6 (1=remember ... 6=create); aim for level 3+ '
    "(apply/analyze/evaluate) where the material allows."
)

# The user-side flashcard prompt as a contract plus its compensations. Rendering
# it reproduces FLASHCARD_USER_TMPL exactly today: both accommodations still
# apply, because nothing has measured that any model can go without them. The
# separation is what makes deleting one an audit rather than a guess.
FLASHCARD_USER_SPEC = PromptSpec(
    task="flashcards",
    contract=(
        "Write {count} {difficulty}-level flashcards from the text below.\n"
        "Difficulty: {difficulty_guidelines}\n"
        "{extra_instructions}"
        "Return a JSON object:\n"
        '{{"flashcards": [{{"question": "...", "answer": "...", "source_excerpt": "...", '
        '"bloom_level": N}}]}}'
    ),
    accommodations=(
        Accommodation(
            id="json_escape_hint",
            kind="format",
            text="Use '\\n' for line breaks inside a string.",
            introduced_for="ollama/llama3.2",
            because=(
                "raw newlines inside JSON strings made the completion unparseable, "
                "which the tolerant parser then repaired silently"
            ),
            drop_when=(
                "the model emits schema-valid JSON natively, or the measured "
                "bad_escape repair count is zero across a matrix run"
            ),
        ),
        Accommodation(
            id="atomic_answer_example",
            kind="example",
            text=(
                "Example card:\n"
                '{{"flashcards": [{{"question": "Why do independent hardware faults need a '
                'different defence from systematic software errors?", "answer": "Hardware '
                "faults are largely independent so redundancy can mask them, while software "
                'errors are correlated and can fail many nodes at once.", '
                '"source_excerpt": "", "bloom_level": 4}}]}}'
            ),
            introduced_for="ollama/qwen3.5:4b",
            because=(
                "it replaces `worked_example`, which existed to turn one-sentence "
                "answers into multi-point bulleted ones. That was the wrong target: "
                "rules 4, 9 and 10 of the card-writing canon make a list the primary "
                "defect in a card, and the measured atomicity floor was 0.7778 with "
                "the old example in place"
            ),
            drop_when=(
                "atomicity holds at 1.0 across a matrix run without it -- an example "
                "sets the register a model regresses toward, in either direction"
            ),
        ),
    ),
)

def flashcard_user_tmpl() -> str:
    """The user prompt, rendered for the model that will generate the cards."""
    return render_for(FLASHCARD_USER_SPEC, "generation") + "\nText:\n{text}\n\nJSON object:"

NOTES_CONCEPT_EXTRACT_SPEC = PromptSpec(
    task="concepts",
    contract=(
        "You are a learning analyst. Given a learner's notes, identify the primary "
        "subject domain and extract atomic, learnable concepts about it. "
        "The domain is what the learner is actively trying to understand or remember. "
        "It is never the setting, date, location, or context in which the notes were written. "
        "A concept must be an insight, claim, argument, principle, or relationship within "
        "the domain. "
        "STRICT GROUNDING: extract only what is explicitly stated or directly implied by "
        "the notes. Never introduce knowledge from outside the notes. "
        "REJECT any concept that is about: "
        "the physical setting (weather, environment, location, surroundings); "
        "people or events incidental to the subject; "
        "bare enumerations with no explanatory content; "
        "meta-commentary about the notes. "
        "For each accepted concept, assign a type: "
        "causal-claim, comparison, process-role, factual-definition, or speculative-claim. "
        'Output a JSON object with keys "domain" (string) and '
        '"concepts" (array of {"concept": "...", "type": "..."}).'
    ),
    accommodations=(
        step_decomposition(
            "Work in two steps: STEP 1 -- DOMAIN, then STEP 2 -- CONCEPTS.",
            introduced_for="ollama/llama3.2",
            because=(
                "without an explicit first step the domain was inferred from the "
                "notes' setting -- the weather and the place -- rather than their "
                "subject, and every concept followed it"
            ),
        ),
        NO_FENCES,
    ),
)

def notes_concept_extract_system() -> str:
    return render_for(NOTES_CONCEPT_EXTRACT_SPEC, "generation")

NOTES_CONCEPT_EXTRACT_TMPL = (
    "Identify the domain and extract up to {max_concepts} learnable concepts from these notes.\n\n"
    "Notes:\n{text}\n\n"
    "JSON object:"
)

NOTES_CARD_FROM_CONCEPTS_SYSTEM = (
    "You are a flashcard designer. You receive a subject domain, a list of typed concepts, "
    "and the original notes they were drawn from. "
    "DOMAIN GATE: only generate cards for concepts that are directly about the stated domain. "
    "Skip any concept outside the domain even if it appears in the notes. "
    "GROUNDING GATE: only generate a card if the answer can be written using the notes alone. "
    "If the notes do not contain sufficient information, skip that concept. "
    "Never hallucinate or use external knowledge. "
    "The question structure MUST match the knowledge type: "
    "causal-claim -> ask why X leads to Y, or what causes X; "
    "comparison -> ask how X and Y differ, or what distinguishes X from Y; "
    "process-role -> ask what X collectively enables or achieves within Y "
    "(not: list the components of X); "
    "factual-definition -> ask what X is or what characterises X; "
    "speculative-claim -> ask what the argument or reasoning behind X is. "
    "The question must name the specific concept directly. "
    "NEVER use context-dependent words: 'this scenario', 'the scenario', 'this situation', "
    "'this case', 'this context', 'this example', 'the author', 'the text', 'these notes', "
    "'the man', 'the person', 'the writer'. "
    "The question must stand alone -- understandable without the notes. "
    "Answer from the notes: lead with one direct sentence, then add short markdown bullets "
    "('- ...') only for several distinct points. Never a bare list; never filler. "
    "For process-role: explain what the collective activity achieves or why it matters -- "
    "never enumerate the individual components as the answer. "
    'Output ONLY a JSON array: [{{"question": "...", "answer": "...", "source_excerpt": ""}}]. '
    "No explanation, no preamble, no markdown fences."
)

NOTES_CARD_FROM_CONCEPTS_TMPL = (
    "Subject domain: {domain}\n"
    "Difficulty: {difficulty}. {difficulty_guidelines}\n\n"
    "Concepts:\n{concepts_json}\n\n"
    "Notes:\n{text}\n\n"
    "JSON array:"
)

_DIFFICULTY_GUIDELINES = {
    "easy": (
        "Focus on basic recall, key characters, main plot points, and obvious facts. "
        "Questions should be straightforward."
    ),
    "medium": (
        "Focus on comprehension, connecting ideas, identifying themes, and explaining 'why'. "
        "Questions should require some thought and understanding."
    ),
    "hard": (
        "Focus on analysis, evaluation, complex relationships, subtle themes, and application "
        "to new contexts. Questions should be challenging and require deep insight."
    ),
}

_BOOK_CONTENT_GUIDELINE = (
    "IMPORTANT: Focus exclusively on the primary narrative or subject matter "
    "(story, characters, plot, themes, or core arguments). "
    "STRICTLY AVOID generating any flashcard about: "
    "Project Gutenberg, publication details, copyright notices, licensing, "
    "translators, editors, publishers, prefaces, forewords, introductions, "
    "the purpose of publishing the work, or any other front/back matter. "
    "These are irrelevant to learning the content and must be completely ignored. "
    "If the provided text starts with publisher boilerplate or editorial notes, "
    "skip past them entirely and generate questions only from the actual narrative or subject.\n"
)

TECH_FLASHCARD_SYSTEM = (
    "You are a technical learning assistant creating flashcards based on Bloom's Taxonomy. "
    "For each card choose exactly one of these flashcard types: "
    "definition (L1), syntax_recall (L1), concept_explanation (L2), analogy (L2), "
    "code_completion (L3), api_signature (L3), trace (L4), pattern_recognition (L4), "
    "design_decision (L5), complexity (L5), implementation (L6). "
    "Choose the type that best matches what the card asks the learner to do. "
    "For code_completion cards: show a code block with a blank rendered as ____ where the "
    "learner must supply the missing part. "
    "For trace cards: show a code snippet and ask the learner to predict its output. "
    "For design_decision cards: ask the learner to justify a technical choice. "
    "For complexity cards: ask the learner to state and justify Big-O for an algorithm. "
    "Questions must be self-contained. "
    "NEVER use phrases like 'in this passage' or 'in this text'. "
    "Output a JSON array starting with [ and ending with ]. "
    'Each element: {"question": "...", "answer": "...", '
    '"source_excerpt": "...", "flashcard_type": "...", "bloom_level": N}. '
    "bloom_level is an integer 1-6. "
    "Write no explanation, preamble, or markdown fences."
)

TECH_FLASHCARD_USER_TMPL = (
    "Generate {count} technical flashcards from the text below.\n"
    "Prefer higher Bloom levels (trace, code_completion, design_decision) when the text "
    "contains code blocks, API signatures, or trade-off discussions.\n"
    "When the section heading contains 'vs' or 'trade-off', generate at least one "
    "design_decision card (bloom_level=5).\n"
    "When the text contains an admonition type of 'warning', generate at least one "
    "definition card (bloom_level=1) that captures the warning.\n"
    "Each card must be answerable from the provided text only.\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "...", '
    '"flashcard_type": "...", "bloom_level": N}}]\n\n'
    "Section heading: {section_heading}\n"
    "Has code blocks: {has_code}\n"
    "Admonition type: {admonition_type}\n\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)


GAP_FLASHCARD_SYSTEM = (
    "You are a learning assistant. Generate exactly ONE flashcard for the given knowledge gap. "
    'Output ONLY a JSON object with two keys: {"front": "...", "back": "..."} '
    "where 'front' is the question and 'back' is a concise answer. "
    "Write no explanation, preamble, or markdown fences. Output only the JSON object."
)

GAP_FLASHCARD_USER_TMPL = (
    'Knowledge gap: "{gap}"\n\n'
    'Generate one flashcard as JSON: {{"front": "question", "back": "answer"}}'
)

GRAPH_FLASHCARD_SYSTEM = (
    "You are a learning assistant creating flashcards that test understanding of relationships "
    "between concepts. Each question must ask how two named entities are connected, "
    "what one entity means in the context of the other, "
    "or what role one plays relative to the other. "
    "NEVER frame a question as a definition question ('What is X?'). "
    "NEVER use phrases like 'in this passage' or 'according to this text'. "
    "Questions must be self-contained. "
    "Output a JSON array starting with [ and ending with ]. "
    "Write no explanation, preamble, or markdown fences."
)

GRAPH_FLASHCARD_USER_TMPL = (
    "Entity A: {name_a}\n"
    "Entity B: {name_b}\n"
    "Relationship hint: {relation_label}\n\n"
    "Context passages:\n{context}\n\n"
    "Generate {count} flashcard(s) testing the relationship between '{name_a}' and '{name_b}'.\n"
    "Each question must be framed as a relationship question "
    "('How does X relate to Y?', 'What connects X and Y?', 'What role does X play in Y?').\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "..."}}]\n'
    "JSON array:"
)


CLOZE_SYSTEM = (
    "You are a learning assistant creating cloze deletion (fill-in-the-blank) flashcards. "
    "Extract 3-5 key technical terms or concepts from the section text. "
    "For each term, produce a sentence that embeds the term using {{term}} syntax. "
    "Each sentence must make sense without the blank and use one or two blanks only. "
    "Output a JSON array starting with [ and ending with ]. "
    'Each element: {"cloze_text": "...", "source_excerpt": "..."}. '
    "cloze_text uses {{term}} markers. source_excerpt is a verbatim passage from the text. "
    "Write no explanation, preamble, or markdown fences."
)

CLOZE_USER_TMPL = (
    "Generate {count} cloze deletion cards from the text below.\n"
    "Each card must contain at least one {{{{term}}}} blank. "
    "Use exactly one or two blanks per sentence.\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)


_TECH_TITLE_KEYWORDS = re.compile(
    r"\b(programming|systems|distributed|database|algorithm|machine learning"
    r"|deep learning|neural|artificial intelligence|reinforcement learning"
    r"|data science|data structures|statistics|mathematics"
    r"|software|engineering|computer|kubernetes|docker|linux|network|security"
    r"|operating system)\b",
    re.IGNORECASE,
)


# What to ask of each kind of material. Distilled from the card-writing canon
# (SuperMemo's 20 rules, which Anki's manual defers to) and pointed at the failure
# each kind actually shows: narrative cards drift into "which word was used",
# technical cards into restating prose instead of the rule, academic cards into
# "who wrote it", and transcript cards into facts that go stale unread.
_GENRE_STRATEGY = {
    "narrative": (
        "Ask about cause and consequence, what a character wanted, or what a choice cost. "
        "Never ask which words the text used or which example illustrated a point."
    ),
    "non-fiction": (
        "Ask what a claim asserts, why it holds, and what it rules out."
    ),
    "technical": (
        "Ask the invariant, the failure mode, when one option beats another, and what a "
        "parameter controls. Where the text gives syntax, a signature or a formula, quote "
        "its exact form in the answer rather than describing it."
    ),
    "academic": (
        "Ask what was claimed, how it was measured, what the evidence was, and what "
        "limitation the work states. Never ask who wrote it or where it was published."
    ),
    "conversation": (
        "Ask what was decided, who owns it, and why the alternative was rejected. Anything "
        "that will go stale -- a date, a version, a headcount -- must carry its date in the "
        "answer so a card reviewed months later is still checkable."
    ),
}


def _infer_genre(doc: DocumentModel | None) -> str:
    """Infer document genre for system prompt tuning.

    Technical content types (tech_book, tech_article, code, paper) MUST map to technical/academic.
    They previously fell through to 'narrative' (the story prompt), so the model summarised or
    extracted tables instead of writing recall cards.
    """
    if doc is None:
        return "non-fiction"
    content_type = (doc.content_type or "").lower()
    # normalise underscores so slugged titles ("d2l_dive_into_deep_learning") match
    title = (doc.title or "").lower().replace("_", " ")
    if content_type in ("tech_book", "tech_article", "code"):
        return "technical"
    if content_type in ("paper", "pdf", "web", "article"):
        return "academic"
    if content_type == "book":
        return "technical" if _TECH_TITLE_KEYWORDS.search(title) else "non-fiction"
    # A transcript's value is the decision and its owner, which the non-fiction
    # prompt does not ask for; it also holds the most volatile facts in a library.
    if content_type in ("conversation", "transcript", "meeting", "audio", "video"):
        return "conversation"
    # notes / unknown: non-fiction recall prompt is safer than narrative
    return "non-fiction"


def _build_genre_system_prompt(genre: str) -> str:
    """The single flashcard system prompt plus what to ask of this kind of material.

    One source of truth (FLASHCARD_SYSTEM) drives generation. The genre block used
    to be the sentence "This is a {genre} document.", which named the material and
    asked for nothing: cards from a meeting transcript and cards from a textbook
    came out the same shape. Each strategy below says what a good card *asks* for
    that kind, which is the part a model cannot infer from the label.
    """
    article = "an" if genre[:1] in "aeiou" else "a"
    label = f"This is {article} {genre} document. " if genre != "narrative" else ""
    strategy = _GENRE_STRATEGY.get(genre, "")
    prefix = f"{label}{strategy}\n" if strategy else label
    return prefix + FLASHCARD_SYSTEM
