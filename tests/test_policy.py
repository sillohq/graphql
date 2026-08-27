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


class TestTransport:
    def test_batch_cannot_be_negative(self):
        with pytest.raises(ValueError, match="batch"):
            Transport(batch=-1)

    def test_zero_batch_is_allowed_and_means_refuse(self):
        assert Transport(batch=0).batch == 0

    def test_max_body_is_validated_eagerly(self):
        with pytest.raises(ValueError):
            Transport(max_body="huge")

    def test_max_body_bytes_reads_the_string(self):
        assert Transport(max_body="2MB").max_body_bytes == 2 * 1024**2


class TestUploads:
    def test_are_off_by_default(self):
        assert Uploads().enabled is False

    def test_max_files_below_one_is_refused(self):
        with pytest.raises(ValueError, match="max_files"):
            Uploads(max_files=0)

    def test_sizes_are_validated_eagerly(self):
        with pytest.raises(ValueError):
            Uploads(max_size="lots")
        with pytest.raises(ValueError):
            Uploads(max_total="lots")

    def test_byte_properties_read_the_strings(self):
        uploads = Uploads(max_size="1MB", max_total="3MB")
        assert uploads.max_size_bytes == 1024**2
        assert uploads.max_total_bytes == 3 * 1024**2

    def test_no_allow_list_allows_anything(self):
        assert Uploads().allows("application/x-anything") is True
        assert Uploads().allows(None) is True

    def test_an_allow_list_refuses_an_unknown_type(self):
        uploads = Uploads(content_types=("image/png",))
        assert uploads.allows("image/png") is True
        assert uploads.allows("text/plain") is False

    def test_an_allow_list_refuses_a_missing_type(self):
        assert Uploads(content_types=("image/png",)).allows(None) is False

    def test_parameters_are_not_part_of_the_match(self):
        uploads = Uploads(content_types=("image/png",))
        assert uploads.allows("image/png; charset=binary") is True

    def test_a_glob_matches_a_family(self):
        uploads = Uploads(content_types=("image/*",))
        assert uploads.allows("image/webp") is True
        assert uploads.allows("video/mp4") is False


class TestPersisted:
    def test_is_disabled_when_neither_mode_is_set(self):
        assert Persisted().enabled is False

    def test_apq_alone_enables_it(self):
        assert Persisted(apq=True).enabled is True

    def test_a_manifest_alone_enables_it(self):
        assert Persisted(trusted={"a": "{ x }"}).enabled is True

    def test_ttl_must_be_positive(self):
        with pytest.raises(ValueError, match="ttl"):
            Persisted(ttl=0)


class TestIDE:
    def test_is_off_by_default(self):
        assert IDE().enabled is False

    def test_assets_must_name_a_known_source(self):
        with pytest.raises(ValueError, match="bundled"):
            IDE(assets="local")

    def test_both_known_sources_are_accepted(self):
        assert IDE(assets="cdn").assets == "cdn"
        assert IDE(assets="bundled").assets == "bundled"


class TestErrorPolicy:
    def test_masks_by_default(self):
        assert ErrorPolicy().mask is True

    def test_stacktraces_are_off_by_default(self):
        assert ErrorPolicy().include_stacktrace is False
