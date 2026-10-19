"""A question the product suggested is answered from the documents only (#66).

A suggestion on the Odyssey presupposed a framing the book never makes; the
factual prompt answered it from general knowledge under "This is not covered in
your documents, but:", with a confidence chip and five source chips.
"""

from app.runtime.chat_nodes._shared import _RELATIONAL_SYSTEM
from app.runtime.qa_stream import _system_prompt_for
from app.services.qa import QA_FACTUAL_SYSTEM_PROMPT, QA_SYSTEM_PROMPT


def _prompt(system: str, suggested: bool) -> str:
    prompt, _ = _system_prompt_for(
        {"_system_prompt": system},
        direct=False,
        creative=False,
        socratic=False,
        suggested=suggested,
    )
    return prompt


def test_a_suggested_question_gets_the_grounded_prompt():
    assert _prompt(QA_FACTUAL_SYSTEM_PROMPT, suggested=True) == QA_SYSTEM_PROMPT


def test_a_typed_question_keeps_the_general_knowledge_fallback():
    assert _prompt(QA_FACTUAL_SYSTEM_PROMPT, suggested=False) == QA_FACTUAL_SYSTEM_PROMPT


def test_other_intents_are_untouched():
    assert _prompt(_RELATIONAL_SYSTEM, suggested=True) == _RELATIONAL_SYSTEM
