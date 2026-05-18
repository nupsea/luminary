"""Pydantic schemas for FastAPI request/response bodies.

Schemas live here (rather than alongside routers) so they can be reused
across multiple routers and shared with tests without pulling in
endpoint code.
"""
