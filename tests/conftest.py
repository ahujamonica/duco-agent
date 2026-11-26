"""Test bootstrap: isolate the platform database and data directory."""

from __future__ import annotations

import os
import shutil
import tempfile

TEST_DIR = tempfile.mkdtemp(prefix="duco-tests-")
os.environ["DUCO_DATA_DIR"] = TEST_DIR
os.environ["DUCO_DATABASE_URL"] = f"sqlite:///{TEST_DIR}/duco-test.db"
os.environ["DUCO_ENV"] = "test"


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    shutil.rmtree(TEST_DIR, ignore_errors=True)
