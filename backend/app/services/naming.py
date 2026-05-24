"""Naming convention utilities for tags and collections.

Convention:
  - Collection names: UPPER-CASE, words separated by hyphens (e.g. 'MY-NOTES')
  - Tag slugs: lower-case, words separated by hyphens, '/' preserved (e.g. 'science/biology')
"""

import re


def normalize_collection_name(name: str) -> str:
    """Normalize a collection name to UPPER-CASE with hyphen separators.

    Algorithm: strip whitespace, replace underscores and spaces with hyphens,
    collapse consecutive hyphens, convert to upper case, strip leading/trailing hyphens.

    Examples:
      'my notes'       -> 'MY-NOTES'
      'machine_learning' -> 'MACHINE-LEARNING'
      '  DDIA  Book  '  -> 'DDIA-BOOK'
    """
    s = name.strip()
    if not s:
        return ""
    # Replace underscores and spaces with hyphens
    s = re.sub(r"[_\s]+", "-", s)
    # Collapse consecutive hyphens
    s = re.sub(r"-+", "-", s)
    # Upper case
    s = s.upper()
    # Strip leading/trailing hyphens
    s = s.strip("-")
    return s


def normalize_tag_slug(slug: str) -> str:
    """Normalize a tag slug to lower-case with hyphen separators, preserving '/' hierarchy.

    Algorithm: strip whitespace, split by '/', for each segment replace underscores
    and spaces with hyphens, drop every char outside [a-z0-9-] (after lowercasing),
    collapse consecutive hyphens, strip leading/trailing hyphens per segment.
    Rejoin with '/'. Returns '' if nothing survives.

    Examples:
      'Science/Biology'        -> 'science/biology'
      'Machine Learning'       -> 'machine-learning'
      'science/Cell_Division'  -> 'science/cell-division'
      "person's-name"          -> 'persons-name'
      'thrift:localhost:9083'  -> 'thriftlocalhost9083'   # caller rejects via min-len
      's3:/...'                -> 's3'
      'benjamin,-brandon'      -> 'benjamin-brandon'
    """
    s = slug.strip()
    if not s:
        return ""
    segments = s.split("/")
    normalized: list[str] = []
    for raw_seg in segments:
        part = raw_seg.strip().lower()
        if not part:
            continue
        # Whitespace and underscores -> hyphen.
        part = re.sub(r"[_\s]+", "-", part)
        # Drop anything outside the slug alphabet. This is the tightening:
        # previously colons, dots, commas, apostrophes all slipped through
        # and produced NER artifacts like 'ne-.-role' or 's3:/...' as tags.
        part = re.sub(r"[^a-z0-9-]", "", part)
        # Collapse consecutive hyphens that the drops above may have created.
        part = re.sub(r"-+", "-", part)
        # Strip leading/trailing hyphens.
        part = part.strip("-")
        if part:
            normalized.append(part)
    return "/".join(normalized)
