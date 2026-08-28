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


class TestMemoryStore:
    async def test_it_returns_what_was_stored(self):
        store = MemoryStore()
        await store.set("k", DOCUMENT, 60)
        assert await store.get("k") == DOCUMENT

    async def test_an_unknown_key_is_none(self):
        assert await MemoryStore().get("k") is None

    async def test_it_evicts_the_oldest_when_full(self):
        store = MemoryStore(max_entries=2)
        await store.set("a", "1", 60)
        await store.set("b", "2", 60)
        await store.set("c", "3", 60)
        assert await store.get("a") is None
        assert await store.get("c") == "3"
        assert len(store) == 2

    async def test_rewriting_a_key_does_not_evict(self):
        store = MemoryStore(max_entries=1)
        await store.set("a", "1", 60)
        await store.set("a", "2", 60)
        assert await store.get("a") == "2"

    def test_a_zero_capacity_store_is_refused(self):
        with pytest.raises(ValueError, match="max_entries"):
            MemoryStore(max_entries=0)


class TestAPQ:
    async def test_a_plain_query_passes_straight_through(self):
        assert await resolve({"query": DOCUMENT}) == DOCUMENT

    async def test_a_registration_stores_the_document(self):
        store = MemoryStore()
        assert await resolve(apq(DOCUMENT), store=store) == DOCUMENT
        assert await store.get(DIGEST) == DOCUMENT

    async def test_a_known_hash_is_answered_from_the_store(self):
        store = MemoryStore()
        await store.set(DIGEST, DOCUMENT, 60)
        assert await resolve(apq(), store=store) == DOCUMENT

    async def test_an_unknown_hash_asks_the_client_to_send_it(self):
        with pytest.raises(GraphQLError) as caught:
            await resolve(apq())
        assert caught.value.code == ErrorCode.PERSISTED_QUERY_NOT_FOUND

    async def test_a_mismatched_hash_is_refused(self):
        with pytest.raises(GraphQLError, match="does not match"):
            await resolve(apq(DOCUMENT, digest="0" * 64))

    async def test_a_hash_is_refused_when_apq_is_off(self):
        with pytest.raises(GraphQLError) as caught:
            await resolve(apq(), policy=Persisted(apq=False))
        assert caught.value.code == ErrorCode.PERSISTED_QUERY_NOT_SUPPORTED

    async def test_neither_hash_nor_query_is_a_bad_request(self):
        with pytest.raises(GraphQLError) as caught:
            await resolve({})
        assert caught.value.code == ErrorCode.BAD_USER_INPUT


class TestTrustedDocuments:
    def test_it_reads_a_mapping(self):
        trusted = TrustedDocuments({DIGEST: DOCUMENT})
        assert trusted.get(DIGEST) == DOCUMENT
        assert DIGEST in trusted
        assert len(trusted) == 1

    def test_an_unknown_key_is_none(self):
        assert TrustedDocuments({}).get("nope") is None

    def test_it_reads_a_manifest_file(self, tmp_path):
        path = tmp_path / "operations.json"
        path.write_text(json.dumps({DIGEST: DOCUMENT}))
        assert TrustedDocuments(str(path)).get(DIGEST) == DOCUMENT

    def test_a_missing_manifest_says_what_to_do(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Generate one"):
            TrustedDocuments(str(tmp_path / "absent.json"))

    def test_a_manifest_that_is_not_an_object_is_refused(self, tmp_path):
        path = tmp_path / "operations.json"
        path.write_text("[1, 2]")
        with pytest.raises(ValueError, match="hash -> document"):
            TrustedDocuments(str(path))

    async def test_a_trusted_hash_executes(self):
        trusted = TrustedDocuments({DIGEST: DOCUMENT})
        assert await resolve({"documentId": DIGEST}, trusted=trusted) == DOCUMENT

    async def test_an_untrusted_hash_is_refused(self):
        with pytest.raises(GraphQLError) as caught:
            await resolve({"documentId": "nope"}, trusted=TrustedDocuments({}))
        assert caught.value.code == ErrorCode.OPERATION_NOT_PERMITTED

    async def test_a_literal_document_in_the_manifest_is_allowed(self):
        trusted = TrustedDocuments({DIGEST: DOCUMENT})
        assert await resolve({"query": DOCUMENT}, trusted=trusted) == DOCUMENT

    async def test_a_literal_document_not_in_the_manifest_is_refused(self):
        trusted = TrustedDocuments({DIGEST: DOCUMENT})
        with pytest.raises(GraphQLError) as caught:
            await resolve({"query": "{ other }"}, trusted=trusted)
        assert caught.value.code == ErrorCode.OPERATION_NOT_PERMITTED

    async def test_neither_hash_nor_query_is_still_a_bad_request(self):
        with pytest.raises(GraphQLError) as caught:
            await resolve({}, trusted=TrustedDocuments({}))
        assert caught.value.code == ErrorCode.BAD_USER_INPUT
