import importlib.util


def require_extra(module: str, feature: str, group: str = "full") -> None:
    if importlib.util.find_spec(module) is None:
        raise RuntimeError(
            f"{feature} requires the '{group}' dependency group. "
            f"Reinstall with: uv sync --group {group}"
        )
