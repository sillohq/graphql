"""``sillo_graphql.ide`` — the explorer page."""

from __future__ import annotations

import json
import re

from sillo_graphql.ide import render
from sillo_graphql.policy import IDE


def config_of(page: str) -> dict:
    """The config object the page was rendered with.

    Angle brackets are written as unicode escapes so the JSON cannot end the
    inline script block; `json.loads` reads them back.
    """
    match = re.search(r"var config = (\{.*?\});", page, re.S)
    assert match is not None
    return json.loads(match.group(1))


class TestBundled:
    def test_it_makes_no_external_requests(self):
        page = render(IDE(), endpoint="/graphql")
        assert "unpkg" not in page
        assert "https://" not in page.split("<script>")[0].split("<style>")[0]

    def test_it_is_a_complete_document(self):
        page = render(IDE(), endpoint="/graphql")
        assert page.lstrip().startswith("<!doctype html>")
        assert page.rstrip().endswith("</html>")

    def test_the_endpoint_is_in_the_config(self):
        assert (
            config_of(render(IDE(), endpoint="/api/graph"))["endpoint"] == "/api/graph"
        )

    def test_the_title_is_shown(self):
        assert "Acme API" in render(IDE(title="Acme API"), endpoint="/g")

    def test_a_title_with_markup_in_it_is_escaped(self):
        page = render(IDE(title="<script>x</script>"), endpoint="/g")
        assert "<script>x</script>" not in page
        assert "&lt;script&gt;" in page

    def test_an_endpoint_with_markup_in_it_is_escaped(self):
        page = render(IDE(), endpoint="/g<img>")
        assert "/g<img>" not in page
        # And it survives the escaping intact.
        assert config_of(page)["endpoint"] == "/g<img>"

    def test_a_default_query_cannot_close_the_script_block(self):
        page = render(IDE(default_query="</script><img>"), endpoint="/g")
        assert "</script><img>" not in page
        assert config_of(page)["defaultQuery"] == "</script><img>"

    def test_a_default_query_is_carried_through(self):
        page = render(IDE(default_query="{ me }"), endpoint="/g")
        assert config_of(page)["defaultQuery"] == "{ me }"

    def test_no_socket_means_the_page_does_not_claim_subscriptions(self):
        assert config_of(render(IDE(), endpoint="/g"))["subscriptions"] is False

    def test_a_socket_is_advertised_when_there_is_one(self):
        page = render(IDE(), endpoint="/g", socket="ws://testserver/g")
        assert config_of(page)["subscriptions"] is True
        assert config_of(page)["socket"] == "ws://testserver/g"


class TestCdn:
    def test_it_loads_graphiql_with_integrity_hashes(self):
        page = render(IDE(assets="cdn"), endpoint="/g")
        assert "unpkg.com/graphiql" in page
        assert page.count("integrity=") >= 4

    def test_the_config_is_still_substituted(self):
        page = render(IDE(assets="cdn"), endpoint="/g", socket="ws://x/g")
        assert '"endpoint": "/g"' in page or '"endpoint":"/g"' in page
