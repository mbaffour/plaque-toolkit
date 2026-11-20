"""Detection benchmark harness: runs THIS checkout's real code in-process.

Adapted from the round-2 tester's h2.py (CT-R2 detection) with the repository located from this
file instead of an absolute path:

* ``app_run(path, mm, scale)`` -- app.engine_api.detect_single + measure_table(with_reason): the
  exact table the Measure tab shows (QC_FLAG / QC_REASON / SOURCE) + plaque dicts. Used for Auto.
* ``cli_run(path, mm, small)`` -- plaque_size_tool._process_one as main() calls it: the CLI
  default (``standard``) and ``-small`` (``small``) rows, every row sized.
* ``match`` -- the tester's greedy one-to-one nearest-centre matching, verbatim.
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import warnings

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
# the app reads user training data from here; an empty folder keeps runs independent of it
os.environ.setdefault("PLAQUE_TRAINING_DIR", tempfile.mkdtemp(prefix="bench_training_"))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import numpy as np  # noqa: E402
import cv2  # noqa: E402
cv2.setNumThreads(2)
import pandas as pd  # noqa: E402
import plaque_size_tool as pst  # noqa: E402
import plaque_qc  # noqa: E402
import plaque_scales  # noqa: E402
from app import engine_api  # noqa: E402

SAMPLE_TIF = os.path.join(REPO, "app", "resources", "sample.tif")
TEST_PLATES = os.path.join(REPO, "Test_plates")


def bundled_plates():
    """[(name, path, plate_mm)]: Test_plates/large (90 mm), small (55 mm), sample.tif (100 mm)."""
    out = []
    for folder, mm in (("large", 90), ("small", 55)):
        d = os.path.join(TEST_PLATES, folder)
        for f in sorted(os.listdir(d), key=lambda s: (len(s), s)):
            if f.endswith(".tif"):
                out.append((folder + "/" + f[:-4], os.path.join(d, f), mm))
    out.append(("sample/sample", SAMPLE_TIF, 100))
    return out


def _in_std_blob(det):
    """Per plaque: does its centre lie on a standard-mask (block-231) blob? The structural fact
    resolve_halos uses for small-pass cores (label 0 = outside every blob)."""
    proc = det.get("proc_gray")
    if proc is None or det.get("scale") != "auto":
        return [None] * len(det["plaques"])
    m = plaque_scales.standard_mask(proc)
    _n, lab = cv2.connectedComponents(m, connectivity=8)
    H, W = lab.shape
    out = []
    for p in det["plaques"]:
        x = min(max(int(round(p["center"][0])), 0), W - 1)
        y = min(max(int(round(p["center"][1])), 0), H - 1)
        out.append(bool(lab[y, x] != 0))
    return out


def app_run(path, mm, scale="auto", sensitive=False, published=False):
    det = engine_api.detect_single(path, plate_mm=mm, scale=scale, sensitive=sensitive,
                                   published=published)
    pl = det["plaques"]
    df = engine_api.measure_table(pl, det["orig_bgr"], det["pxl_per_mm"], det["lawn_gray"],
                                  published=published, plate=det["plate"], with_reason=True)
    if len(df):
        df["X"] = [p["center"][0] for p in pl]
        df["Y"] = [p["center"][1] for p in pl]
        df["SIZE_OK"] = [plaque_qc.size_ok(f) for f in df["QC_FLAG"]]
        df["CORE_ONLY"] = [bool(p.get("core_only")) for p in pl]
        df["IN_STD_BLOB"] = _in_std_blob(det)
    det["df"] = df
    return det


_orig = dict(write_data=pst.write_data, write_images=pst.write_images)


def cli_run(path, mm, small=False):
    """The CLI default (small=False) or -small rows of one image, as main() would write them.
    Returns (green DataFrame with X, Y, SIZE_OK=True, SOURCE='auto'; plate px diameter or None)."""
    cap = {}

    def _wd(o, ip, g, r, ot):
        cap["green"] = g

    tmp = tempfile.mkdtemp(prefix="bench_cli_")
    pst.small_plaques = bool(small)
    pst.debug_mode = False
    pst.upstream_exact = False
    pst.use_published = False
    pst.watershed_enabled = False
    pst.sensitive = False
    pst.multiscale = False
    pst.out_dir_path = tmp
    pst._output_stems = {}
    pst.last_calibration['mm_per_px'] = None
    pst.last_calibration['warned_no_dish'] = True
    pst.write_data, pst.write_images = _wd, (lambda *a, **k: None)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pst._process_one(path, str(mm) if mm else None, [], {"qc": False})
    finally:
        pst.write_data, pst.write_images = _orig["write_data"], _orig["write_images"]
        pst.small_plaques = False
        shutil.rmtree(tmp, ignore_errors=True)
    g = cap["green"].copy()
    if len(g):
        g["X"] = [float(c[0]) for c in g["ENCL_CENTER"]]
        g["Y"] = [float(c[1]) for c in g["ENCL_CENTER"]]
        g["DIAMETER_MM"] = pd.to_numeric(g["DIAMETER_MM"], errors="coerce")
    g["SOURCE"] = "auto"
    g["QC_FLAG"] = "OK"
    g["SIZE_OK"] = True
    g["CORE_ONLY"] = False
    mpp = pst.last_calibration.get("mm_per_px")
    return g, (float(mm) / mpp if (mm and mpp) else None)


def match(a, b, tol):
    """greedy NN one-to-one matching of (N,2) arrays; tol scalar or per-a array (tester's)."""
    a = np.asarray(a, float).reshape(-1, 2)
    b = np.asarray(b, float).reshape(-1, 2)
    if len(a) == 0 or len(b) == 0:
        return []
    tol = np.broadcast_to(np.asarray(tol, float), (len(a),))
    d = np.hypot(a[:, None, 0] - b[None, :, 0], a[:, None, 1] - b[None, :, 1])
    order = np.dstack(np.unravel_index(np.argsort(d, axis=None), d.shape))[0]
    ui, uj, out = set(), set(), []
    for i, j in order:
        if i in ui or j in uj or d[i, j] > tol[i]:
            continue
        ui.add(i)
        uj.add(j)
        out.append((int(i), int(j)))
    return out
