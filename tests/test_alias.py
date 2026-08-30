"""``sillo.graphql`` as an import path for ``sillo_graphql``.

The finder is driven directly rather than through a real import wherever
possible, so these hold under an editable install — where the repository copy
of the bootstrap is importable and the site-packages one may not be.
"""

from __future__ import annotations

import re
import sys

import pytest

import _sillo_graphql_bootstrap as bootstrap


class TestResolve:
    def test_the_alias_maps_to_the_real_package(self):
        assert bootstrap._resolve("sillo.graphql") == "sillo_graphql"

    def test_a_submodule_maps_through(self):
        assert bootstrap._resolve("sillo.graphql.limits") == "sillo_graphql.limits"

    def test_a_deep_submodule_maps_through(self):
        assert (
            bootstrap._resolve("sillo.graphql.transport.ws")
            == "sillo_graphql.transport.ws"
        )

    @pytest.mark.parametrize(
        "name",
        ["sillo", "sillo.record", "sillo_graphql", "graphql", "sillo.graphqlish"],
    )
    def test_anything_else_is_declined(self, name):
        assert bootstrap._resolve(name) is None


class TestFinder:
    def test_it_answers_for_the_alias(self):
        spec = bootstrap._AliasFinder().find_spec("sillo.graphql")
        assert spec is not None
        assert spec.name == "sillo.graphql"

    def test_it_declines_everything_else(self):
        assert bootstrap._AliasFinder().find_spec("json") is None

    def test_the_spec_carries_the_package_s_search_path(self):
        spec = bootstrap._AliasFinder().find_spec("sillo.graphql")
        assert spec.submodule_search_locations is not None

    def test_a_submodule_spec_has_no_search_path(self):
        spec = bootstrap._AliasFinder().find_spec("sillo.graphql.errors")
        assert spec.submodule_search_locations is None

    def test_it_declines_when_the_target_is_missing(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "REAL", "no_such_package_anywhere")
        assert bootstrap._AliasFinder().find_spec("sillo.graphql") is None

    def test_it_declines_rather_than_raising_on_a_broken_target(self, monkeypatch):
        def explode(name):
            raise ImportError("half-installed")

        monkeypatch.setattr(bootstrap, "find_spec", explode)
        assert bootstrap._AliasFinder().find_spec("sillo.graphql") is None


class TestLoader:
    def test_it_hands_back_the_module_already_imported(self):
        import sillo_graphql

        loader = bootstrap._AliasLoader("sillo_graphql")
        assert loader.create_module(None) is sillo_graphql

    def test_executing_it_again_does_nothing(self):
        assert bootstrap._AliasLoader("sillo_graphql").exec_module(object()) is None


class TestInstall:
    def test_the_finder_is_registered(self):
        assert any(
            isinstance(finder, bootstrap._AliasFinder) for finder in sys.meta_path
        )

    def test_installing_twice_adds_nothing(self):
        before = len(sys.meta_path)
        assert bootstrap.install() is False
        assert len(sys.meta_path) == before
