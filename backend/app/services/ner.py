"""EntityExtractor: GLiNER-based zero-shot named entity recognition.

Loads 'urchade/gliner_multi_pii-v1' on first use and caches to DATA_DIR/models/gliner/.
Extracts entities from chunk texts with custom entity types, then applies layered
post-extraction filters to remove pronouns, possessive phrases, generic geographic
terms, bare-number dates, and other common noise patterns from literary/prose text.
"""

import logging
import re
import uuid
from collections import Counter
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

ENTITY_TYPES = [
    "PERSON",
    "ORGANIZATION",
    "PLACE",
    "CONCEPT",
    "EVENT",
    "TECHNOLOGY",
    "DATE",
]

# ---------------------------------------------------------------------------
# Noise-filter constants
# ---------------------------------------------------------------------------

# English pronouns — personal, possessive, reflexive, demonstrative, archaic.
# These should never be extracted as named entities.
_PRONOUNS: frozenset[str] = frozenset({
    # first person
    "i", "me", "my", "mine", "myself",
    "we", "us", "our", "ours", "ourselves",
    # second person
    "you", "your", "yours", "yourself", "yourselves",
    # third person singular
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
    # third person plural
    "they", "them", "their", "theirs", "themselves",
    # relative / interrogative
    "who", "whom", "whose", "which", "what",
    # demonstrative
    "this", "that", "these", "those",
    # indefinite
    "one", "ones", "someone", "anyone", "everyone", "nobody", "somebody",
    # archaic (common in classical literature translations)
    "thee", "thou", "thy", "thine", "ye",
})

# Possessive words that should not open a multi-word entity span.
# e.g. "his father", "my house", "their city" → all noise.
_POSSESSIVE_OPENERS: frozenset[str] = frozenset({
    "his", "her", "my", "our", "your", "their", "its", "thy",
})

# Generic single-word place nouns — meaningful only with a proper modifier.
_GENERIC_PLACES: frozenset[str] = frozenset({
    "area", "avenue", "bay", "beach", "camp", "castle", "cave", "city",
    "coast", "corner", "country", "county", "court", "dale", "district",
    "field", "forest", "hall", "harbor", "hill", "home", "house", "island",
    "lake", "land", "location", "mountain", "nation", "ocean", "palace",
    "passage", "place", "plain", "region", "river", "road", "room", "sea",
    "shore", "spot", "state", "street", "town", "valley", "village", "zone",
})

# Generic single-word organisation nouns — too vague without a proper name.
_GENERIC_ORGS: frozenset[str] = frozenset({
    "agency", "association", "board", "bureau", "club", "committee",
    "company", "corporation", "council", "department", "enterprise",
    "firm", "foundation", "group", "guild", "institution", "ministry",
    "office", "organization", "party", "society", "team", "union",
})

# A DATE must match at least one of these patterns; bare integers are rejected.
_DATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(1[0-9]{3}|20[0-2][0-9])\b"),                        # 1000–2029
    re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
               r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
               r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", re.I),   # month names
    re.compile(r"\b\d+(st|nd|rd|th)\b", re.I),                          # ordinals
    re.compile(r"\b(bc|ad|bce|ce)\b", re.I),                            # era markers
    re.compile(r"\b(century|decade|millennium|millennia)\b", re.I),
    re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I),
    re.compile(r"\b(spring|summer|autumn|fall|winter)\b", re.I),
    re.compile(r"\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b"),              # 12/31/1999
]

# Minimum character length for a single-token entity name.
_MIN_SINGLE_TOKEN_LEN = 3

# Minimum number of chunks a document must span before the frequency filter kicks in.
_FREQ_FILTER_MIN_CHUNKS = 30
# Minimum number of chunk appearances required to survive the frequency filter.
_MIN_CHUNK_FREQ = 2

# Number of chunk texts sent to GLiNER in a single batch_predict_entities call.
# Each batch is one model forward pass — larger batches amortise overhead but use more RAM.
_NER_BATCH_SIZE = 8


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_valid_entity(name: str, entity_type: str) -> bool:
    """Return False for clearly noisy entity candidates."""
    tokens = name.split()
    first = tokens[0] if tokens else ""

    # 1. Pronoun check — covers single-word pronouns and pronoun-only spans
    if name in _PRONOUNS:
        return False
    if len(tokens) == 1 and first in _PRONOUNS:
        return False

    # 2. Minimum length for single-token entities ("it" → 2 chars, slips past pronouns)
    if len(tokens) == 1 and len(name) < _MIN_SINGLE_TOKEN_LEN:
        return False

    # 3. Possessive opener — "his father", "my house", "their city"
    if first in _POSSESSIVE_OPENERS:
        return False

    # 4. Type-specific rules

    if entity_type == "DATE":
        # Bare integers (page numbers, verse numbers, chapter numbers) are not dates
        if re.fullmatch(r"\d+", name):
            return False
        # Must resemble an actual date/time expression
        if not any(p.search(name) for p in _DATE_PATTERNS):
            return False

    elif entity_type == "PLACE" and len(tokens) == 1:
        if name in _GENERIC_PLACES:
            return False

    elif entity_type == "ORGANIZATION" and len(tokens) == 1:
        if name in _GENERIC_ORGS:
            return False

    return True


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_extractor: "EntityExtractor | None" = None


