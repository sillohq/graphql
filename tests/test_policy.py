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
