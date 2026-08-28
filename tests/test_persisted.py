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


class TestExtractHash:
    def test_it_reads_the_apq_extension(self):
        assert extract_hash(apq()) == DIGEST

    def test_it_reads_a_bare_document_id(self):
        assert extract_hash({"documentId": "abc"}) == "abc"

    def test_a_payload_with_neither_has_none(self):
        assert extract_hash({"query": "{ x }"}) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"extensions": "not an object"},
            {"extensions": {"persistedQuery": "not an object"}},
            {"extensions": {"persistedQuery": {}}},
            {"extensions": {"persistedQuery": {"sha256Hash": ""}}},
            {"extensions": {"persistedQuery": {"sha256Hash": 7}}},
            {"documentId": ""},
            {"documentId": 7},
        ],
    )
    def test_a_malformed_hash_is_no_hash(self, payload):
        assert extract_hash(payload) is None
