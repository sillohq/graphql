"""``sillo_graphql.loaders`` — batching, caching, and their edges."""

from __future__ import annotations

import asyncio

import pytest

from sillo_graphql.loaders import Loader, LoaderError, LoaderRegistry, loader
