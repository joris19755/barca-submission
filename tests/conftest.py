"""Shared fixtures for the harness tests."""
import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)

import helpers as H  # noqa: E402


def _require_mtah(what):
    if not os.path.isdir(os.path.join(MTAH, "evaluation")):
        pytest.skip("{} skipped: mtah-2027 not found at {} — set $MTAH_REPO_DIR or keep "
                    "the sibling checkout to run this official-scorer test".format(
                        what, MTAH))


@pytest.fixture(scope="session")
def pm():
    return H.load_pm()