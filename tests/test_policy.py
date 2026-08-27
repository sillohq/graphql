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
