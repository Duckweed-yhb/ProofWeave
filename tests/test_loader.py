"""Tests for snapshot loading, including the documented environment override."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from proofweave.data.loader import _DEFAULT_SNAPSHOT, default_snapshot_path, load_snapshot

# A path that is never created, so "does this exist?" stays deterministic.
_ABSENT = Path("proofweave-tests-absent-snapshot.json")


def test_bundled_snapshot_is_the_default():
    assert default_snapshot_path() == _DEFAULT_SNAPSHOT
    assert _DEFAULT_SNAPSHOT.exists(), "the frozen snapshot must ship with the package"


def test_env_var_overrides_the_snapshot_path(monkeypatch):
    """`.env.example` documents PROOFWEAVE_SNAPSHOT; it has to actually work."""
    monkeypatch.setenv("PROOFWEAVE_SNAPSHOT", str(_ABSENT))
    assert default_snapshot_path() == _ABSENT


def test_empty_env_var_falls_back_to_the_bundled_file(monkeypatch):
    monkeypatch.setenv("PROOFWEAVE_SNAPSHOT", "")
    assert default_snapshot_path() == _DEFAULT_SNAPSHOT


def test_missing_snapshot_raises_a_useful_error(monkeypatch):
    monkeypatch.setenv("PROOFWEAVE_SNAPSHOT", str(_ABSENT))
    with pytest.raises(FileNotFoundError) as exc:
        load_snapshot()
    # The message must name the override, or the cause is invisible.
    assert "PROOFWEAVE_SNAPSHOT" in str(exc.value)


def test_explicit_path_wins_over_the_env_var(monkeypatch):
    monkeypatch.setenv("PROOFWEAVE_SNAPSHOT", str(_ABSENT))
    snap = load_snapshot(_DEFAULT_SNAPSHOT)
    assert snap.subject.id == "nvda"


def test_loading_does_not_mutate_the_file_on_disk():
    before = _DEFAULT_SNAPSHOT.read_bytes()
    snap = load_snapshot()
    # The JSON on disk carries no scores; they are derived at load time only.
    raw = json.loads(before.decode("utf-8"))
    assert all(r.get("score") is None for r in raw["relationships"])
    assert all(r.score is not None for r in snap.relationships)


def test_loaded_models_are_frozen():
    """A process-wide cached snapshot must not be mutable through its models."""
    snap = load_snapshot()
    with pytest.raises(ValidationError):
        snap.relationships[0].status = "confirmed"
