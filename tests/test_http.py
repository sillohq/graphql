"""``sillo_graphql.transport.http`` — framing, negotiation and status codes."""

from __future__ import annotations

import json

import pytest

from sillo_graphql import IDE, Transport, Uploads
from sillo_graphql.testing import GraphClient
from sillo_graphql.transport.http import (
    APPLICATION_JSON,
    GRAPHQL_RESPONSE_JSON,
    negotiate,
)

SPEC = {"accept": GRAPHQL_RESPONSE_JSON}
