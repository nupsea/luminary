"""is_junk_entity -- the format-driven noise filter for concept/entity surface forms.

Guards the trust-visible promise: code tokens, CLI flags, source literals, and unicode
styled garbage never reach the doc-overview study view as studyable concepts, while real
mid-level concepts pass untouched.
"""

import pytest

from app.workflows.concept_nodes._shared import is_junk_entity


@pytest.mark.parametrize(
    "label",
    [
        "false",                       # boolean literal
        "true",
        "null",
        "dynamic",                     # generic type keyword
        "--acl-spec",                  # CLI flag
        "-v",
        "unique_files",                # snake_case code identifier
        "rollback_to_timestamp procedure",
        "emp_partitioned_table",
        "𝐆𝐚𝐭𝐞𝐰𝐚𝐲 𝐚𝐠𝐠𝐫𝐞𝐠𝐚𝐭𝐢𝐨𝐧 𝐥𝐚𝐲𝐞𝐫",  # unicode math-alphanumeric garbage
        "123",                         # digit-dominant
        "",                            # empty
        "performance",                 # pre-existing generic stoplist
    ],
)
def test_junk_dropped(label):
    assert is_junk_entity(label) is True


@pytest.mark.parametrize(
    "label",
    [
        "microservices architectures",
        "data lakehouse",
        "iceberg tables",
        "exactly-once delivery semantics",   # hyphen + multiword stays
        "oauth token",
        "graphql federation",
        "statement-based replication",
        "suffix tree",
        "generative ai",
    ],
)
def test_good_concepts_kept(label):
    assert is_junk_entity(label) is False
