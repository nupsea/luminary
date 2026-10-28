"""A concept's centroid does not depend on the order its chunks were written in."""

import uuid

from app.services.vector_store import LanceDBService

DOC = str(uuid.uuid4())
CHUNKS = sorted(str(uuid.uuid4()) for _ in range(3))
# In float32, 1e8 + 1 rounds back to 1e8: summed in a different order, the mean differs.
VALUES = dict(zip(CHUNKS, [1e8, 1.0, -1e8], strict=True))


def _write(directory, order: list[str]) -> LanceDBService:
    svc = LanceDBService(directory=directory)
    for chunk_id in order:
        svc.upsert_chunks(
            [
                {
                    "chunk_id": chunk_id,
                    "document_id": DOC,
                    "section_heading": "",
                    "page": 0,
                    "chunk_index": 0,
                    "speaker": "",
                    "text": "t",
                    "vector": [VALUES[chunk_id]] * 384,
                }
            ]
        )
    return svc


def test_the_centroid_is_the_same_whatever_order_the_chunks_were_written(tmp_path):
    ordered = _write(tmp_path / "a", CHUNKS)
    shuffled = _write(tmp_path / "b", [CHUNKS[0], CHUNKS[2], CHUNKS[1]])

    assert ordered.compute_centroid(CHUNKS) == shuffled.compute_centroid(CHUNKS)
