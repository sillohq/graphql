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


def parse_size(value: int | str) -> int:
    """Bytes from ``10485760`` or from ``"10MB"``.

    Upload limits are read far more often than they are written, and a reader
    should not have to divide by 1024 twice to check one.
    """
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"size cannot be negative: {value}")
        return value

    match = _SIZE.match(value)
    if match is None:
        raise ValueError(f"cannot read {value!r} as a size, try '10MB'")

    amount, unit = match.groups()
    unit = unit.upper()
    if unit in ("K", "M", "G"):
        unit += "B"
    return int(float(amount) * _UNITS[unit])
