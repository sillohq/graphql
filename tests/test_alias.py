"""``sillo.graphql`` as an import path for ``sillo_graphql``.

The finder is driven directly rather than through a real import wherever
possible, so these hold under an editable install — where the repository copy
of the bootstrap is importable and the site-packages one may not be.
"""

from __future__ import annotations

import re
import sys

import pytest

import _sillo_graphql_bootstrap as bootstrap
