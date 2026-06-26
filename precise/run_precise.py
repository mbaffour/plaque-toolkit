"""Precise pipeline -- top-level orchestrator (two-env handoff).

Given one image + plate_mm + out dir, it:
  1. runs precise/pst_front.py in the PLAQUE env   -> <out>/<tag>_pst.json
     (dish geometry, calibration mm_per_px, PST normal+sensitive centers)
  2. runs _plaqseg/run_plaqseg.py in the PLAQSEG env on the ORIGINAL image
     (--conf 0.1 --iou 0.5 --ppm <mm_per_px from step 1>) -> plaqseg_<tag>.csv
  3. runs precise/combine.py in the PLAQSEG env (masks, density switch, recall
     gating, blob recovery, combine, sizing, overlay) -> precise_<tag>.csv +
     precise_overlay_<tag>.jpg + summary_<tag>.json

The mm/px unit handling is a known trap: plaque_gui's "pxl_per_mm" is actually
mm-per-pixel, and run_plaqseg.py's --ppm expects mm-per-pixel, so it is passed
through unchanged.

Usage:
  python run_precise.py --image IMG --out OUTDIR [--tag TAG] [--plate-mm 100]
                        [--conf 0.1] [--iou 0.5] [--weights .../small.pt]
"""
import argparse
import os
import subprocess
import json
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)   # so `from app.env_paths import ...` resolves standalone

# Portable interpreter discovery (Windows envs/<x>/python.exe vs posix envs/<x>/bin/python).
# Overridable per-machine via the PLAQUE_PY / PLAQSEG_PY env vars or --plaque-py/--plaqseg-py.
try:
    from app.env_paths import find_env_python
except Exception:                      # pragma: no cover - keep working with no app pkg
    def find_env_python(name):
        cand = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(sys.executable)))), "envs", name,
            "python.exe" if os.name == "nt" else os.path.join("bin", "python"))
        return cand if os.path.exists(cand) else None

# Default to the running interpreter for the plaque stage (run_precise itself is launched
# from the plaque env); fall back to discovery, then to sys.executable.
PLAQUE_PY = find_env_python("plaque") or sys.executable
PLAQSEG_PY = find_env_python("plaqseg") or "python"
RUN_PLAQSEG = os.path.join(ROOT, "_plaqseg", "run_plaqseg.py")
DEFAULT_WEIGHTS = os.path.join(ROOT, "_plaqseg", "models", "small.pt")


def run(cmd, cwd=None, env=None):
    print("[run]", " ".join('"%s"' % c if " " in c else c for c in cmd))
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if p.stdout:
        print(p.stdout.rstrip())
    if p.returncode != 0:
        print(p.stderr.rstrip(), file=sys.stderr)
        raise SystemExit("step failed (rc=%d): %s" % (p.returncode, cmd[2] if len(cmd) > 2 else cmd))
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--plate-mm", default="100")
    ap.add_argument("--conf", default="0.1")
    ap.add_argument("--iou", default="0.5")
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS)
    ap.add_argument("--plaque-py", default=PLAQUE_PY)
    ap.add_argument("--plaqseg-py", default=PLAQSEG_PY)
    ap.add_argument("--blob", action="store_true",
                    help="enable the optional blob_log recovery pass (stage 7); OFF by default "
                         "because it over-detects on textured lawns (net false positives)")
    ap.add_argument("--clf", action="store_true",
                    help="enable the optional learned precision gate (stage 7.5): re-score "
                         "every candidate with _research/clf/plaque_clf.pt and drop P(plaque) "
                         "below --clf-thr. OFF by default (validated path unchanged).")
    ap.add_argument("--clf-thr", default=None,
                    help="P(plaque) threshold for the learned gate (default 0.5 / model default).")
    a = ap.parse_args()

    image = os.path.abspath(a.image)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    tag = a.tag or os.path.splitext(os.path.basename(image))[0]

    pst_json = os.path.join(out, "%s_pst.json" % tag)
    ps_csv = os.path.join(out, "plaqseg_%s.csv" % tag)

    # --- Stage 1: PST front (plaque env). cwd=ROOT so plaque_gui imports cleanly.
    run([a.plaque_py, os.path.join(HERE, "pst_front.py"), image, pst_json, a.plate_mm],
        cwd=ROOT)

    # read calibration to pass mm/px straight to PlaqSeg's --ppm
    pst = json.load(open(pst_json))
    mm_per_px = pst["mm_per_px"]
    if not mm_per_px:
        raise SystemExit("no calibration (dish not detected) for %s" % tag)

    # --- Stage 3: PlaqSeg primary (plaqseg env) on the ORIGINAL image.
    run([a.plaqseg_py, RUN_PLAQSEG, a.weights, image, out, tag,
         "--conf", a.conf, "--iou", a.iou, "--ppm", "%.10f" % mm_per_px],
        cwd=ROOT)

    # --- Stages 2,4-10: combine (plaqseg env).
    blob_flag = "1" if a.blob else "0"
    combine_env = os.environ.copy()
    if a.clf:
        combine_env["PRECISE_CLF"] = "1"
        if a.clf_thr is not None:
            combine_env["PRECISE_CLF_THR"] = str(a.clf_thr)
    run([a.plaqseg_py, os.path.join(HERE, "combine.py"), pst_json, ps_csv, out, tag,
         blob_flag],
        cwd=ROOT, env=combine_env)

    print("PRECISE_PLATE_DONE tag=%s out=%s" % (tag, out))


if __name__ == "__main__":
    main()
