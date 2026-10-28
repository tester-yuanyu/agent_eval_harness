"""Stable CLI entrypoint for Capability Snapshot Protocol v3."""

from minimal_agent.capabilities.v3.cli import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
