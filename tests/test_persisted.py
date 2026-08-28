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


def apq(document=None, digest=DIGEST):
    payload = {"extensions": {"persistedQuery": {"sha256Hash": digest}}}
    if document is not None:
        payload["query"] = document
    return payload


async def resolve(payload, *, policy=None, store=None, trusted=None):
    return await resolve_document(
        payload,
        policy=policy or Persisted(apq=True),
        store=store if store is not None else MemoryStore(),
        trusted=trusted,
    )


class TestHashing:
    def test_it_is_the_sha256_of_the_document(self):
        assert len(DIGEST) == 64
        assert hash_document(DOCUMENT) == DIGEST

    def test_a_different_document_hashes_differently(self):
        assert hash_document("{ other }") != DIGEST
