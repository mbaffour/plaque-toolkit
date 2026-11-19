"""Click-through round 1 (CT-R1) findings F1..F24 for the R Shiny app (plaque_stats/app.R).

Runs tests/r_ct_r1_check.R with Rscript (shiny::testServer, plain function calls) and asserts
every line it prints: "PASS <id>" or "FAIL <id> <detail>". The R-vs-Python numbers (Welch ANOVA,
Games-Howell, Tukey, Welch t, Mann-Whitney) are pinned inside the R script as constants that
plaque_stats.py produced. Skipped where R or the app's packages are missing, exactly as
test_legend_key::test_r_shiny_app_key and test_paper_style.
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINDINGS = ["F%d" % i for i in range(1, 25)]


@pytest.fixture(scope="module")
def r_checks(tmp_path_factory):
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("R not installed")
    pkgs = 'c("shiny","ggplot2","dplyr","tidyr","readr","DT","ggpubr","svglite","jsonlite")'
    ok = subprocess.run([rscript, "-e", "q(status = !all(sapply(%s, requireNamespace, "
                         "quietly = TRUE)))" % pkgs], capture_output=True)
    if ok.returncode != 0:
        pytest.skip("the R app's packages are not installed")
    out_dir = tmp_path_factory.mktemp("ct_r1")
    cwd = os.path.join(ROOT, "plaque_stats")
    r = subprocess.run([rscript, os.path.join(ROOT, "tests", "r_ct_r1_check.R")], cwd=cwd,
                       capture_output=True, text=True, env=dict(os.environ, OUT_DIR=str(out_dir)),
                       timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    lines = [m.groups() for m in (re.match(r"(PASS|FAIL) (\S+)(.*)", x) for x in r.stdout.splitlines()) if m]
    # no stray graphics-device file is ever written into the app folder
    assert not os.path.exists(os.path.join(cwd, "Rplots.pdf"))
    return lines


def test_every_check_passes(r_checks):
    failed = ["%s %s" % (i, d.strip()) for s, i, d in r_checks if s == "FAIL"]
    assert not failed, "\n".join(failed)
    assert len(r_checks) >= 100


@pytest.mark.parametrize("finding", FINDINGS)
def test_finding_is_covered_by_a_passing_check(r_checks, finding):
    ids = [i for s, i, _ in r_checks if i.split("_")[0] == finding and s == "PASS"]
    assert ids, finding
