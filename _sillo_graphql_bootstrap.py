"""Make ``sillo.graphql`` resolve to this package, without touching the framework.

The code lives in the top-level ``sillo_graphql`` package. This module registers a
meta-path finder that maps the name ``sillo.graphql`` onto it, so both import
paths reach the same objects:

    from sillo.graphql import Graph      # reads as part of the framework
    from sillo_graphql import Graph      # where the code actually is

It is loaded by ``sillo_graphql.pth`` at interpreter startup, which is the only
hook that runs *before* an ``import sillo.graphql`` could fail. Nothing is
imported here — neither ``sillo`` nor ``sillo_graphql`` — so the cost is one
object appended to ``sys.meta_path``.

Why not simply ship ``sillo/wire/`` into the framework's own package directory:
two distributions writing into one directory goes wrong in both directions.
Installing the framework from a checkout moves where ``sillo`` resolves and
orphans whatever the other package left in ``site-packages``; and removing or
replacing the framework leaves that directory standing with no ``__init__.py``
in it, which is an override rather than an addition. Nothing here writes into
``sillo/`` at all.

Static analysis does not run import hooks, so type checkers are served
separately, by the partial stubs in ``sillo-stubs/`` (PEP 561).
"""

from __future__ import annotations

import os
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import find_spec

ALIAS = "sillo.graphql"
REAL = "sillo_graphql"


def _resolve(fullname: str) -> str | None:
    """The real module *fullname* stands for, or ``None`` if it is not ours."""
    if fullname == ALIAS:
        return REAL
    if fullname.startswith(ALIAS + "."):
        return REAL + fullname[len(ALIAS) :]
    return None


def _framework_ships_graphql() -> str | None:
    """Where the framework's own ``sillo/graphql`` lives, if it still does.

    Versions of ``sillo-framework`` before 1.0 shipped a ``sillo.graphql``
    module of their own. A meta-path finder is consulted *before* the path
    finder, so this one would quietly shadow it — the same override that
    installing into ``sillo/`` would have been, arrived at from the other
    direction.

    Rather than shadow it, the alias refuses and says which two things
    disagree. Cheap: nothing is imported, only ``sillo.__path__`` is read, and
    only at the moment someone actually imports ``sillo.graphql``.
    """
    module = sys.modules.get("sillo")
    paths = getattr(module, "__path__", None) if module is not None else None
    for base in paths or ():
        for candidate in (
            os.path.join(base, "graphql", "__init__.py"),
            os.path.join(base, "graphql.py"),
        ):
            if os.path.exists(candidate):
                return candidate
    return None


class _AliasLoader(Loader):
    """Hands back the already-imported target, so both names are one object.

    Loading the source a second time under the other name would give two
    ``Graph`` classes and two sets of rooms — a broadcast would reach half of
    them, and ``isinstance`` would disagree with itself.
    """

    def __init__(self, target: str) -> None:
        self.target = target

    def create_module(self, spec: ModuleSpec):
        import importlib

        return importlib.import_module(self.target)

    def exec_module(self, module) -> None:
        """Already executed under its own name; nothing to run again."""


class _AliasFinder(MetaPathFinder):
    """Answers for ``sillo.graphql`` and anything beneath it."""

    def find_spec(self, fullname: str, path=None, target=None):
        real = _resolve(fullname)
        if real is None:
            return None

        shipped = _framework_ships_graphql()
        if shipped is not None:
            raise ImportError(
                f"sillo-graphql cannot provide `{ALIAS}`: the installed "
                f"sillo-framework ships its own, at {shipped}. They are "
                f"different packages with the same import path, and silently "
                f"preferring either one would be wrong.\n\n"
                f"Upgrade to sillo-framework>=1.0, which no longer ships it, "
                f"or import `{REAL}` directly."
            )

        try:
            if find_spec(real) is None:
                return None
        except (ImportError, ValueError):
            # The package is half-installed, or its parent is missing. Decline
            # rather than raise: another finder may do better, and the import
            # error a caller gets should be the ordinary one.
            return None

        import importlib

        module = importlib.import_module(real)
        spec = ModuleSpec(fullname, _AliasLoader(real))
        spec.submodule_search_locations = getattr(module, "__path__", None)
        return spec
