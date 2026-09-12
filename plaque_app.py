"""Entry point for the unified Plaque Toolkit desktop app.

  python plaque_app.py                  -> launch the GUI
  python plaque_app.py --smoke          -> headless self-test (packaging acceptance gate)
  python plaque_app.py --uitest         -> headless construct-the-GUI self-test
  python plaque_app.py --precise-smoke  -> run the in-process Precise pipeline on the
                                           bundled sample image (self-contained gate)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)   # so `import plaque_size_tool` / `import app...` resolve when frozen


def _precise_smoke(extra=None):
    """Run Precise IN-PROCESS on the bundled sample image and print PRECISE_SMOKE OK/FAIL.

    This is the acceptance gate for the SELF-CONTAINED build: it proves torch +
    ultralytics + the YOLO weights + the classifier all load and run inside the frozen
    exe with no conda env. Exit 0 on success."""
    from app import engine_api
    try:
        from precise.pipeline import torch_inprocess_available
    except Exception as e:
        print("PRECISE_SMOKE FAIL  (cannot import precise.pipeline:", e, ")")
        return 1
    if not torch_inprocess_available():
        print("PRECISE_SMOKE FAIL  (torch/ultralytics not importable in this interpreter)")
        return 1
    img = extra or engine_api.resource_path("sample.tif")
    out_dir = os.path.join(os.path.dirname(os.path.abspath(img)), "out_precise_smoke")
    try:
        from precise.pipeline import run_inprocess
        s = run_inprocess(img, plate_mm=100, out_dir=out_dir, clf=True, blob=False)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("PRECISE_SMOKE FAIL  (run_inprocess raised:", e, ")")
        return 1
    # PT-6: this is a BUILD ACCEPTANCE GATE (build_macos.sh fails the build on a
    # non-zero exit, and it is the only Precise check in CI). The old condition was
    # `n >= 0` on a count -- always true -- followed by an unconditional `return 0`,
    # so a build that loaded torch but detected nothing shipped as green.
    # A working Precise engine MUST find plaques on the bundled sample.
    min_n = int(os.environ.get("PRECISE_SMOKE_MIN", "1"))
    n = int(s.get("n_final", 0))
    overlay = s.get("overlay")
    problems = []
    if n < min_n:
        problems.append("n_final=%d < required %d" % (n, min_n))
    if not overlay or not os.path.exists(overlay):
        problems.append("overlay not written (%r)" % overlay)
    ok = not problems
    print("PRECISE_SMOKE", "OK" if ok else "FAIL",
          "| n_final=%d | n_plaqseg=%s | overlay=%s" % (n, s.get("n_plaqseg"), overlay))
    if not ok:
        print("PRECISE_SMOKE FAIL reasons: " + "; ".join(problems))
        print("  The Precise engine loaded but produced nothing usable on the bundled "
              "sample. Do NOT ship this build.")
        return 1
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--smoke":
        from app.engine_api import smoke
        return smoke(argv[1] if len(argv) > 1 else None)
    if argv and argv[0] == "--precise-smoke":
        return _precise_smoke(argv[1] if len(argv) > 1 else None)
    if argv and argv[0] == "--uitest":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"   # construct the GUI with no display
        from app.ui import uitest
        return uitest()
    from app.ui import launch
    return launch()


if __name__ == "__main__":
    sys.exit(main())
