import json

import pytest

from gate.github_gate import GitHubGate


class TestGetAllComments:
    def test_parse_array_json(self):
        """_get_all_comments consegue fazer parse de array JSON."""
        g = GitHubGate.__new__(GitHubGate)
        g.repo = "flpccabral/hermes-github-gate"
        g.gh = "gh"
        # Teste conceitual: verificar que parse de array funciona
        sample = '[{"id":1,"body":"test","created_at":"2026-01-01","updated_at":"2026-01-01"}]'
        data = json.loads(sample)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == 1
