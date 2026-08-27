"""``sillo_graphql.policy`` — the configuration objects and their guards."""

from __future__ import annotations

import pytest

from sillo_graphql.policy import (
    IDE,
    ErrorPolicy,
    Limits,
    Persisted,
    Transport,
    Uploads,
    parse_size,
)


class TestParseSize:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, 0),
            (2048, 2048),
            ("512", 512),
            ("512B", 512),
            ("1KB", 1024),
            ("1 kb", 1024),
            ("10MB", 10 * 1024**2),
            ("1.5GB", int(1.5 * 1024**3)),
            ("4M", 4 * 1024**2),
            ("  2 G  ", 2 * 1024**3),
        ],
    )
    def test_reads_the_forms_people_write(self, value, expected):
        assert parse_size(value) == expected

    def test_a_negative_int_is_refused(self):
        with pytest.raises(ValueError, match="negative"):
            parse_size(-1)

    def test_nonsense_names_what_it_wanted(self):
        with pytest.raises(ValueError, match="10MB"):
            parse_size("about a megabyte")


class TestLimits:
    def test_defaults_are_set_for_a_public_endpoint(self):
        limits = Limits()
        assert limits.depth == 10
        assert limits.cost == 1_000

    @pytest.mark.parametrize(
        "field", ["depth", "aliases", "breadth", "list_multiplier", "max_tokens"]
    )
    def test_a_limit_below_one_is_refused(self, field):
        with pytest.raises(ValueError, match=field):
            Limits(**{field: 0})

    def test_cost_may_be_none_to_disable_it(self):
        assert Limits(cost=None).cost is None

    def test_a_cost_below_one_is_refused(self):
        with pytest.raises(ValueError, match="cost"):
            Limits(cost=0)

    def test_a_negative_field_cost_is_refused(self):
        with pytest.raises(ValueError, match="default_field_cost"):
            Limits(default_field_cost=-1)

    def test_none_relaxes_everything(self):
        limits = Limits.none()
        assert limits.cost is None
        assert limits.depth >= 1_000

    def test_is_frozen(self):
        with pytest.raises(Exception):
            Limits().depth = 2
