"""Every document-scoped table is either cascaded on delete or declared exempt.

`section_summaries` was missing from the cascade for as long as it has existed:
the dev database carried 1,956 orphan rows, summary text belonging to documents
that had been deleted. Seven more tables with a `document_id` column were in the
same position, and the omission was invisible because the cascade list was typed
out by hand and never checked against the models.

Deriving the list from the models is what turns the next omission into a decision.
A new table with a `document_id` now fails this test until someone says which it
is: cascaded, special-cased, or part of the learner record that outlives the
document.
"""

from app.models import Base
from app.services.document_deletion_service import (
    _DOCUMENT_ID_CHILD_TABLES,
    _LEARNER_RECORD_TABLES,
    _SPECIAL_CASE_TABLES,
)


def _models_with_document_id() -> set[type]:
    return {
        cls
        for cls in Base.__subclasses__()
        if getattr(cls, "__tablename__", None) is not None
        and "document_id" in cls.__table__.columns
    }


def test_every_document_scoped_table_is_cascaded_or_declared():
    accounted = (
        set(_DOCUMENT_ID_CHILD_TABLES) | set(_SPECIAL_CASE_TABLES) | set(_LEARNER_RECORD_TABLES)
    )
    unaccounted = {cls.__tablename__ for cls in _models_with_document_id() - accounted}
    assert not unaccounted, (
        f"tables carry a document_id but deleting a document ignores them: "
        f"{sorted(unaccounted)}. Add each to _DOCUMENT_ID_CHILD_TABLES, or to "
        f"_LEARNER_RECORD_TABLES if its rows should outlive the document."
    )


def test_declared_tables_still_exist_and_are_document_scoped():
    """A stale entry is as misleading as a missing one."""
    declared = (
        set(_DOCUMENT_ID_CHILD_TABLES) | set(_SPECIAL_CASE_TABLES) | set(_LEARNER_RECORD_TABLES)
    )
    with_doc_id = _models_with_document_id()
    # CollectionMemberModel is keyed on (member_id, member_type) rather than
    # document_id, which is exactly why it is special-cased.
    from app.models import CollectionMemberModel

    for cls in declared - {CollectionMemberModel}:
        assert cls in with_doc_id, (
            f"{cls.__name__} is declared in the deletion cascade but has no "
            f"document_id column"
        )


def test_the_three_lists_do_not_overlap():
    """A table cannot be both deleted and kept."""
    cascaded = set(_DOCUMENT_ID_CHILD_TABLES)
    special = set(_SPECIAL_CASE_TABLES)
    kept = set(_LEARNER_RECORD_TABLES)
    assert not cascaded & kept, sorted(c.__name__ for c in cascaded & kept)
    assert not cascaded & special, sorted(c.__name__ for c in cascaded & special)
    assert not special & kept, sorted(c.__name__ for c in special & kept)
