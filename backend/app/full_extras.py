import importlib.util


def require_extra(module: str, feature: str) -> None:
    if importlib.util.find_spec(module) is None:
        raise RuntimeError(
            f"{feature} requires the 'full' dependency group. "
            f"Reinstall with: uv sync --group full"
        )
