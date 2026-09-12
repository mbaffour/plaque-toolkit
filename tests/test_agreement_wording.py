"""PT-4: the "paste-ready" manuscript sentence must follow the statistics.

The repo shipped validation/figures/agreement_report_tiny_diameter.md saying
"closely agreed ... highly correlated (Pearson r = -0.013 ...) ICC(A,1) = -0.012
... (poor agreement)" -- a self-contradicting sentence in text explicitly labelled
ready to paste into a manuscript.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "plaque_stats", "agreement"))

import agreement as ps_agreement          # noqa: E402  plaque_stats/agreement
from app import agreement as app_agreement  # noqa: E402


BASE = dict(n=20, r=0.0, r2=0.0, pearson_p=0.5, icc=0.0, icc_lo=float("nan"),
            icc_hi=float("nan"), ccc=0.0, bias=0.015, pct_bias=3.6, t_p=0.26,
            loa_lo=-0.10, loa_hi=0.13, slope=-0.02)


def _ps(**over):
    s = dict(BASE)
    s.update(over)
    return ps_agreement.report_sentence(s, "mm", "diameter", "Plaque Toolkit", "Fiji / ImageJ")


def test_poor_agreement_is_not_described_as_close_agreement():
    """The exact committed case: r = -0.013, ICC = -0.012."""
    sent = _ps(r=-0.0126, icc=-0.0121, pearson_p=0.958)
    assert "closely agreed" not in sent
    assert "highly correlated" not in sent
    assert "did NOT agree at the individual level" in sent
    assert "poor agreement" in sent
    assert "cannot be used interchangeably" in sent


def test_excellent_agreement_still_reads_as_agreement():
    """The primary validation (r = 0.979, ICC = 0.974) must not be talked down."""
    sent = _ps(r=0.979, r2=0.958, icc=0.974, pearson_p=0.0001, ccc=0.974)
    assert "agreed closely with" in sent
    assert "very strongly correlated" in sent
    assert "excellent agreement" in sent
    assert "cannot be used interchangeably" not in sent


@pytest.mark.parametrize("icc,expected", [
    (0.95, "agreed closely with"),
    (0.80, "agreed well with"),
    (0.60, "agreed only moderately with"),
    (0.20, "did NOT agree at the individual level with"),
    (float("nan"), "could not be compared with"),
])
def test_icc_bands(icc, expected):
    assert ps_agreement.agreement_phrase(icc) == expected
    assert app_agreement.agreement_phrase(icc) == expected


@pytest.mark.parametrize("r,p,expected", [
    (0.95, 0.001, "very strongly correlated"),
    (0.80, 0.001, "strongly correlated"),
    (0.60, 0.001, "moderately correlated"),
    (0.40, 0.001, "weakly correlated"),
    (0.10, 0.001, "essentially uncorrelated"),
    (0.95, 0.20, "not significantly correlated"),
    (-0.80, 0.001, "INVERSELY strongly correlated"),
])
def test_correlation_bands(r, p, expected):
    assert ps_agreement.correlation_phrase(r, p) == expected


def test_the_committed_artefacts_no_longer_contradict_themselves():
    """Regression on the shipped validation reports themselves."""
    figs = os.path.join(REPO_ROOT, "validation", "figures")
    for name in sorted(os.listdir(figs)):
        if not name.startswith("agreement_report_"):
            continue
        text = open(os.path.join(figs, name), encoding="utf-8").read()
        sentence = [l for l in text.splitlines() if l.startswith("> ")]
        assert sentence, name
        line = sentence[0]
        if "poor agreement" in line:
            assert "closely" not in line and "highly correlated" not in line, name
            assert "did NOT agree" in line, name


def test_app_agreement_module_matches():
    s = dict(n=20, r=-0.013, icc=-0.012, bias=0.015, pct_bias=3.6,
             loa_lo=-0.10, loa_hi=0.13, slope=-0.02)
    sent = app_agreement.report_sentence(s)
    assert "did NOT agree at the individual level" in sent
    assert "poor agreement" in sent
