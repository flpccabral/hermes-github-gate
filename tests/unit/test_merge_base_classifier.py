"""Test _classify_merge_base: 0/1/>1 resultados, shallow, dedup."""
from gate.github_gate import GitHubGate

def _classify(gate, all_mb, is_shallow=False):
    return gate._classify_merge_base(all_mb, is_shallow)

def test_zero_shallow(gate):
    """0 resultados + shallow → HISTORY_INCOMPLETE."""
    sha, err = _classify(gate, [], is_shallow=True)
    assert sha is None
    assert err == "HISTORY_INCOMPLETE"

def test_zero_complete(gate):
    """0 resultados + nao shallow → UNRELATED_HISTORIES."""
    sha, err = _classify(gate, [], is_shallow=False)
    assert sha is None
    assert err == "UNRELATED_HISTORIES"

def test_one_result(gate):
    """1 resultado → retorna SHA."""
    sha, err = _classify(gate, ["a1b2c3d4e5"], is_shallow=False)
    assert sha == "a1b2c3d4e5"
    assert err is None

def test_multiple_results(gate):
    ">1 resultados → AMBIGUOUS_MERGE_BASE."
    sha, err = _classify(gate, ["a", "b"], is_shallow=False)
    assert sha is None
    assert err == "AMBIGUOUS_MERGE_BASE"

def test_dedup(gate):
    """Duplicatas: [a,b,a] conta como 2."""
    sha, err = _classify(gate, ["x", "y", "x"], is_shallow=False)
    assert sha is None
    assert err == "AMBIGUOUS_MERGE_BASE"