def get_entity_extractor() -> "EntityExtractor":
    global _extractor
    if _extractor is None:
        settings = get_settings()
        _extractor = EntityExtractor(settings.DATA_DIR)
    return _extractor


# ---------------------------------------------------------------------------
# EntityExtractor
# ---------------------------------------------------------------------------

class EntityExtractor:
    _model = None

    def __init__(self, data_dir: str) -> None:
        self._model_dir = Path(data_dir).expanduser() / "models" / "gliner"
        self._model_dir.mkdir(parents=True, exist_ok=True)
        logger.info("EntityExtractor created", extra={"model_dir": str(self._model_dir)})

    def _load_model(self):
        """Lazy-load GLiNER model, caching to DATA_DIR/models/gliner/."""
        if self._model is not None:
            return self._model

        from gliner import GLiNER  # noqa: PLC0415

        logger.info("Loading GLiNER model", extra={"model_dir": str(self._model_dir)})
        self._model = GLiNER.from_pretrained(
            "urchade/gliner_multi_pii-v1",
            cache_dir=str(self._model_dir),
        )
        logger.info("GLiNER model loaded")
        return self._model

    def extract(
        self,
        chunks: list[dict],
        content_type: str = "unknown",
    ) -> list[dict]:
        """Extract named entities from a list of chunk dicts.

        Each chunk dict must have: id (str), document_id (str), text (str).

        Args:
            chunks: Chunk dicts produced by the ingestion pipeline.
            content_type: Document content type (e.g. "code", "book", "paper").
                TECHNOLOGY entities are only extracted for code documents.

        Returns:
            List of entity dicts:
                {id, name (normalized lowercase), type, chunk_id, document_id}
            Noise entities (pronouns, possessives, generic terms, bare-number
            dates) are removed. For documents with many chunks, entities that
            appear in only a single chunk are also dropped.
        """
        model = self._load_model()

        # For non-code documents, TECHNOLOGY is almost always noise (pronouns
        # like "it" are the most common false-positive in that category).
        is_code = content_type == "code"
        active_types = ENTITY_TYPES if is_code else [t for t in ENTITY_TYPES if t != "TECHNOLOGY"]

        # Higher threshold than default 0.5 — reduces low-confidence false positives
        # while retaining genuine entities that GLiNER is confident about.
        threshold = 0.65

        entities: list[dict] = []

        # Strip context headers [Book > Section] before entity extraction.
        # These are injected during chunking for search but are noise for NER.
        header_pattern = re.compile(r"^\[.*? > .*?\]\s*")
        
        valid_chunks = []
        for c in chunks:
            text = c.get("text", "").strip()
            if not text:
                continue
            # Strip header only for NER, don't modify the original chunk dict
            clean_text = header_pattern.sub("", text)
            valid_chunks.append({**c, "text": clean_text})

        total_batches = (len(valid_chunks) + _NER_BATCH_SIZE - 1) // _NER_BATCH_SIZE
        for batch_idx in range(0, len(valid_chunks), _NER_BATCH_SIZE):
            batch = valid_chunks[batch_idx : batch_idx + _NER_BATCH_SIZE]
            texts = [c["text"] for c in batch]

            # One forward pass for all texts in the batch — significantly faster
            # than calling predict_entities per chunk on CPU.
            batch_results = model.batch_predict_entities(texts, active_types, threshold=threshold)

            for chunk, chunk_entities in zip(batch, batch_results):
                chunk_id = chunk["id"]
                doc_id = chunk["document_id"]

                for ent in chunk_entities:
                    name = ent["text"].strip().lower()
                    entity_type = ent["label"]

                    if not name:
                        continue

                    if not _is_valid_entity(name, entity_type):
                        continue

                    entity_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{name}"))
                    entities.append(
                        {
                            "id": entity_id,
                            "name": name,
                            "type": entity_type,
                            "chunk_id": chunk_id,
                            "document_id": doc_id,
                        }
                    )

            done_batches = batch_idx // _NER_BATCH_SIZE + 1
            if done_batches % 10 == 0 or done_batches == total_batches:
                logger.debug(
                    "NER progress: batch %d/%d",
                    done_batches,
                    total_batches,
                    extra={"doc_id": valid_chunks[0]["document_id"] if valid_chunks else ""},
                )

        # Frequency filter: for large documents, single-chunk entities are usually
        # noise (e.g. a pronoun that slipped past the blocklist, or a hapax legomenon
        # from a table-of-contents chunk). Only applied when enough chunks were
        # processed to make frequency a meaningful signal.
        if len(chunks) >= _FREQ_FILTER_MIN_CHUNKS:
            chunk_counts: Counter[str] = Counter(e["id"] for e in entities)
            before = len(entities)
            entities = [e for e in entities if chunk_counts[e["id"]] >= _MIN_CHUNK_FREQ]
            dropped = before - len(entities)
            if dropped:
                logger.info(
                    "Frequency filter dropped %d single-chunk entities (threshold=%d, chunks=%d)",
                    dropped, _MIN_CHUNK_FREQ, len(chunks),
                )

        logger.info(
            "NER complete",
            extra={
                "content_type": content_type,
                "chunks_processed": len(chunks),
                "entities_extracted": len(entities),
                "active_types": active_types,
            },
        )
        return entities
