"""Unit tests for status publishing with retries."""
import time
from unittest.mock import MagicMock

import pytest


def _make_gh(side_effects):
    """Return a fake _gh that returns configured CompletedProcesses in order."""
    calls = {"count": 0}

    def fake_gh(*args, **kwargs):
        idx = calls["count"]
        calls["count"] += 1
        rc = side_effects[idx]
        return MagicMock(returncode=rc, stdout="", stderr="fail" if rc else "")

    return fake_gh, calls


def test_set_status_true_on_first_success(gate, monkeypatch):
    fake_gh, calls = _make_gh([0])
    monkeypatch.setattr(gate, "_gh", fake_gh)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    assert gate.set_status("sha123", "success", "ok", max_retries=3) is True
    assert calls["count"] == 1


def test_set_status_true_after_retry(gate, monkeypatch):
    fake_gh, calls = _make_gh([1, 0])
    monkeypatch.setattr(gate, "_gh", fake_gh)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    assert gate.set_status("sha123", "success", "ok", max_retries=3) is True
    assert calls["count"] == 2


def test_set_status_false_after_three_failures(gate, monkeypatch):
    fake_gh, calls = _make_gh([1, 1, 1])
    monkeypatch.setattr(gate, "_gh", fake_gh)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    assert gate.set_status("sha123", "success", "ok", max_retries=3) is False
    assert calls["count"] == 3
