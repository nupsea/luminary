"""direct_node — handles questions sent directly to the model without retrieval."""

import logging
import re

from app.services.youtube_downloader import is_youtube_url
from app.types import ChatState

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)

# Words that make the link's content the subject ("blog for this video", "summarize
# <url>"); "write a curl for <url>" uses the URL as an operand and still reaches the model.
_CONTENT_REQUEST_RE = re.compile(
    r"\b(summar\w*|recap|tl;?dr|blog|article|post|transcri\w*|watch\w*|video|podcast|"
    r"episode|lecture|talk|explain|describe|review|analy[sz]\w*|takeaways?|key points|"
    r"notes|outline|about|says?|covers?|content)\b",
    re.IGNORECASE,
)


def unreadable_link(question: str) -> str | None:
    """The first URL whose content the question asks about, which Direct mode cannot open."""
    urls = [u.rstrip(".,;:!?)]'\"") for u in _URL_RE.findall(question)]
    if not urls:
        return None
    for url in urls:
        if is_youtube_url(url):
            return url
    if _CONTENT_REQUEST_RE.search(_URL_RE.sub(" ", question)):
        return urls[0]
    return None


def _link_refusal(url: str) -> str:
    return (
        f"I can't open links, so I haven't seen what's at {url} and anything I wrote "
        "about it would be made up. Add it to your library with Add Content → Web URL "
        "(videos are transcribed), then ask again with Direct off and the answer will "
        "come from its actual content, with citations."
    )


async def direct_node(state: ChatState) -> dict:
    """Prepare prompt for direct model questioning without library context.

    Skips retrieval entirely. Formats conversation history if present,
    sets _llm_prompt to the direct question (with prior dialogue), and sets
    citations and context to empty. A question about a link's content gets a
    fixed reply pointing at library ingestion instead of a model call.
    """
    question = state["question"]
    link = unreadable_link(question)
    if link:
        # No model call: the model sees only the URL string and invents its content.
        logger.info("direct_node: question asks about an unopened link %r", link[:80])
        return {**_empty_result(), "_llm_prompt": None, "answer": _link_refusal(link)}

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

    return {**_empty_result(), "_llm_prompt": prompt}


def _empty_result() -> dict:
    return {
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
