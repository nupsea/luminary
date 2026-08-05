import importlib.util


def require_extra(module: str, feature: str, group: str = "full") -> None:
    if importlib.util.find_spec(module) is None:
        # --no-default-groups is part of the command: `--group X` only ADDS to
        # default-groups, so the bare form also resolves `dev`, whose
        # arize-phoenix pulls a source-built sqlean-py that fails.
        raise RuntimeError(
            f"{feature} requires the '{group}' dependency group. "
            f"Reinstall with: uv sync --no-default-groups --group {group}"
        )
