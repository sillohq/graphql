"""Batching, so a graph query is not a table scan per node.

N+1 is GraphQL's defining failure: ``{ posts { author { name } } }`` asks for
one author per post, and a resolver written the obvious way issues one query
per post. A loader collects the keys its siblings asked for during the same
tick of the event loop and answers them all with one call.

Registration is a decorator, like everything else a ``Graph`` is configured
with::

    @graph.loader
    async def load_author(keys: list[int]) -> list[User]:
        rows = await User.objects.filter(id__in=keys).all()
        return align(rows, keys)

and a resolver simply calls it::

    @field
    async def author(ctx: HttpContext, root: Post) -> User:
        return await load_author(root.author_id)

There is no registry to thread through. The batch a call joins is found from
the context variable the transport sets, so state is per operation and two
concurrent requests never share a cache.
"""

from __future__ import annotations

import asyncio
import typing

from sillo_graphql.errors import SilloGraphQLError

__all__ = ["Loader", "LoaderError", "LoaderRegistry", "loader"]

K = typing.TypeVar("K")
V = typing.TypeVar("V")

BatchFn = typing.Callable[
    [list[typing.Any]], typing.Awaitable[typing.Sequence[typing.Any]]
]


class LoaderError(SilloGraphQLError):
    """A batch function broke its contract."""
