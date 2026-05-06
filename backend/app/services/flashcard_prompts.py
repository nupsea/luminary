"""Flashcard prompt strings and system-prompt builders.

Extracted from ``flashcard.py`` so the generation service is not dominated
by prompt boilerplate. Pure module: no I/O, no DB, no LLM calls.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import DocumentModel


FLASHCARD_SYSTEM = (
    "You are a learning assistant creating flashcards for active recall. "
    "Generate questions that test understanding, not surface recall. "
    "Match the question structure to the type of knowledge being tested: "
    "causal knowledge -> ask why or what causes; "
    "comparative knowledge -> ask how two things differ or what distinguishes them; "
    "process or role knowledge -> ask what role X plays in Y or how X enables Y; "
    "definitional knowledge -> ask what X is or what characterises X; "
    "speculative or argued knowledge -> ask what the argument or evidence for X is. "
    "AVOID: list-regurgitation questions whose answer is just an enumeration of items; "
    "trivia about exact wording; yes/no questions; "
    "questions whose answer is not derivable from the provided text. "
    "CRITICAL -- NEVER use deictic or source-referencing words in a question: "
    "'in this passage', 'in this text', 'in this excerpt', 'in this book', "
    "'in this document', 'according to the text', 'as described', 'as stated', "
    "'this scenario', 'the scenario', 'this situation', 'this case', 'this context', "
    "'this example', 'the author', 'the writer'. "
    "These make no sense on a flashcard viewed without the source. "
    "Instead, name the specific concept, entity, technology, or idea directly in the question. "
    "CRITICAL -- question framing must match the answer exactly: "
    "if the answer explains a cause, the question must ask for that cause; "
    "if the answer describes a role, the question must ask for that role. "
    "The answer must be a concise explanation in 1-3 sentences -- never a bare list of items. "
    "Before writing each question, verify: does someone without the source text understand "
    "exactly what is being asked, and does the answer directly satisfy the question? "
    "Output a JSON array starting with [ and ending with ]. "
    "Write no explanation, preamble, or markdown fences."
)

FLASHCARD_USER_TMPL = (
    "Generate {count} {difficulty}-level flashcard pairs from the text below.\n"
    "Difficulty guidelines: {difficulty_guidelines}\n"
    "{extra_instructions}"
    "Each card must be answerable from the provided text only.\n"
    "Format: "
    '[{{"question": "...", "answer": "...", "source_excerpt": "...",'
    ' "bloom_level": N}}]\n'
    "bloom_level is an integer 1-6 "
    "(1=remember, 2=understand, 3=apply, "
    "4=analyze, 5=evaluate, 6=create).\n"
    'The "answer" field may use Markdown (bold, lists) for clarity.\n\n'
    "Text:\n{text}\n\n"
    "JSON array:"
)

NOTES_CONCEPT_EXTRACT_SYSTEM = (
    "You are a learning analyst. Given a learner's notes, your job is two steps. "
    "STEP 1 -- DOMAIN: Identify the primary subject domain of the notes in a single short phrase. "
    "The domain is what the learner is actively trying to understand or remember. "
    "It is never the setting, date, location, or context in which the notes were written. "
    "STEP 2 -- CONCEPTS: Extract atomic, learnable concepts that are directly about that domain. "
    "A concept must be an insight, claim, argument, principle, or relationship within the domain. "
    "STRICT GROUNDING: extract only what is explicitly stated or directly implied by the notes. "
    "Never introduce knowledge from outside the notes. "
    "REJECT any concept that is about: "
    "the physical setting (weather, environment, location, surroundings); "
    "people or events incidental to the subject; "
    "bare enumerations with no explanatory content; "
    "meta-commentary about the notes. "
    "For each accepted concept, assign a type: "
    "causal-claim, comparison, process-role, factual-definition, or speculative-claim. "
    'Output ONLY a JSON object with keys "domain" (string) and '
    '"concepts" (array of {"concept": "...", "type": "..."}). '
    "No explanation, no preamble, no markdown fences."
)

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
    "The answer must be derived from the notes in 1-3 sentences. "
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

# S188: Bloom L3+ instruction appended to the genre system prompt
_BLOOM_L3_INSTRUCTION = (
    "\nBLOOM LEVEL TARGETING: Generate questions at Bloom's Taxonomy Level 3 or higher "
    "(application, analysis, synthesis, evaluation). At least 50% of questions must require "
    "the learner to apply, analyze, or evaluate -- not merely recall or describe. "
    'For each card, include a "bloom_level" integer (1-6) indicating the cognitive level. '
    "ANSWER CITATION: Each answer must reference the section or chapter where the concept "
    "appears (e.g., 'In Chapter XII...', 'In the section on X...'). "
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
    r"|software|engineering|computer|kubernetes|docker|linux|network|security"
    r"|data structures|operating system)\b",
    re.IGNORECASE,
)


def _infer_genre(doc: DocumentModel | None) -> str:
    """Infer document genre for system prompt tuning."""
    if doc is None:
        return "narrative"
    content_type = (doc.content_type or "").lower()
    title = (doc.title or "").lower()
    if content_type == "book":
        if _TECH_TITLE_KEYWORDS.search(title):
            return "technical"
        return "non-fiction"
    if content_type in ("pdf", "web"):
        return "academic"
    return "narrative"


def _build_genre_system_prompt(genre: str) -> str:
    """Build a genre-aware flashcard generation system prompt."""
    genre_hint = f"This is a {genre} document. " if genre != "narrative" else ""
    quality_rules = (
        "QUALITY RULES for concept-focused questions:\n"
        "- Do NOT write questions whose answer is a proper noun drawn from an analogy or "
        "illustrative story used to explain a concept (e.g., do not ask 'What animal did the "
        "author compare X to?').\n"
        "- Questions must be answerable by someone who understands the underlying concept but "
        "has NOT read the specific analogy or illustration.\n"
        "- Prefer 'Explain X in your own words' and 'What is the practical implication of Y' "
        "over 'According to the text, what does Z do'.\n"
        "- Frame questions in terms of WHY or HOW, not WHAT was mentioned in an example.\n"
    )
    return (
        genre_hint + "You are a learning assistant creating flashcards for active recall. "
        "Generate questions that test understanding of core concepts and principles. "
        "Prefer questions that: (1) ask the learner to explain a concept in their own words, "
        "(2) apply a concept to a new situation, "
        "(3) distinguish between similar concepts, "
        "or (4) evaluate a claim or argument. "
        "AVOID: trivia questions about exact wording, hypothetical questions not grounded "
        "in the content, questions whose answer is not in the text, yes/no questions. "
        "CRITICAL -- questions must be fully self-contained. "
        "NEVER use phrases like 'in this passage', 'according to this text', 'in this excerpt', "
        "'in this book', 'in this document', or any similar reference to the source material. "
        "A flashcard question must make complete sense on its own without seeing the original"
        " text. " + quality_rules + "Output a JSON array starting with [ and ending with ]. "
        "Write no explanation, preamble, or markdown fences."
    )
