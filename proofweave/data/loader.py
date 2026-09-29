"""Load the frozen JSON snapshot shipped inside the repo.

We deliberately do NOT call the network at import time.  The JSON file is
the single source of truth for review; re-crawling is a separate
developer-facing command (see README) and its output must be reviewed by
a human before being committed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Snapshot
from ..scoring import score_relationship

_DEFAULT_SNAPSHOT = Path(__file__).parent / "snapshot_2026_09_29.json"


def load_snapshot(path: str | Path | None = None) -> Snapshot:
    p = Path(path) if path else _DEFAULT_SNAPSHOT
    data = json.loads(p.read_text(encoding="utf-8"))
    snap = Snapshot.model_validate(data)
    # Re-score every relation at load time so the score is always derived,
    # never hand-typed into JSON.
    for rel in snap.relationships:
        rel.score = score_relationship(rel)
    return snap
