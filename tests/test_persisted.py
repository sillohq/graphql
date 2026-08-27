"""``sillo_graphql.persisted`` — APQ, and the manifest that actually matters."""

from __future__ import annotations

import json

import pytest

from sillo_graphql.errors import ErrorCode, GraphQLError
from sillo_graphql.persisted import (
    MemoryStore,
    TrustedDocuments,
    extract_hash,
    hash_document,
    resolve_document,
)
from sillo_graphql.policy import Persisted

DOCUMENT = "{ hello }"
DIGEST = hash_document(DOCUMENT)
