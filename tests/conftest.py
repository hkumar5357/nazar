"""Pytest bootstrap: make ``import pipeline`` work from any invocation dir.

The pipeline package is used straight from the repo (no install step), so
tests insert the repo root at the front of sys.path. This keeps
``pytest``, ``pytest tests/``, and IDE runners equivalent.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
