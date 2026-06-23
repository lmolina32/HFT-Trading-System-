"""Imported at the top of every test module to put src on the path.

Also raises the log threshold so test output isn't drowned by the warnings
the modules emit on purpose during error paths we deliberately exercise.
"""

import logging
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(level=logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)
