"""direct_node — handles questions sent directly to the model without retrieval."""

import logging

from app.types import ChatState

logger = logging.getLogger(__name__)


async def direct_node(state: ChatState) -> dict:
    """Prepare prompt for direct model questioning without library context.

    Skips retrieval entirely. Formats conversation history if present,
    sets _llm_prompt to the direct question (with prior dialogue), and sets
    citations and context to empty.
    """
    question = state["question"]
    conversation_history = state.get("conversation_history") or []

    history_block = ""
    if conversation_history:
        all_lines: list[str] = []
        for msg in conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            label = "User" if role == "user" else "Assistant"
            all_lines.append(f"{label}: {content}")
        # Keep as many lines as fit within ~385 words (~500 tokens), prioritizing recent turns
        lines_to_include: list[str] = []
        word_count = 0
        for line in reversed(all_lines):
            words = len(line.split())
            if word_count + words > 385:
                break
            lines_to_include.insert(0, line)
            word_count += words
        if lines_to_include:
            history_block = "Prior conversation (most recent last):\n" + "\n".join(lines_to_include)

    if history_block:
        prompt = f"{history_block}\n\nQuestion: {question}"
    else:
        prompt = question

    logger.info("direct_node: direct prompt prepared for question=%r", question[:60])

    return {
        "_llm_prompt": prompt,
        "_system_prompt": None,
        "chunks": [],
        "section_context": None,
        "answer": "",
        "citations": [],
        "source_citations": [],
        "cited_chunks": [],
        "confidence": "high",
        "not_found": False,
        "transparency": None,
        "image_ids": [],
        "web_snippets": [],
        "web_calls_used": 0,
        "primary_strategy": "direct",
    }
