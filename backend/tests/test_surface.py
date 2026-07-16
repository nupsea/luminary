from app.surface_manifest import enabled_routers, surfaces_for_mode


def test_enabled_routers_mode_semantics():
    pub = enabled_routers("public")
    assert "documents" in pub
    assert "feynman" not in pub
    assert "evals" not in pub
    assert "graph" not in pub

    full = enabled_routers("full")
    assert {"feynman", "evals", "admin", "graph", "monitoring"} <= full
    assert pub <= full


def test_map_is_a_full_mode_nav_tab():
    full_tabs = [s for s in surfaces_for_mode("full") if s["kind"] == "nav_tab"]
    assert any(s["id"] == "map" for s in full_tabs)
    public_ids = {s["id"] for s in surfaces_for_mode("public")}
    assert "map" not in public_ids


def test_dev_rail_surfaces_are_full_mode_only():
    dev_rail = [s for s in surfaces_for_mode("full") if s.get("rail") == "dev"]
    assert {s["id"] for s in dev_rail} == {"quality_dashboard", "admin", "monitoring"}
    for s in dev_rail:
        assert s["mode"] == "full"
