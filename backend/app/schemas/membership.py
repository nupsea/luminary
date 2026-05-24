"""Lightweight reference schemas shared across documents/notes list responses.

Both /documents and /notes return membership-chip data so cards can render
"In Collection X · Y" affordances without a follow-up fetch (plan 2E.5).
Putting the ref shape here keeps the OpenAPI schema deduplicated, which in
turn gives the frontend a single generated TypeScript type to consume.
"""

from pydantic import BaseModel


class CollectionRef(BaseModel):
    id: str
    name: str
    color: str
