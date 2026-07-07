"""Internal modules for the AI News Radar update pipeline."""

from __future__ import annotations

from types import ModuleType


def wire_modules(modules: list[ModuleType]) -> None:
    """Share moved top-level names across split modules.

    The original update_news.py kept every helper in one global namespace.
    Stage A moves helpers into files without changing function bodies, so each
    moved module receives the same public names after import.
    """

    shared: dict[str, object] = {}
    for module in modules:
        for name, value in vars(module).items():
            if not name.startswith("_"):
                shared[name] = value
    for module in modules:
        for name, value in shared.items():
            if not name.startswith("_"):
                setattr(module, name, value)
