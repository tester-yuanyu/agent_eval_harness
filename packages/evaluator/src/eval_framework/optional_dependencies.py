"""Actionable errors at explicitly requested optional integration boundaries."""

from importlib import import_module


class MissingOptionalDependencyError(ValueError):
    pass


def require_langfuse() -> None:
    try:
        import_module("langfuse.api.client")
    except ModuleNotFoundError as exc:
        if exc.name is None or exc.name.split(".")[0] != "langfuse":
            raise
        raise MissingOptionalDependencyError(
            "Langfuse is optional; install 'agent-evaluator[langfuse]' "
            "or run python3.11 scripts/setup.py --only evaluator --with-langfuse"
        ) from exc
