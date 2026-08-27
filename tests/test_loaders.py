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


class TestFailures:
    async def test_a_raising_batch_reaches_every_waiter(self):
        @loader
        async def load(keys):
            raise RuntimeError("database gone")

        async with LoaderRegistry().scope():
            with pytest.raises(RuntimeError, match="database gone"):
                await asyncio.gather(load(1), load(2))

    async def test_a_short_result_is_named_as_a_contract_break(self):
        @loader
        async def load(keys):
            return [1]

        async with LoaderRegistry().scope():
            with pytest.raises(LoaderError, match="one value per key"):
                await asyncio.gather(load(1), load(2))

    async def test_an_exception_in_the_list_fails_only_that_key(self):
        @loader
        async def load(keys):
            return [KeyError("missing") if key == 2 else key for key in keys]

        async with LoaderRegistry().scope():
            first = asyncio.ensure_future(load(1))
            second = asyncio.ensure_future(load(2))
            assert await first == 1
            with pytest.raises(KeyError):
                await second

    async def test_calling_outside_an_operation_says_so(self):
        @loader
        async def load(keys):
            return list(keys)

        with pytest.raises(LoaderError, match="outside a GraphQL operation"):
            await load(1)

    def test_a_batch_size_below_one_is_refused(self):
        with pytest.raises(ValueError, match="max_batch_size"):
            Loader(lambda keys: keys, max_batch_size=0)


class TestPriming:
    async def test_a_primed_key_is_never_asked_for(self):
        calls = []

        @loader
        async def load(keys):
            calls.append(list(keys))
            return list(keys)

        async with LoaderRegistry().scope():
            load.prime(1, "already known")
            assert await load(1) == "already known"

        assert calls == []

    async def test_forgetting_sends_the_key_back_to_the_batch(self):
        calls = []

        @loader
        async def load(keys):
            calls.append(list(keys))
            return [f"fresh-{key}" for key in keys]

        async with LoaderRegistry().scope():
            load.prime(1, "stale")
            load.forget(1)
            assert await load(1) == "fresh-1"

        assert calls == [[1]]

    async def test_forgetting_an_unknown_key_is_harmless(self):
        @loader
        async def load(keys):
            return list(keys)

        async with LoaderRegistry().scope():
            load.forget("never seen")

    async def test_an_unhashable_key_cannot_be_primed(self):
        @loader
        async def load(keys):
            return list(keys)

        async with LoaderRegistry().scope():
            with pytest.raises(LoaderError, match="unhashable"):
                load.prime([1], "x")


class TestRegistry:
    async def test_it_counts_the_loaders_an_operation_touched(self):
        @loader
        async def one(keys):
            return list(keys)

        @loader
        async def two(keys):
            return list(keys)

        registry = LoaderRegistry()
        async with registry.scope():
            await asyncio.gather(one(1), two(2))

        assert len(registry) == 2

    async def test_two_loaders_of_the_same_name_stay_apart(self):
        def make():
            @loader
            async def load(keys):
                return list(keys)

            return load

        first, second = make(), make()
        registry = LoaderRegistry()
        async with registry.scope():
            await asyncio.gather(first(1), second(1))

        assert len(registry) == 2

    def test_a_loader_names_itself_after_its_function(self):
        @loader
        async def load_author(keys):
            """Doc."""
            return list(keys)

        assert load_author.name == "load_author"
        assert repr(load_author) == "Loader('load_author')"
        assert load_author.__doc__ == "Doc."

    def test_a_name_can_be_given(self):
        assert loader(lambda keys: keys, name="chosen").name == "chosen"
