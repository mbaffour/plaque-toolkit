"""`plaque_app.py --smoke` also runs one statistics analysis and one agreement computation, and
fails when either errors (the frozen macOS app's build gate then proves the statistics stack
works inside the bundle; CI 2026-11, after SciPy 1.17 broke every analysis unnoticed)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytest.importorskip("cv2")
from app import engine_api  # noqa: E402


def test_smoke_stats_and_agreement_run():
    assert "p = " in engine_api._smoke_stats()
    assert "ICC" in engine_api._smoke_agreement()


@pytest.mark.parametrize("which", ["_smoke_stats", "_smoke_agreement"])
def test_smoke_fails_when_the_statistics_fail(monkeypatch, capsys, which):
    def boom():
        raise RuntimeError("simulated statistics failure")
    monkeypatch.setattr(engine_api, which, boom)
    assert engine_api.smoke() == 1
    out = capsys.readouterr().out
    assert "simulated statistics failure" in out and "SMOKE FAIL" in out
