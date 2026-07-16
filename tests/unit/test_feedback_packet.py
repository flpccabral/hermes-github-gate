"""Test _feedback_packet: overall_status, publication_status precedence."""
from gate.github_gate import _make_error

def test_passed_when_clean(gate, sample_fb):
    """Sem erros → overall_status=passed."""
    result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": True}
    fb = gate._feedback_packet("r1", "ai/test", "abc", "def", "ghi", result)
    assert fb["overall_status"] == "passed"
    assert fb["next_action"] == "merge"

def test_failed_when_code_error(gate, sample_fb):
    """Erro category=code → overall_status=failed."""
    result = {"success": False, "errors": [_make_error("SYNTAX_ERROR", "bad code")],
              "warnings": [], "has_checkpoint": True}
    fb = gate._feedback_packet("r1", "ai/test", "abc", "def", "ghi", result)
    assert fb["overall_status"] == "failed"
    assert fb["next_action"] == "fix_code"

def test_infra_error_when_infra(gate, sample_fb):
    """Erro category=infra → overall_status=infra_error."""
    result = {"success": False, "errors": [_make_error("FETCH_TIMEOUT", "timeout")],
              "warnings": [], "has_checkpoint": False}
    fb = gate._feedback_packet("r1", "ai/test", "abc", "def", "ghi", result)
    assert fb["overall_status"] == "infra_error"
    assert fb["next_action"] == "retry"

def test_publication_failed_elevates(gate, sample_fb):
    """publication_status=failed eleva p/ infra_error mesmo se validation passed."""
    result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": True}
    fb = gate._feedback_packet("r1", "ai/test", "abc", "def", "ghi", result,
                                publication_status="failed")
    assert fb["overall_status"] == "infra_error"
    assert fb["next_action"] == "retry_status_publish"

def test_publication_failed_precedence(gate, sample_fb):
    """publication_status=failed → next_action=retry_status_publish (prioridade)."""
    # Mesmo com CHECKPOINT_MISSING antes, publication_status=failed domina
    result = {"success": False, "errors": [_make_error("CHECKPOINT_MISSING", "no checkpoint")],
              "warnings": [], "has_checkpoint": False}
    fb = gate._feedback_packet("r1", "ai/test", "abc", "def", "ghi", result,
                                publication_status="failed")
    assert fb["next_action"] == "retry_status_publish", \
        f"Esperado retry_status_publish, got {fb['next_action']}"
    assert fb["overall_status"] == "infra_error"
