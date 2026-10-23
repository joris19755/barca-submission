"""Shared fixtures for the harness tests."""
import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)

import helpers as H  # noqa: E402


@pytest.fixture(scope="session")
def pm():
    return H.load_pm()