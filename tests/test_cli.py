"""Tests for the typer CLI.

The CLI is a documented entry point in the README, so it gets the same
happy-path / edge / error treatment as the HTTP API.
"""

import json

import pytest
from typer.testing import CliRunner

from proofweave import __version__
from proofweave.cli import app

runner = CliRunner()


def run(*args):
    return runner.invoke(app, list(args))


# --- happy path --------------------------------------------------------------


def test_version():
    result = run("version")
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_summary_lists_relationships():
    result = run("summary")
    assert result.exit_code == 0
    assert "NVIDIA" in result.stdout
    assert "2026-09-29" in result.stdout
    # The digest is one line per counterparty, not per relationship id.
    assert "tsmc" in result.stdout
    assert "supplier" in result.stdout


def test_list_emits_parseable_json():
    result = run("list")
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)
    assert len(rows) == 25


def test_list_filters_by_type():
    result = run("list", "--type", "supplier")
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows
    assert all(r["relation_type"] == "supplier" for r in rows)


def test_list_min_score_and_age_filters():
    result = run("list", "--min-score", "95", "--max-age-days", "180")
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows
    for r in rows:
        assert r["score"]["total"] >= 95
        assert r["score"]["evidence_age_days"] <= 180


def test_list_published_after_filter():
    result = run("list", "--published-after", "2026-06-01")
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows
    assert all(r["score"]["newest_evidence_date"] >= "2026-06-01" for r in rows)


def test_show_returns_the_full_evidence_list():
    result = run("show", "nvda-tsmc-foundry")
    assert result.exit_code == 0
    rel = json.loads(result.stdout)
    assert rel["id"] == "nvda-tsmc-foundry"
    assert rel["evidence"], "show must include the evidence a reviewer needs"
    assert rel["evidence"][0]["locator"]


def test_neighbors_reports_hop_distances():
    result = run("neighbors", "tsmc", "--hops", "2")
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["hop_distances"]["tsmc"] == 0
    assert body["hop_distances"]["nvda"] == 1


def test_path_between_two_suppliers():
    result = run("path", "tsmc", "micron")
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["nodes"] == ["tsmc", "nvda", "micron"]
    assert body["hops"] == 2


def test_path_to_self_is_zero_hops():
    result = run("path", "nvda", "nvda")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["hops"] == 0


def test_graph_writes_a_usable_file(write_dir):
    out = write_dir / "graph.json"
    result = run("graph", "--out", str(out))
    assert result.exit_code == 0
    assert out.exists()
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["nodes"] and body["edges"]
    assert body["subject"]["ticker"] == "NVDA"


def test_audit_passes_on_the_shipped_snapshot():
    result = run("audit")
    assert result.exit_code == 0
    assert "verdict    : OK" in result.stdout
    assert "stale evidence" in result.stdout


def test_stale_emits_json():
    result = run("stale", "--max-age-days", "100")
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert all(r["age_days"] > 100 for r in rows)


# --- error paths -------------------------------------------------------------


@pytest.mark.parametrize("command,args", [
    ("show", ["no-such-id"]),
    ("neighbors", ["no-such-company"]),
    ("path", ["no-such-company", "nvda"]),
    ("path", ["nvda", "no-such-company"]),
])
def test_unknown_ids_exit_three(command, args):
    result = run(command, *args)
    assert result.exit_code == 3


def test_path_beyond_max_hops_exits_three():
    result = run("path", "tsmc", "micron", "--max-hops", "1")
    assert result.exit_code == 3


def test_invalid_date_exits_two():
    result = run("list", "--published-after", "not-a-date")
    assert result.exit_code == 2


def test_invalid_enum_is_rejected():
    result = run("list", "--type", "banana")
    assert result.exit_code != 0


def test_out_of_range_score_is_rejected():
    result = run("list", "--min-score", "150")
    assert result.exit_code != 0


def test_hops_beyond_the_cap_is_rejected():
    result = run("neighbors", "nvda", "--hops", "99")
    assert result.exit_code != 0


def test_no_arguments_shows_help():
    result = run()
    assert "ProofWeave" in result.stdout
