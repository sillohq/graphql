"""Persisted operations — APQ, and the trusted-document mode that matters.

Two different things share one name.

**Automatic persisted queries** are a bandwidth optimisation. A client sends a
SHA-256 hash instead of the document; on a miss the server says so, the client
sends the document once, and the hash works from then on. Any document is
still accepted, so this buys nothing in safety.

**Trusted documents** are the safety property. A manifest of the operations an
application actually sends is generated at build time, and the server executes
nothing else. The workload becomes finite and known: cost analysis has a
ceiling that was measured rather than guessed, introspection stops mattering,
and a GET response is safe to cache because the set of possible responses is
enumerable.

They compose — APQ for the wire saving, the manifest for the guarantee — and
the store is an interface so the manifest can come from a file, a dict, or
whatever a deployment already has.
"""

from __future__ import annotations

import hashlib
import json
import os
import typing

from sillo_graphql.errors import ErrorCode, GraphQLError
from sillo_graphql.policy import Persisted

__all__ = [
    "MemoryStore",
    "PersistedStore",
    "TrustedDocuments",
    "extract_hash",
    "hash_document",
    "resolve_document",
]


def hash_document(document: str) -> str:
    """The SHA-256 of a document, as the APQ protocol computes it."""
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


class PersistedStore(typing.Protocol):
    """Where APQ documents are kept between requests.

    A Protocol rather than a base class: an application that already has a
    cache should be able to hand it over without inheriting anything.
    """

    async def get(self, key: str) -> str | None:
        """The document stored under *key*, or ``None``."""
        ...

    async def set(self, key: str, document: str, ttl: int) -> None:
        """Store *document* under *key* for *ttl* seconds."""
        ...


class MemoryStore:
    """An in-process APQ store, and the default.

    Good enough for one process. Across several, each will learn the same
    documents separately — correct, just wasteful — so a shared cache is worth
    configuring once there is more than one.

    Bounded, because an unbounded map keyed by client-supplied hashes is a
    memory leak with a nice name. Eviction is oldest-first, which suits a
    workload where a deploy replaces the whole document set at once.
    """

    def __init__(self, max_entries: int = 1_000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self._documents: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        """The document stored under *key*, or ``None``."""
        return self._documents.get(key)

    async def set(self, key: str, document: str, ttl: int) -> None:
        """Store *document*, evicting the oldest entry if full.

        *ttl* is accepted and ignored: entries only leave by eviction here,
        and a process restart clears the lot anyway.
        """
        if key not in self._documents and len(self._documents) >= self.max_entries:
            oldest = next(iter(self._documents))
            del self._documents[oldest]
        self._documents[key] = document

    def __len__(self) -> int:
        return len(self._documents)
