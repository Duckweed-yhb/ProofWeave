# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-29

Scores change in this release. 11 of the 25 relationships in the shipped
snapshot score differently from 0.1.0 because the recency term was wrong; see
"Fixed" below. The scoring formula is unchanged otherwise.

### Added

- `GET /` index listing the available endpoints, for reviewers landing on the
  API without the README.
- `GET /graph/neighbors/{company_id}?hops=1..3` — induced subgraph around a
  company with per-node hop distances (`proofweave/graph.py`).
- `GET /graph/path?source=&target=&max_hops=` — shortest undirected path
  between two companies, with the traversed edges.
- `GET /audit` and `proofweave audit` — a self-check of the shipped snapshot:
  structural invariants, evidence attribution, and a recomputation of every
  score, so a hand-edited score can no longer ship unnoticed. Exits non-zero
  when the snapshot is inconsistent, and runs in CI.
- `GET /stale` and `proofweave stale` — relationships whose newest evidence is
  older than a given number of days.
- Time-dimension filters on `/relationships` and `proofweave list`:
  `published_after` and `max_age_days`.
- `proofweave neighbors`, `proofweave path` and `proofweave version` commands.
- `ScoreBreakdown.newest_evidence_date` and `ScoreBreakdown.evidence_age_days`,
  so the recency term shows what it was measured against.
- `PROOFWEAVE_SNAPSHOT` environment variable support in
  `proofweave.data.loader`, which `.env.example` had documented but nothing read.
- Test coverage for the CLI and for the shared graph/audit layer (was: none).
- `ruff` configuration, and a lint step plus a snapshot audit in CI.

### Fixed

- **The recency term was a constant.** It was derived from `Evidence.accessed_at`,
  and every source in a frozen snapshot is accessed on the snapshot date, so all
  25 relationships collected an identical `+10`. The 0/3/6/10 term documented in
  the README therefore discriminated nothing. It is now derived from
  `published_at` (falling back to `accessed_at` only for undated sources), which
  is what actually makes a claim fresh. The term now takes three distinct values
  and the snapshot's score spread widened from 6 to 9 distinct values.
- The models claimed to be frozen in their docstring but were not; they now are.
  This matters because the API caches the snapshot process-wide, so in-place
  mutation would have leaked one request's edits into every later request.
- `proofweave graph` wrote `graph.json`, but `.gitignore` only covered
  `.graph.json`, so running it left an untracked file behind.
- `.env.example` referenced a `scripts/refresh_snapshot.py` that does not exist.
- README corrections: the coverage table said 23 company nodes when the snapshot
  has 24 (21 listed + 3 unlisted, including the synthetic anonymous-customer
  node), and it advertised "23 passed" tests when the suite had 24.
- The `/graph/path` 404 message said "within 1 hops".

### Changed

- Query and traversal logic moved into `proofweave/graph.py`, shared by the API
  and the CLI; the two previously duplicated their filtering and graph-building
  code and could drift apart.
- The API declares response models for every route (previously `/health`,
  `/stats`, `/graph` and the page wrapper returned bare dicts), so `/docs` shows
  the real shapes.
- The version is single-sourced from `proofweave/__init__.py`; `pyproject.toml`
  reads it dynamically instead of repeating it.
- `proofweave list`'s `--type` option no longer shadows the builtin `type`.

## [0.1.0] - 2026-09-29

Initial release: a frozen, reviewable NVIDIA supply-chain and partnership
snapshot with an explainable 0-100 score, a FastAPI service and a `typer` CLI.

[Unreleased]: https://github.com/Duckweed-yhb/ProofWeave/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Duckweed-yhb/ProofWeave/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Duckweed-yhb/ProofWeave/releases/tag/v0.1.0
