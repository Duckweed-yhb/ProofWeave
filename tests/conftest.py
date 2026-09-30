import shutil
import tempfile
from pathlib import Path

import pytest

from proofweave.data.loader import load_snapshot


@pytest.fixture(scope="session")
def snap():
    """Read-only snapshot, loaded once for the whole session.

    Do not mutate anything reached from this fixture.  The models are frozen
    exactly to make that mistake loud, but use `fresh_snap` when a test needs
    to tamper with the data.
    """
    return load_snapshot()


@pytest.fixture
def fresh_snap():
    """A private snapshot copy for tests that need to break something."""
    return load_snapshot()


@pytest.fixture
def rescore():
    """Re-derive every score, as `load_snapshot` does.

    Tests that change the evidence of a snapshot need this, otherwise the audit
    reports their stale scores before it gets to the check under test.
    """
    from proofweave.scoring import score_relationship

    def _rescore(snap):
        rels = [r.model_copy(update={"score": score_relationship(r)})
                for r in snap.relationships]
        return snap.model_copy(update={"relationships": rels})

    return _rescore


@pytest.fixture
def tamper():
    """Rebuild a snapshot with one relationship replaced by an edited copy.

    Frozen models make the intent explicit: a test cannot quietly edit the
    shared snapshot, it has to say which field it is corrupting.
    """

    def _tamper(snap, index=0, **updates):
        rels = list(snap.relationships)
        rels[index] = rels[index].model_copy(update=updates)
        return snap.model_copy(update={"relationships": rels})

    return _tamper


@pytest.fixture
def write_dir():
    """A temporary directory this process can actually write into.

    Deliberately not pytest's ``tmp_path``: under a restricted sandbox (the DSH
    Windows sandbox runs the confined process at low integrity) the shared temp
    tree is not writable, and ``tmp_path`` then fails during fixture setup --
    turning a plain environment limitation into a confusing error.  Here the
    directory is created and probed first, and the test skips with a readable
    reason when no writable location exists.
    """
    path = Path(tempfile.mkdtemp(prefix="proofweave-test-"))
    probe = path / ".write-probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        shutil.rmtree(path, ignore_errors=True)
        pytest.skip(f"no writable temporary directory in this environment: {exc}")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
