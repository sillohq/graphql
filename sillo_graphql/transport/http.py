"""GraphQL over HTTP.

Implements the GraphQL-over-HTTP specification, which is mostly a set of rules
about when the answer is 200 and when it is 400 — and which the previous
integration answered with "always 200", including for a document that failed
to parse.

Two response media types, negotiated from ``Accept``:

``application/graphql-response+json``
    The spec's own. A request that never reaches execution — malformed JSON, a
    missing document, a validation failure — is a 4xx. A request that executes
    and produces field errors is a 200 with ``errors`` in the body, because
    the operation did run.

``application/json``
    The legacy shape every existing client understands: 200 for everything
    except a body that could not be read at all. Chosen when the client does
    not ask for the other, so nothing that works today stops working.
"""

from __future__ import annotations

import json as jsonlib
import typing

from sillo.responses import html, json

from sillo_graphql.errors import ErrorCode, GraphQLError

if typing.TYPE_CHECKING:
    from sillo.core.http import HttpContext

    from sillo_graphql.graph import Graph

__all__ = ["HttpTransport", "negotiate"]

#: The spec's media type. A client sending this in `Accept` is asking to be
#: told about failures with status codes rather than only in the body.
GRAPHQL_RESPONSE_JSON = "application/graphql-response+json"
APPLICATION_JSON = "application/json"
APPLICATION_GRAPHQL = "application/graphql"
MULTIPART_FORM = "multipart/form-data"
FORM_URLENCODED = "application/x-www-form-urlencoded"
