"""CT-R1 web apps (Shiny for Python): plaque_stats/app_py.py ("A", statistics) and
plaque_stats/agreement/app_py.py ("B", agreement).

Each test pins one finding of the round-1 click-through of the web apps (F1..F25). The server
logic lives in small module-level helpers so most of it is tested without a browser; the few
browser tests start the real app on a free port, drive it with Playwright + the installed Chrome,
and skip cleanly when either is missing.
"""
import importlib.util
import io
import os
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

import numpy as np
import pandas as pd
import pytest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS_DIR = os.path.join(ROOT, "plaque_stats")
AG_DIR = os.path.join(PS_DIR, "agreement")
for _d in (PS_DIR, AG_DIR):
    if _d not in sys.path:
        sys.path.insert(0, _d)

pytest.importorskip("shiny")


def _load(name, path):
    """Both apps are files called app_py.py: load each under its own module name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load("ct_web_stats_app", os.path.join(PS_DIR, "app_py.py"))
B = _load("ct_web_agree_app", os.path.join(AG_DIR, "app_py.py"))
import agreement as ag  # noqa: E402
import legend_key as lk  # noqa: E402
import plaque_stats as ps  # noqa: E402


def _pairs(n=40, seed=3):
    rng = np.random.default_rng(seed)
    m = rng.uniform(0.5, 3.0, n)
    t = m * 0.98 + rng.normal(0, 0.05, n)
    return list(np.round(t, 3)), list(np.round(m, 3))


def _agree_stats(n=40):
    t, m = _pairs(n)
    return ag.full_stats(t, m)


def _html(app_module):
    from htmltools import TagList
    return str(TagList(app_module.app_ui))


# =========================================================================== B: F9 legend key
@pytest.mark.parametrize("k", ["both", "a", "b"])
def test_b_f9_every_figure_has_key_download_text_and_switch(k):
    """F9: each of the three agreement figures offers a legend key download and a text starter."""
    html = _html(B)
    assert 'id="dl_key_%s"' % k in html
    assert 'id="key_text_%s"' % k in html
    assert html.count('id="show_key"') == 1 and "Place key on figure" in html


@pytest.mark.parametrize("k,expect,absent", [
    ("both", ["line of identity", "mean bias", "95% limits of agreement"], []),
    ("a", ["line of identity", "least-squares fit"], ["mean bias"]),
    ("b", ["mean bias", "95% limits of agreement", "zero difference"], ["line of identity"]),
])
def test_b_f9_key_text_lists_what_the_figure_draws(k, expect, absent):
    s = _agree_stats()
    fig = B.make_fig(s, B.FIGURES[k][1], show_key=False)
    txt = B.key_text(fig)
    for e in expect:
        assert e in txt
    for a_ in absent:
        assert a_ not in txt
    assert "within the limits of agreement (bluish green, filled circles" in txt


@pytest.mark.parametrize("k", ["both", "a", "b"])
def test_b_f9_key_zip_has_figure_formats_and_text(k):
    s = _agree_stats()
    base = B.FIGURES[k][2]
    fig = B.make_fig(s, B.FIGURES[k][1])
    names = zipfile.ZipFile(io.BytesIO(B.key_zip_bytes(fig, base))).namelist()
    assert sorted(names) == sorted(["%s_legend_key.%s" % (base, f) for f in ("png", "svg", "pdf")]
                                   + ["%s_legend_text.txt" % base])


@pytest.mark.parametrize("k", ["both", "a", "b"])
def test_b_f9_embedded_key_equals_standalone(k):
    s = _agree_stats()
    fig = B.make_fig(s, B.FIGURES[k][1], show_key=True)
    key = lk.from_figure(fig)
    legs = list(fig.legends) + [ax.get_legend() for ax in fig.axes if ax.get_legend()]
    assert len(legs) == 1
    shown = [t.get_text() for t in legs[0].get_texts()]
    assert shown == lk.legend_handles(key)[1]
    # switch off: no key drawn, but the stand-alone key is unchanged
    fig2 = B.make_fig(s, B.FIGURES[k][1], show_key=False)
    assert not fig2.legends and lk.entries_signature(lk.from_figure(fig2)) == lk.entries_signature(key)


# =========================================================================== browser helpers
def _free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def _have_chrome():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:                                       # noqa: BLE001
        return False
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            b.close()
        return True
    except Exception:                                       # noqa: BLE001
        return False


_CHROME = None


def _need_browser():
    global _CHROME
    if _CHROME is None:
        _CHROME = _have_chrome()
    if not _CHROME:
        pytest.skip("playwright or Chrome not available")


class _Server:
    def __init__(self, app_path, tmp_path):
        self.port = _free_port()
        env = dict(os.environ, MPLBACKEND="Agg", TMPDIR=str(tmp_path))
        self.log = open(str(tmp_path / "server.log"), "w")
        self.proc = subprocess.Popen([sys.executable, "-m", "shiny", "run", "--port", str(self.port),
                                      app_path], stdout=self.log, stderr=subprocess.STDOUT, env=env,
                                     cwd=str(tmp_path))
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=2).read(10)
                return
            except Exception:                               # noqa: BLE001
                time.sleep(0.25)
        self.stop()
        pytest.skip("the Shiny app did not start")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except Exception:                                   # noqa: BLE001
            self.proc.kill()
        self.log.close()


def _idle(page, t=0.6):
    time.sleep(t)
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('shiny-busy') && "
        "![...document.querySelectorAll('.recalculating')].some(e => e.offsetParent !== null)",
        timeout=60000)
    time.sleep(0.3)


def _tab(page, text):
    page.locator("a.nav-link", has_text=text).first.click(timeout=10000)
    _idle(page)


def _download(page, port, id_):
    """GET a download link's URL with the page's session (the link must be visible: Shiny only
    binds outputs that are shown)."""
    page.wait_for_function("(i) => (document.getElementById(i).getAttribute('href') || '').length > 1",
                           arg=id_, timeout=30000)
    href = page.get_attribute("#" + id_, "href")
    r = page.request.get("http://127.0.0.1:%d/%s" % (port, href.lstrip("/")), timeout=120000)
    return r.body()


@pytest.fixture
def browser_page():
    """yield a function (app_path, tmp_path, width) -> (page, server); everything is closed after."""
    _need_browser()
    from playwright.sync_api import sync_playwright
    opened = []
    pw = sync_playwright().start()

    def _open(app_path, tmp_path, width=1280):
        srv = _Server(app_path, tmp_path)
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": width, "height": 900})
        opened.append((srv, b))
        page.goto("http://127.0.0.1:%d/" % srv.port)
        page.wait_for_function("() => window.Shiny && Shiny.shinyapp && Shiny.shinyapp.isConnected()",
                               timeout=30000)
        _idle(page)
        return page, srv
    yield _open
    for srv, b in opened:
        b.close()
        srv.stop()
    pw.stop()


def test_b_f9_browser_key_downloads_and_zip(browser_page, tmp_path):
    page, srv = browser_page(os.path.join(AG_DIR, "app_py.py"), tmp_path)
    page.click("#load_example"); _idle(page, 2)
    _tab(page, "B · Bland")
    z = zipfile.ZipFile(io.BytesIO(_download(page, srv.port, "dl_key_b")))
    assert "agreement_B_bland_altman_legend_key.svg" in z.namelist()
    _tab(page, "Both (A + B)")
    assert "mean bias" in page.inner_text("#key_text_both")
    _tab(page, "Statistics")
    allz = zipfile.ZipFile(io.BytesIO(_download(page, srv.port, "dl_all"))).namelist()
    for suffix in ("_legend_key.png", "_legend_key.svg", "_legend_key.pdf", "_legend_text.txt"):
        assert sum(n.endswith(suffix) for n in allz) == 3, (suffix, allz)
