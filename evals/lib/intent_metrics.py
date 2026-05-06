"""Intent routing eval metrics (S218)."""

from __future__ import annotations

ROUTES = ("summary", "graph", "comparative", "search")


def normalize_route(route: str) -> str:
    """Map internal chat intents/node names to the four eval route labels."""
    route = route.strip().lower()
    mapping = {
        "summary": "summary",
        "summary_node": "summary",
        "relational": "graph",
        "graph": "graph",
        "graph_node": "graph",
        "comparative": "comparative",
        "comparative_node": "comparative",
        "factual": "search",
        "exploratory": "search",
        "search": "search",
        "search_node": "search",
    }
    return mapping.get(route, "search")


def compute_routing_accuracy(samples: list[dict]) -> float:
    if not samples:
        return 0.0
    correct = sum(
        1
        for sample in samples
        if normalize_route(sample["predicted_route"]) == normalize_route(sample["expected_route"])
    )
    return correct / len(samples)


def compute_per_route_precision_recall(samples: list[dict]) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for route in ROUTES:
        tp = sum(
            1
            for s in samples
            if normalize_route(s["predicted_route"]) == route
            and normalize_route(s["expected_route"]) == route
        )
        fp = sum(
            1
            for s in samples
            if normalize_route(s["predicted_route"]) == route
            and normalize_route(s["expected_route"]) != route
        )
        fn = sum(
            1
            for s in samples
            if normalize_route(s["predicted_route"]) != route
            and normalize_route(s["expected_route"]) == route
        )
        metrics[route] = {
            "precision": tp / (tp + fp) if (tp + fp) else 0.0,
            "recall": tp / (tp + fn) if (tp + fn) else 0.0,
        }
    return metrics
