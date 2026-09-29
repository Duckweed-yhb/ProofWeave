import pytest

from proofweave.data.loader import load_snapshot


@pytest.fixture(scope="session")
def snap():
    return load_snapshot()
