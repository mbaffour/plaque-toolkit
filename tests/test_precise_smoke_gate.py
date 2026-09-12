"""PT-6: the Precise build-acceptance gate must be able to fail.

plaque_app._precise_smoke() printed OK when `n_final >= 0` -- always true for a
count -- and then `return 0` unconditionally. build_macos.sh treats a non-zero exit
as a hard build failure ("FAIL the build rather than ship a broken Precise") and it
is the only Precise check in CI, so a build that loaded torch but detected nothing
shipped as green.

torch/ultralytics are not installed here (and cannot be on this runner), so the
pipeline itself is not exercised; these tests drive the verdict logic directly with
a stubbed run_inprocess.
"""
import os
import sys
import types

import pytest

import plaque_app


@pytest.fixture
def fake_precise(monkeypatch, tmp_path):
    """Stub out precise.pipeline + app.engine_api so only the gate logic runs."""
    state = {"summary": {}}

    pipeline = types.ModuleType("precise.pipeline")
    pipeline.torch_inprocess_available = lambda: True
    pipeline.run_inprocess = lambda *a, **k: state["summary"]
    precise_pkg = types.ModuleType("precise")
    precise_pkg.pipeline = pipeline
    monkeypatch.setitem(sys.modules, "precise", precise_pkg)
    monkeypatch.setitem(sys.modules, "precise.pipeline", pipeline)

    engine_api = types.ModuleType("app.engine_api")
    sample = tmp_path / "sample.tif"
    sample.write_bytes(b"")
    engine_api.resource_path = lambda name: str(sample)
    app_pkg = types.ModuleType("app")
    app_pkg.engine_api = engine_api
    monkeypatch.setitem(sys.modules, "app", app_pkg)
    monkeypatch.setitem(sys.modules, "app.engine_api", engine_api)
    return state, tmp_path


def test_gate_fails_when_nothing_is_detected(fake_precise, capsys):
    state, tmp_path = fake_precise
    overlay = tmp_path / "overlay.jpg"
    overlay.write_bytes(b"x")
    state["summary"] = {"n_final": 0, "n_plaqseg": 0, "overlay": str(overlay)}
    rc = plaque_app._precise_smoke()
    assert rc != 0, "a Precise run that detects nothing must fail the build"
    assert "PRECISE_SMOKE FAIL" in capsys.readouterr().out


def test_gate_fails_when_the_overlay_is_missing(fake_precise):
    state, tmp_path = fake_precise
    state["summary"] = {"n_final": 12, "n_plaqseg": 12,
                        "overlay": str(tmp_path / "never_written.jpg")}
    assert plaque_app._precise_smoke() != 0


def test_gate_passes_on_a_healthy_run(fake_precise, capsys):
    state, tmp_path = fake_precise
    overlay = tmp_path / "overlay.jpg"
    overlay.write_bytes(b"x")
    state["summary"] = {"n_final": 16, "n_plaqseg": 15, "overlay": str(overlay)}
    assert plaque_app._precise_smoke() == 0
    assert "PRECISE_SMOKE OK" in capsys.readouterr().out


def test_minimum_is_configurable(fake_precise, monkeypatch):
    state, tmp_path = fake_precise
    overlay = tmp_path / "overlay.jpg"
    overlay.write_bytes(b"x")
    state["summary"] = {"n_final": 3, "n_plaqseg": 3, "overlay": str(overlay)}
    assert plaque_app._precise_smoke() == 0
    monkeypatch.setenv("PRECISE_SMOKE_MIN", "10")
    assert plaque_app._precise_smoke() != 0


def test_gate_fails_when_torch_is_unavailable(monkeypatch, capsys):
    """The real situation on this runner: no torch -> non-zero, no false green."""
    rc = plaque_app._precise_smoke()
    assert rc != 0
    assert "PRECISE_SMOKE FAIL" in capsys.readouterr().out
