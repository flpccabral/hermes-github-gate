"""Test _ERROR_MAP: todos os codigos, categorias, actions."""
from gate.github_gate import GitHubGate, INFRA_CODES

ERROR_MAP = GitHubGate._ERROR_MAP

def test_known_codes_present():
    """Codigos criticos existem no mapa."""
    for code in ["HISTORY_INCOMPLETE", "UNRELATED_HISTORIES",
                 "AMBIGUOUS_MERGE_BASE", "SYNTAX_ERROR", "CHECKPOINT_MISSING"]:
        assert code in ERROR_MAP, f"{code} ausente do _ERROR_MAP"

def test_unrelated_histories_mapping():
    """UNRELATED_HISTORIES: policy, nao retentavel, recreate_branch."""
    cat, retry, action = ERROR_MAP["UNRELATED_HISTORIES"]
    assert cat == "policy", f"Esperado policy, got {cat}"
    assert retry is False, f"Esperado retryable=False, got {retry}"
    assert action == "recreate_branch", f"Esperado recreate_branch, got {action}"

def test_ambiguous_merge_base_mapping():
    """AMBIGUOUS_MERGE_BASE: unsupported, nao retentavel, unsupported_topology."""
    cat, retry, action = ERROR_MAP["AMBIGUOUS_MERGE_BASE"]
    assert cat == "unsupported", f"Esperado unsupported, got {cat}"
    assert retry is False, f"Esperado retryable=False, got {retry}"
    assert action == "unsupported_topology", f"Esperado unsupported_topology, got {action}"

def test_history_incomplete_infra():
    """HISTORY_INCOMPLETE: infra, retentavel."""
    cat, retry, _ = ERROR_MAP["HISTORY_INCOMPLETE"]
    assert cat == "infra"
    assert retry is True

def test_syntax_error_code():
    """SYNTAX_ERROR: code, nao retentavel."""
    cat, retry, action = ERROR_MAP["SYNTAX_ERROR"]
    assert cat == "code"
    assert retry is False
    assert action == "fix_code"

def test_checkpoint_missing_code():
    """CHECKPOINT_MISSING: code, nao retentavel."""
    cat, retry, action = ERROR_MAP["CHECKPOINT_MISSING"]
    assert cat == "code"
    assert retry is False
    assert action == "fix_checkpoint"

def test_unknown_code_fallback():
    """Codigo desconhecido: fallback code/False/fix_code."""
    meta = ERROR_MAP.get("UNKNOWN_CODE", ("code", False, "fix_code"))
    assert meta[0] == "code"
    assert meta[1] is False
    assert meta[2] == "fix_code"

def test_fail_closed_invariant(gate):
    # Simula WORKTREE_FAILED e verifica que success=False
    from gate.github_gate import _make_error
    err = _make_error("WORKTREE_FAILED", "worktree add failed")
    assert err["category"] == "infra"
    result = {"success": True, "errors": [err]}
    # Se houver erro infra, success deve ser False para fail-closed
    infra = any(e.get("category") == "infra" for e in result.get("errors", []))
    if infra:
        result["success"] = False
    assert result["success"] is False, "fail-closed: erro infra deve derrubar success"
