"""A locked graph is expected; it must not be reported as a crash.

Reported as "seeing errors after deleting notes": the note deleted fine and a
background reindex simply held the Kuzu lock, but the handler printed a full
stack trace for it. The lock is an OS lock the kernel frees when the holder
exits (I-24), so it is self-resolving and actionable -- not a defect.
"""

import logging

from app.services.graph_connection import GraphDatabaseLockedError
from app.services.note_graph import _log_graph_failure


def _capture(exc):
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("app.services.note_graph")
    handler = _H()
    logger.addHandler(handler)
    try:
        _log_graph_failure("delete_note_node", exc)
    finally:
        logger.removeHandler(handler)
    return records[-1]


def test_locked_graph_logs_without_a_stack_trace():
    rec = _capture(GraphDatabaseLockedError("the graph at /x is locked by another process"))
    assert rec.levelno == logging.WARNING
    assert rec.exc_info is None, "a documented, self-resolving lock printed a stack trace"
    assert "locked" in rec.getMessage()
    assert "delete_note_node" in rec.getMessage()


def test_unexpected_failure_keeps_its_stack_trace():
    """The quiet path is only for the known condition; nothing else is muffled."""
    rec = _capture(RuntimeError("kuzu segfaulted"))
    assert rec.levelno == logging.WARNING
    assert rec.exc_info is not None, "an unexpected graph failure lost its traceback"
