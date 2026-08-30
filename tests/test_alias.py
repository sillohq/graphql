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
