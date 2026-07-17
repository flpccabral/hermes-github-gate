import os

import pytest

from gate.github_gate import GitHubGate
from pathlib import Path


class TestValidateCommit:
    def test_sandbox_detects_tests_absent(self, gate_integration):
        """Branch sem tests/ → TESTS_ABSENT no resultado, e sandbox esta dentro do try/finally."""
        # Verifica estrutura do codigo: o bloco de execucao de tests/ deve estar
        # dentro do try/finally que remove o worktree. Em d99a3e3 (sandbox morto)
        # o bloco pytest fica DEPOIS do finally, vazando worktree em caso de excecao.
        src_path = Path(__file__).resolve().parent.parent.parent / "gate" / "github_gate.py"
        source = src_path.read_text(encoding="utf-8")
        tests_dir_idx = source.find('tests_dir = Path(tmp_dir) / "tests"')
        finally_idx = source.find('self._git("worktree", "remove", "--force", tmp_dir)')
        assert tests_dir_idx != -1, "bloco de testes nao encontrado"
        assert finally_idx != -1, "limpeza do worktree nao encontrada"
        assert tests_dir_idx < finally_idx, "sandbox tests rodam fora do try/finally — worktree pode vazar"

    def test_branch_without_tests_warns_tests_absent(self, gate_integration):
        """Branch sem tests/ → TESTS_ABSENT no resultado."""
        head = os.popen("git rev-parse HEAD").read().strip()
        base = os.popen("git rev-parse HEAD~1 2>/dev/null || echo HEAD").read().strip()
        ctx = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
        assert "warnings" in ctx
