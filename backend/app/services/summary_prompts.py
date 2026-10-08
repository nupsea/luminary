"""The instructions every summary is generated under. Pure: no I/O, no settings."""

from app.types import DocumentProfile

# Grounding prefix applied to every summarization prompt
GROUNDING_PREFIX = "Answer using only information present in the provided text."

_MARKDOWN_INSTRUCTION = (
    "Format your response using Markdown. "
    "Use ## headings, **bold**, bullet lists, and `code` spans where appropriate."
)

# Mode-specific instructions appended after the grounding prefix
MODE_INSTRUCTIONS: dict[str, str] = {
    "one_sentence": "Summarize in a single sentence of at most 30 words.",
    # Written for a reader deciding to start the work: abstract "themes" alone
    # told them neither what it is about nor who and what it involves.
    "executive": (
        "Write the key points a curious reader needs before starting this work. "
        "Open with one or two plain sentences saying what the work is about: its "
        "subject, premise or central question. "
        "Then give 5 to 8 bullet points covering its main events, ideas or arguments, "
        "drawn from the beginning, middle and end of the work, not only its opening. "
        "Name the specific people, places, concepts and terms the work is built on. "
        "State only what the text says; do not interpret beyond it. "
        "Do NOT list chapter or passage summaries one by one — synthesise across them. "
        "Ignore copyright notices, licensing terms, and distribution metadata. "
        "Format your response using Markdown: a short paragraph, then a bullet list "
        "with **bold** for names and terms. No headings."
    ),
    "detailed": (
        "Summarize each section separately, preserving the heading structure. "
        f"{_MARKDOWN_INSTRUCTION}"
    ),
    "conversation": (
        'Output a JSON object with keys: "timeline" (list of strings), '
        '"decisions" (list of strings), '
        '"action_items" (list of objects with "owner" and "task" keys).'
    ),
    # A recorded talk has no decisions and no owners. Asking for them returns
    # empty lists, which is why this mode was hidden from anything but a
    # meeting rather than adapted (#104).
    "conversation_talk": (
        'Output a JSON object with keys: "timeline" (list of strings), '
        '"points" (list of strings: the techniques, tools and claims covered), '
        '"references" (list of strings: anything named that a listener would '
        "look up afterwards)."
    ),
}

MAP_SYSTEM_PROMPT = f"{GROUNDING_PREFIX}\n\nSummarize this passage concisely in 2-3 sentences."

_METADATA_IGNORE = (
    "Ignore any copyright notices, licensing terms, distribution metadata, "
    "publisher boilerplate, or digitisation project information. "
    "Focus only on the intellectual and narrative content of the works."
)

# System prompts for library-level synthesis
LIBRARY_SYSTEM_PROMPTS: dict[str, str] = {
    "one_sentence": (
        f"Synthesize all documents in one sentence of at most 30 words. {_METADATA_IGNORE}"
    ),
    "executive": (
        "List the 5-7 key themes across all documents as bullet points. "
        "Focus on intellectual content, ideas, arguments, and narratives. "
        f"Note connections between them. {_METADATA_IGNORE} {_MARKDOWN_INSTRUCTION}"
    ),
    "detailed": (
        "Write a structured overview: main themes, key documents, "
        f"and how they relate to each other. {_METADATA_IGNORE} {_MARKDOWN_INSTRUCTION}"
    ),
}

# What to say about each kind of document, appended to the mode instruction.
# One instruction for all of them asked a conference talk for "character arcs"
# and lost every tool it named (#105). Keyed on the facets, not content_type:
# a manual and a novel are both "book".
_FORM_GUIDANCE: dict[str, str] = {
    "prose": (
        "Focus on what the work argues or recounts, and name the people, places "
        "and specific subjects it is about."
    ),
    "article": "Focus on the claim being made and the specific things it is about.",
    "reference": (
        "Name the specific rules, components, commands and parameters the work "
        "defines. A reader uses this to decide what to look up, so a named thing "
        "is worth more than a description of it."
    ),
    "paper": (
        "Name what was measured, the method, the finding, and the limitation the "
        "work states. Keep figures and named methods exactly as written."
    ),
    "dialogue": (
        "Name the specific systems, tools and decisions discussed, and who owns "
        "them. Anything that will go stale -- a version, a date, a number -- "
        "carries its date."
    ),
    "entries": "Name the recurring subjects across entries rather than retelling each one.",
    "script": "Focus on what happens and what the characters want.",
    "source_code": "Name the functions, types and responsibilities the file defines.",
}

_NARRATIVE_GUIDANCE = (
    "Focus on what happens, what the characters want, and what their choices "
    "cost. Name the people and places that carry the story."
)

# The specific failure was abstraction: "configuration files" for `agents.md`.
_TECHNICAL_GUIDANCE = (
    "Preserve exact names: files, commands, libraries, parameters, metrics and "
    "tools. Never replace a named thing with the category it belongs to."
)


def _kind_guidance(profile: DocumentProfile | None) -> str:
    """The sentence that tells the model what this kind of document is for."""
    if profile is None:
        return ""
    if profile.form in ("prose", "article") and profile.register == "narrative":
        parts = [_NARRATIVE_GUIDANCE]
    else:
        parts = [_FORM_GUIDANCE.get(profile.form, "")]
    if profile.is_technical:
        parts.append(_TECHNICAL_GUIDANCE)
    return " ".join(p for p in parts if p)


def build_system_prompt(mode: str, profile: DocumentProfile | None = None) -> str:
    """The grounding prefix, the mode instruction, and what this kind wants.

    `conversation` asks for a JSON object; prose guidance would invite
    commentary around it.
    """
    if mode == "conversation" and profile is not None and profile.is_technical:
        mode = "conversation_talk"
    prompt = f"{GROUNDING_PREFIX}\n\n{MODE_INSTRUCTIONS[mode]}"
    if mode.startswith("conversation"):
        return prompt
    guidance = _kind_guidance(profile)
    return f"{prompt} {guidance}" if guidance else prompt
