"""The policy objects a :class:`~sillo_graphql.graph.Graph` is configured with.

Common knobs are plain keyword arguments on ``Graph``; the deeper ones are
grouped here, the same split ``sillo`` makes between arguments on ``SilloApp``
and objects like ``CSRFConfig``. Grouping matters more than usual in a GraphQL
endpoint, because "how large may a query be" is four numbers that only make
sense read together.

Every default is chosen for a public endpoint. A framework whose defaults are
safe only on a private network is a framework that ships incidents.
"""

from __future__ import annotations

import dataclasses
import re
import typing

__all__ = [
    "IDE",
    "ErrorPolicy",
    "Limits",
    "Persisted",
    "Transport",
    "Uploads",
    "parse_size",
]

_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMG]?B?)\s*$", re.IGNORECASE)
_UNITS = {"": 1, "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
