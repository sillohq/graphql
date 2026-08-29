"""``sillo_graphql.transport.sse`` — subscriptions over an HTTP response."""

from __future__ import annotations

import json

import pytest
from sillo import SilloApp

from sillo_graphql import Graph
from sillo_graphql.transport.sse import MEDIA_TYPE, SseTransport, _event
