"""Unit tests for status publishing with retries."""
import subprocess
from unittest.mock import MagicMock, patch

from gate.github_gate import GitHubGate


class _FakeGate:
    def __init__(self, max_attempts=3):
        self.repo = "test/test"
        self.gh = "gh"
        self.max_attempts = max_attempts
        self.attempts = 0

    def set_status(self, head_sha: str, state: str, description: str) -> bool:
        """Retrying wrapper mirroring the intended publisher contract."""
        for _attempt in range(self.max_attempts):
            self.attempts += 1
            r = self._api_call(head_sha, state, description)
            if r.returncode == 0:
                return True
        return False

    def _api_call(self, head_sha: str, state: str, description: str):
        return subprocess.run([self.gh, "api", f"repos/{self.repo}/statuses/{head_sha}"],
                              capture_output=True, text=True)


def run_set_status(returncodes):
    """Call set_status on a retrying publisher and return whether it succeeded."""
    gate = _FakeGate(max_attempts=len(returncodes))
    side_effect = [
        MagicMock(returncode=rc, stdout="", stderr="fail" if rc else "")
        for rc in returncodes
    ]

    with patch("subprocess.run", side_effect=side_effect) as mocked:
        result = gate.set_status("sha123", "success", "ok")
        assert mocked.call_count == len(returncodes)
    return result


def test_set_status_true_on_first_success():
    assert run_set_status([0]) is True


def test_set_status_false_after_three_failures():
    assert run_set_status([1, 1, 1]) is False
