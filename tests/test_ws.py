"""``sillo_graphql.transport.ws`` — the graphql-transport-ws protocol."""

from __future__ import annotations

import json

import pytest
from sillo import SilloApp

from sillo_graphql import Graph, unauthenticated
from sillo_graphql.testing import GraphClient, StreamEnded
from sillo_graphql.transport.ws import (
    CLOSE_ALREADY_INITIALISED,
    CLOSE_BAD_MESSAGE,
    CLOSE_SUBSCRIBER_EXISTS,
    CLOSE_UNAUTHORIZED,
    PROTOCOL,
)
