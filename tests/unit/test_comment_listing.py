"""Test _get_all_comments parsing logic (mock gh)."""
import json

def _make_gh_response(data, rc=0):
    """Simula CompletedProcess com stdout string (text=True)."""
    import subprocess
    stdout = "\n".join(json.dumps(d) for d in data) if data else ""
    return subprocess.CompletedProcess(["gh"], rc, stdout, "")

def test_valid_json_added(gate, monkeypatch):
    """JSON valido → adicionado a comments."""
    calls = []
    def fake_gh(*args, **kwargs):
        calls.append(args)
        if "page=1" in str(args):
            return _make_gh_response([{"id": 1, "body": "hello"}])
        return _make_gh_response([])
    monkeypatch.setattr(gate, '_gh', fake_gh)
    res = gate._get_all_comments("1")
    assert res["status"] in ("complete", "complete_empty")
    assert len(res["comments"]) >= 1

def test_invalid_json_fails(gate, monkeypatch):
    """JSON invalido → status=failed, error=COMMENT_LIST_PARSE_FAILED."""
    import subprocess
    def fake_gh(*args, **kwargs):
        # Return malformed JSON
        return subprocess.CompletedProcess(args, 0, "not json{{{", "")
    monkeypatch.setattr(gate, '_gh', fake_gh)
    res = gate._get_all_comments("1")
    assert res["status"] == "failed"
    assert "COMMENT_LIST_PARSE_FAILED" in res.get("error", "")

def test_api_fail_first_page(gate, monkeypatch):
    """Falha na primeira pagina → status=failed."""
    import subprocess
    def fake_gh(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, b"", b"rate limit")
    monkeypatch.setattr(gate, '_gh', fake_gh)
    res = gate._get_all_comments("1")
    assert res["status"] == "failed"
    assert "rate limit" in res.get("error", "").lower() or "API error" in res.get("error", "")
