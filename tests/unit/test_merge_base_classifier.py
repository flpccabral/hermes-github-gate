"""Test _classify_merge_base: 0/1/>1 resultados, shallow, dedup."""
import subprocess

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
    """Duplicatas: [x,y,x] conta como 2."""
    sha, err = _classify(gate, ["x", "y", "x"], is_shallow=False)
    assert sha is None
    assert err == "AMBIGUOUS_MERGE_BASE"


def _make_git(calls):
    """Return fake gate._git driven by an ordered list of (command_tokens, response_or_exc).
    response_or_exc may be:
      - subprocess.CompletedProcess
      - subprocess.TimeoutExpired instance
    """
    idx = {"n": 0}

    def fake_git(*args, timeout=60, **kwargs):
        i = idx["n"]
        idx["n"] += 1
        tokens, resp = calls[i]
        # Optionally assert expected tokens
        for t, a in zip(tokens, args):
            assert str(a) == t, f"expected {t} got {a}"
        if isinstance(resp, Exception):
            raise resp
        return resp

    return fake_git, idx


def test_unshallow_timeout(gate, monkeypatch):
    """merge-base falha em shallow repo e fetch --unshallow timeout."""
    calls = [
        (["fetch", "origin", "main"], subprocess.CompletedProcess(["git", "fetch", "origin", "main"], 0, "", "")),
        (["fetch", "origin", "ai/test"], subprocess.CompletedProcess(["git", "fetch", "origin", "ai/test"], 0, "", "")),
        (["cat-file", "-e", "head"], subprocess.CompletedProcess(["git", "cat-file", "-e", "head"], 0, "", "")),
        (["cat-file", "-e", "base"], subprocess.CompletedProcess(["git", "cat-file", "-e", "base"], 0, "", "")),
        (["merge-base", "--all", "base", "head"], subprocess.CompletedProcess(["git", "merge-base", "--all", "base", "head"], 1, "", "")),
        (["rev-parse", "--is-shallow-repository"], subprocess.CompletedProcess(["git", "rev-parse", "--is-shallow-repository"], 0, "true\n", "")),
        (["fetch", "--unshallow"], subprocess.TimeoutExpired(["git", "fetch", "--unshallow"], 60)),
    ]
    fake_git, _ = _make_git(calls)
    monkeypatch.setattr(gate, "_git", fake_git)

    result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
    mb = gate._resolve_merge_base("ai/test", "head", "base", result)

    assert mb is None
    assert result["success"] is False
    assert result["errors"][0]["code"] == "UNSHALLOW_TIMEOUT"
    assert result["errors"][0]["category"] == "infra"


def test_dedup_in_resolve_merge_base(gate, monkeypatch):
    """merge-base --all retorna SHAs duplicados; _resolve_merge_base deduplica."""
    calls = [
        (["fetch", "origin", "main"], subprocess.CompletedProcess(["git", "fetch", "origin", "main"], 0, "", "")),
        (["fetch", "origin", "ai/test"], subprocess.CompletedProcess(["git", "fetch", "origin", "ai/test"], 0, "", "")),
        (["cat-file", "-e", "head"], subprocess.CompletedProcess(["git", "cat-file", "-e", "head"], 0, "", "")),
        (["cat-file", "-e", "base"], subprocess.CompletedProcess(["git", "cat-file", "-e", "base"], 0, "", "")),
        (["merge-base", "--all", "base", "head"], subprocess.CompletedProcess(["git", "merge-base", "--all", "base", "head"], 0, "a\na\nb\na", "")),
        (["rev-parse", "--is-shallow-repository"], subprocess.CompletedProcess(["git", "rev-parse", "--is-shallow-repository"], 0, "false\n", "")),
    ]
    fake_git, _ = _make_git(calls)
    monkeypatch.setattr(gate, "_git", fake_git)

    result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
    mb = gate._resolve_merge_base("ai/test", "head", "base", result)

    # a,a,b,a => dedup mantém ordem => [a,b] => 2 únicos => ambíguo
    assert mb is None
    assert result["success"] is False
    assert result["errors"][0]["code"] == "AMBIGUOUS_MERGE_BASE"
