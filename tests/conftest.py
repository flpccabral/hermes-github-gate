import pytest, sys, json, os, subprocess
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gate.github_gate import GitHubGate, _make_error, INFRA_CODES

# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def gate():
    """Gate instance that skips _check_gh."""
    g = GitHubGate.__new__(GitHubGate)
    g.repo = "flpccabral/hermes-github-gate"
    g.gh = "gh"
    g._log = lambda msg: None  # silent
    return g

@pytest.fixture
def marker():
    return "<!-- hermes-gate:L1-v1:abc123:def456:end -->"

@pytest.fixture
def sample_fb():
    return {
        "schema_version": "1.0", "run_id": "test",
        "validator_version": "L1-v1",
        "branch": "ai/test",
        "head_sha": "abc123", "base_sha": "def456", "merge_base_sha": "ghi789",
        "overall_status": "passed",
        "checkpoint_present": True,
        "errors": [],
        "warnings": [],
        "next_action": "merge",
        "timestamps": {"poll_utc": "2026-07-16T21:00:00Z"},
    }
