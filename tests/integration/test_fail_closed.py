import pytest

from gate.github_gate import _make_error, INFRA_CODES


class TestFailClosedIntegration:
    def test_worktree_error_is_infra(self):
        """WORKTREE_FAILED tem category=infra."""
        err = _make_error("WORKTREE_FAILED", "worktree add failed")
        assert err["category"] == "infra"
        assert err["retryable"] is True

    def test_infra_error_derruba_success(self):
        """Erro infra → success deve ser False."""
        err = _make_error("FETCH_TIMEOUT", "timeout")
        result = {"success": True, "errors": [err]}
        for e in result["errors"]:
            if e.get("category") == "infra" or e.get("code") in INFRA_CODES:
                result["success"] = False
        assert result["success"] is False
