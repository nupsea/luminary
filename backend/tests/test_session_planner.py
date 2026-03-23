"""Tests for S101: _build_session_plan() pure function and GET /study/session-plan endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.study import _build_session_plan

# ---------------------------------------------------------------------------
# (a) Review item appears first and is prioritized when due_count > 0
# ---------------------------------------------------------------------------


def test_build_plan_review_priority():
    """due_count=5, no gaps, no docs -> first item is type='review' with title containing '5'."""
    items = _build_session_plan(due_count=5, gap_areas=[], recent_doc_titles=[], budget_minutes=20)
    assert len(items) >= 1
    assert items[0].type == "review"
    assert "5" in items[0].title
    assert items[0].minutes == min(10, max(5, 5 // 2))  # min(10,max(5,2)) = 5


def test_build_plan_review_minutes_capped():
    """due_count=30 -> minutes capped at 10."""
    items = _build_session_plan(due_count=30, gap_areas=[], recent_doc_titles=[], budget_minutes=20)
    assert items[0].type == "review"
    assert items[0].minutes == 10


def test_build_plan_review_minutes_floor():
    """due_count=1 -> minutes floored at 5 (max(5, 1//2)=max(5,0)=5)."""
    items = _build_session_plan(due_count=1, gap_areas=[], recent_doc_titles=[], budget_minutes=20)
    assert items[0].type == "review"
    assert items[0].minutes == 5


# ---------------------------------------------------------------------------
# (b) Total items capped at 5
# ---------------------------------------------------------------------------


def test_build_plan_caps_at_5():
    """due_count=1, 3 gap areas, 1 doc -> total items <= 5."""
    items = _build_session_plan(
        due_count=1,
        gap_areas=["g1", "g2", "g3"],
        recent_doc_titles=[("id1", "Doc A")],
        budget_minutes=20,
    )
    assert len(items) <= 5


def test_build_plan_max_2_gap_items():
    """Even with 3 gap areas only max 2 gap items are added."""
    items = _build_session_plan(
        due_count=0,
        gap_areas=["g1", "g2", "g3"],
        recent_doc_titles=[],
        budget_minutes=20,
    )
    gap_items = [i for i in items if i.type == "gap"]
    assert len(gap_items) == 2


# ---------------------------------------------------------------------------
# (c) Empty inputs return empty list
# ---------------------------------------------------------------------------


def test_build_plan_empty_inputs():
    """All zeros / empty inputs -> items=[]."""
    items = _build_session_plan(
        due_count=0,
        gap_areas=[],
        recent_doc_titles=[],
        budget_minutes=20,
    )
    assert items == []


# ---------------------------------------------------------------------------
# (d) API returns HTTP 200 and valid response schema
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_session_plan_api_200(client):
    """GET /study/session-plan?minutes=20 -> HTTP 200, 'items' list, total_minutes==20."""
    resp = client.get("/study/session-plan?minutes=20")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    assert body["total_minutes"] == 20


# ---------------------------------------------------------------------------
# (e) API rejects minutes outside bounds (ge=5, le=120)
# ---------------------------------------------------------------------------


def test_session_plan_api_bounds_high(client):
    """GET /study/session-plan?minutes=200 returns HTTP 422."""
    resp = client.get("/study/session-plan?minutes=200")
    assert resp.status_code == 422


def test_session_plan_api_bounds_low(client):
    """GET /study/session-plan?minutes=2 returns HTTP 422."""
    resp = client.get("/study/session-plan?minutes=2")
    assert resp.status_code == 422
