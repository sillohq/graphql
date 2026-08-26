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
