"""Load the frozen JSON snapshot shipped inside the repo.

We deliberately do NOT call the network at import time.  The JSON file is
the single source of truth for review; re-crawling is a separate
developer-facing command (see README) and its output must be reviewed by
a human before being committed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..models import Snapshot
from ..scoring import score_relationship

_DEFAULT_SNAPSHOT = Path(__file__).parent / "snapshot_2026_09_29.json"

_SNAPSHOT_ENV_VAR = "PROOFWEAVE_SNAPSHOT"


def default_snapshot_path() -> Path:
    """The snapshot to load when no path is given.

    ``PROOFWEAVE_SNAPSHOT`` overrides the bundled file, so someone reviewing a
    refreshed snapshot can point the CLI and API at it without editing code or
    reinstalling.
    """
    override = os.environ.get(_SNAPSHOT_ENV_VAR)
    return Path(override) if override else _DEFAULT_SNAPSHOT


def load_snapshot(path: str | Path | None = None) -> Snapshot:
    p = Path(path) if path else default_snapshot_path()
    if not p.exists():
        raise FileNotFoundError(
            f"snapshot not found: {p}"
            + (f" (from {_SNAPSHOT_ENV_VAR})" if os.environ.get(_SNAPSHOT_ENV_VAR) else "")
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    snap = Snapshot.model_validate(data)
    # Re-score every relation at load time so the score is always derived,
    # never hand-typed into JSON.  The models are frozen, so this rebuilds the
    # relationships rather than assigning the score in place.
    scored = [rel.model_copy(update={"score": score_relationship(rel)})
              for rel in snap.relationships]
    return snap.model_copy(update={"relationships": scored})
