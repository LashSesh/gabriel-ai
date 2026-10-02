import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest


def pytest_collection_modifyitems(config, items):
    skip_containment = pytest.mark.skip(reason="privileged containment self-tests need GABRIEL_CONTAINMENT_TESTS=1")
    skip_live = pytest.mark.skip(reason="live provider tests need GABRIEL_LIVE_PROVIDER=1 and a credential")
    for item in items:
        if "containment" in item.keywords and os.environ.get("GABRIEL_CONTAINMENT_TESTS") != "1":
            item.add_marker(skip_containment)
        if "live_provider" in item.keywords and os.environ.get("GABRIEL_LIVE_PROVIDER") != "1":
            item.add_marker(skip_live)
