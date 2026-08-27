"""``sillo_graphql.loaders`` — batching, caching, and their edges."""

from __future__ import annotations

import asyncio

import pytest

from sillo_graphql.loaders import Loader, LoaderError, LoaderRegistry, loader


class TestBatching:
    async def test_siblings_become_one_call(self):
        calls = []

        @loader
        async def load(keys):
            calls.append(list(keys))
            return [f"v{key}" for key in keys]

        async with LoaderRegistry().scope():
            got = await asyncio.gather(load(1), load(2), load(3))

        assert got == ["v1", "v2", "v3"]
        assert calls == [[1, 2, 3]]

    async def test_a_repeated_key_is_asked_for_once(self):
        calls = []

        @loader
        async def load(keys):
            calls.append(list(keys))
            return [key * 2 for key in keys]

        async with LoaderRegistry().scope():
            got = await asyncio.gather(load(1), load(1), load(2))

        assert got == [2, 2, 4]
        assert calls == [[1, 2]]

    async def test_caching_can_be_turned_off(self):
        calls = []

        @loader(cache=False)
        async def load(keys):
            calls.append(list(keys))
            return [key for key in keys]

        async with LoaderRegistry().scope():
            await asyncio.gather(load(1), load(1))

        assert calls == [[1, 1]]

    async def test_load_many_is_one_batch(self):
        calls = []

        @loader
        async def load(keys):
            calls.append(list(keys))
            return [str(key) for key in keys]

        async with LoaderRegistry().scope():
            got = await load.load_many([3, 1, 2])

        assert got == ["3", "1", "2"]
        assert calls == [[3, 1, 2]]

    async def test_load_is_the_same_as_calling(self):
        @loader
        async def load(keys):
            return list(keys)

        async with LoaderRegistry().scope():
            assert await load.load(5) == 5

    async def test_a_large_batch_is_chunked(self):
        sizes = []

        @loader(max_batch_size=2)
        async def load(keys):
            sizes.append(len(keys))
            return list(keys)

        async with LoaderRegistry().scope():
            await load.load_many([1, 2, 3, 4, 5])

        assert sizes == [2, 2, 1]

    async def test_two_scopes_do_not_share_a_cache(self):
        calls = []

        @loader
        async def load(keys):
            calls.append(list(keys))
            return list(keys)

        for _ in range(2):
            async with LoaderRegistry().scope():
                await load(1)

        assert calls == [[1], [1]]

    async def test_an_unhashable_key_skips_the_cache(self):
        calls = []

        @loader
        async def load(keys):
            calls.append(len(keys))
            return [len(key) for key in keys]

        async with LoaderRegistry().scope():
            got = await asyncio.gather(load([1, 2]), load([1, 2]))

        assert got == [2, 2]
        assert calls == [2]
