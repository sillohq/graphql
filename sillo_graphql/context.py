"""What a resolver sees.

``sillo``'s pitch is one typed context object per connection, and this package
keeps that promise inside GraphQL: a resolver declares ``ctx: HttpContext`` and
gets the same object an HTTP handler would, not a dictionary lookup.

:class:`GraphContext` is what Strawberry is handed as ``context_value``. It
carries the connection's own context, a handle for influencing the response,
the request-scoped loader registry, and whatever a ``@graph.context`` hook
added. It is also a ``Mapping``, so ``info.context["ctx"]`` — the shape the
old ``sillo.graphql`` handler had — keeps working while a codebase migrates.
"""

from __future__ import annotations

import contextvars
import dataclasses
import time
import typing

if typing.TYPE_CHECKING:
    from sillo.core.http import HttpContext
    from sillo.websockets import WebSocketContext

    from sillo_graphql.loaders import LoaderRegistry

__all__ = ["GraphContext", "ResponseHandle", "current_context"]

#: The context of the operation being resolved, for code that cannot be
#: handed one. Loaders use it to find their per-request batch; nothing else
#: should need it, and a resolver never does — it declares ``ctx`` instead.
current_context: contextvars.ContextVar[GraphContext] = contextvars.ContextVar(
    "sillo_graphql_context"
)
