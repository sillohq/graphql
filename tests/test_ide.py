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
