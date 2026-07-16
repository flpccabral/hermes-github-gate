"""Test _post_or_update convergence logic (mock gh)."""
import subprocess

def test_semantic_equal_no_patch(gate, monkeypatch):
    """Semanticamente igual → nao chama PATCH."""
    patched = []
    def fake_gh(*args, **kwargs):
        cmd = " ".join(str(a) for a in args)
        if "pr list" in cmd and "--head" in cmd:
            return subprocess.CompletedProcess(args, 0, "42", "")
        if "comments?" in cmd and "page=1" in cmd:
            return subprocess.CompletedProcess(args, 0, 
                '{"id":1,"body":"<!-- hermes-gate:L1-v1:abc:def:end -->\\n```json\\n{\\"head_sha\\":\\"abc\\",\\"base_sha\\":\\"def\\",\\"merge_base_sha\\":\\"ghi\\",\\"overall_status\\":\\"passed\\",\\"checkpoint_present\\":true,\\"errors\\":[],\\"warnings\\":[],\\"validator_version\\":\\"L1-v1\\",\\"next_action\\":\\"merge\\"}\\n```"}', "")
        if "PATCH" in cmd:
            patched.append(True)
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(gate, '_gh', fake_gh)

    fb = {"head_sha": "abc", "base_sha": "def", "merge_base_sha": "ghi",
          "overall_status": "passed", "checkpoint_present": True,
          "errors": [], "warnings": [], "validator_version": "L1-v1",
          "next_action": "merge", "run_id": "r1",
          "timestamps": {"poll_utc": "2026-07-16T21:00:00Z"}}
    body = "## test\n<!-- hermes-gate:L1-v1:abc:def:end -->"
    gate._post_or_update("ai/test", body, fb)
    assert len(patched) == 0, "Semanticamente igual deveria evitar PATCH"

def test_semantic_different_patches(gate, monkeypatch):
    """Semanticamente diferente → faz PATCH."""
    patched = []
    def fake_gh(*args, **kwargs):
        cmd = " ".join(str(a) for a in args)
        if "pr list" in cmd and "--head" in cmd:
            return subprocess.CompletedProcess(args, 0, "42", "")
        if "comments?" in cmd and "page=1" in cmd:
            return subprocess.CompletedProcess(args, 0,
                '{"id":1,"body":"<!-- hermes-gate:L1-v1:abc:def:end -->\\n```json\\n{\\"head_sha\\":\\"abc\\",\\"base_sha\\":\\"def\\",\\"merge_base_sha\\":\\"ghi\\",\\"overall_status\\":\\"failed\\",\\"checkpoint_present\\":false,\\"errors\\":[{\\"code\\":\\"SYNTAX_ERROR\\"}],\\"warnings\\":[],\\"validator_version\\":\\"L1-v1\\",\\"next_action\\":\\"fix_code\\"}\\n```"}', "")
        if "PATCH" in cmd:
            patched.append(True)
            return subprocess.CompletedProcess(args, 0, "", "")
        if "comments/" in cmd and "DELETE" in str(args):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(gate, '_gh', fake_gh)

    fb = {"head_sha": "abc", "base_sha": "def", "merge_base_sha": "ghi",
          "overall_status": "passed", "checkpoint_present": True,
          "errors": [], "warnings": [], "validator_version": "L1-v1",
          "next_action": "merge", "run_id": "r2",
          "timestamps": {"poll_utc": "2026-07-16T21:01:00Z"}}
    body = "## test\n<!-- hermes-gate:L1-v1:abc:def:end -->"
    gate._post_or_update("ai/test", body, fb)
    assert len(patched) == 1, "Diferente deveria fazer PATCH"
