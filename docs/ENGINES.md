# Detection engines

The toolkit ships **four detection modes**. They share the same measurement math (area,
area-equivalent diameter `2·√(area/π)`, mm calibration from the detected dish); they differ in
*which* plaques they find and, critically, in **how much you can trust the result for a
publication**.

| Engine | Validation status | One-line summary |
|---|---|---|
| **Published** | ✅ Peer-reviewed & validated | The exact Trofimova & Jaschke 2021 algorithm — the only citable mode. |
| **Current** | In-house (default) | Same algorithm, bug-fixes + corrected calibration + numeric values. |
| **Sensitive** | In-house, **not** validated | Lowers the size gates to catch tiny plaques; more recall, more false positives. |
| **Precise** | In-house, **not** validated | PST + PlaqSeg YOLO union — the best detector on dense plates. |

> **The honest summary:** Only **Published** carries peer-reviewed validation. Current is a
> near-identical superset of it. Sensitive, Precise, and the optional classifier are useful but
> have **not** been independently validated — to publish counts/sizes from them you must
> validate them on your own plates ([PUBLICATION.md](PUBLICATION.md)).

---

## 1. Published (validated)

The exact, byte-for-byte algorithm from:

> Trofimova E, Jaschke PR. *Plaque Size Tool.* Virology 2021;561:1–5.
> [doi:10.1016/j.virol.2021.05.011](https://doi.org/10.1016/j.virol.2021.05.011)

- Adaptive-local thresholding → contour detection → keeps non-overlapping, roughly-circular
  contours → measures convex-hull area.
- Reproduces the published literature **within ~0.04 mm**.
- This is the **only** mode you may cite as a published, peer-reviewed method.

**Use it for:** every number that goes into a paper.

**How to get it:**
- App: pick **Published** in the engine dropdown.
- Launcher: **`Original Plaque Size Tool (1 plate).bat`** / **`(batch).bat`**, or choose
  `[O]riginal published` when a launcher prompts.
- CLI: `plaque_size_tool.py … --published` (this also forces `--watershed` off).

---

## 2. Current (corrected) — the default

The same published detection/sizing **algorithm**, with two classes of fix:

1. **Bug-fixes + numeric values** — measurements are kept numeric instead of being truncated
   to 2 decimal places.
2. **Corrected dish / calibration** — the dish is chosen as the **roundest large contour**, so
   the dark surround around the dish can no longer hijack the mm scale (a real failure mode of
   the original on top-lit photos). The corrected calibration is `mm_per_px = plate_mm /
   dish_diameter_px`.

On the 17 bundled test plates this leaves the plaque **count unchanged**; individual-plaque
`DIAMETER_MM` differs from Published by **≤ ~0.04 mm** (below imaging resolution — the
concentric-pair de-dup occasionally keeps a slightly different surviving contour).

**Use it for:** routine, day-to-day measurement. It is the **default** in the app and launchers.

**How to get it:** default everywhere; CLI is `plaque_size_tool.py …` with no `--published`.

---

## 3. Sensitive (tiny plaques)

Current with the **size gates lowered** to catch sub-0.4 mm plaques the standard gates reject.

- Detects **many more** plaques on plates with tiny/faint plaques…
- …but also **more false positives** (bubbles, glare, dust, lawn texture).
- **In-house; not independently validated.** Forced **off** under Published mode so it can never
  contaminate a validated run.

**Use it for:** exploratory counts and tiny-plaque phenotypes — **verify detections by eye**,
keep it out of citable runs, and report sensitive-vs-normal counts separately.

**How to get it:**
- App: tick **Sensitive** (or pick the Sensitive engine), or use the live toggle in the editor.
- Launcher: answer `[Y]es` to the "catch tiny plaques" prompt in **`Edit Plaques (GUI).bat`**.
- CLI: `plaque_gui.py … --sensitive` (the editor live-toggles it; `--published` overrides it off).

---

## 4. Precise (PST + PlaqSeg) — the best detector

The strongest detector in the toolkit. It fuses the validated PST geometry with a YOLO
segmentation model and a series of precision gates:

1. **PST front** — validated dish detection + mm/px calibration + PST normal & sensitive
   centers (`precise/pst_front.py`, which calls the same `plaque_gui.run_detection`).
2. **Artifact masks** from the dish geometry: a **lawn ROI** (inner 0.80·radius), a
   **blue-label** mask, and a hard **dish-boundary** reject — so detections on the rim, on the
   label, or outside the dish are dropped.
3. **PlaqSeg YOLO primary** — a tiled YOLO-seg model (`_plaqseg/models/small.pt`) detects
   plaques on the original image; detections outside the lawn ROI / on the label are removed.
4. **Density switch** — if PlaqSeg already found a dense field
   (`n_plaqseg ≥ DENSE_FACTOR · n_pst_sensitive`), the PlaqSeg set is taken as final (skip the
   recall passes — they only help on sparse plates).
5. **Gated PST-sensitive recall** (sparse/clean plates) — a PST-sensitive center is accepted
   only if it is inside the lawn ROI, **not** already matched to a PlaqSeg detection, **and**
   passes a center-vs-ring contrast floor on a float flat-fielded lawn.
6. **Optional blob recovery** (sparse only, off by default — over-detects on textured lawns).
7. **Union + dedup** of PlaqSeg + gated-PST + gated-blob, by match radius.
8. **Optional learned classifier gate** (`--clf`, default **OFF**) — see below.
9. **Sizing + output** — per-plaque CSV, a colored overlay (green = PlaqSeg, blue = recovered,
   cyan lawn ring, dish circle, physical scale bar) and a one-line JSON summary.

**Validation status:** **In-house, not independently validated.** PlaqSeg itself is **not
peer-reviewed**. Treat Precise as the best available detector, not a citable method.

**Use it for:** dense, countable plates where PST alone drops fused plaques and Sensitive
over-detects.

**How to run it:** Precise needs PyTorch + ultralytics + the YOLO weights. Two supported paths:
- **All-in-one installer** (`PlaqueToolkitFullSetup.exe`) — Precise is **built in**, no conda.
- **Two-env / run-from-source** — a `plaque` env (PST) plus a `plaqseg` env (torch/ultralytics);
  the app auto-detects the second env. Or run **`Precise Detect (best engine).bat`**.

See [INSTALL.md](INSTALL.md) for the environments and [DEVELOPER.md](DEVELOPER.md) for the
two-env vs unified-env design.

### The optional ML classifier (`--clf`)

A learned **plaque-vs-texture gate** that re-scores every Precise candidate and keeps only those
the model judges to be real plaques.

- **Architecture / data:** a ResNet-18 trained on detector-union labels plus an independent
  vision ground-truth set and OnePetri real-phage data (15,659 boxes total).
- **Performance:** leave-one-plate-out **F1 ≈ 0.95** on held-out plates.
- **Opt-in, default OFF** (`PRECISE_CLF=1` or `run_precise.py --clf`) — so the validated,
  hand-tuned-contrast path is unchanged unless you ask for the gate.
- **Validation status:** **locally validated by the authors, not independently/peer-reviewed.**
  Its outputs — inside the Precise engine — were validated on the authors' own plates (detection
  precision 1.00 and diameter *r* ≥ 0.99 vs hand-labelled ground truth; ICC 0.97 vs independent
  Fiji tracing — see [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md)). Its *training* labels are
  partly detector-derived, so treat the training set (not the validation) with that caveat.

The model and inference code live in `_research/clf/` (`plaque_clf.pt` + `infer.py`), which the
Precise pipeline loads when `--clf` is enabled.

---

## Why the cross-tool reality matters

These plates are typically **top-lit, gradient-lit iPhone photos**. On that input:

- **ImageJ** and the **published ViralPlaque macro** rely on *global* thresholding and **fail**
  — the illumination gradient defeats a single threshold.
- Only **adaptive-local** methods (PST) and the **trained PlaqSeg model** handle them.

So the practical limit is **imaging, not the algorithm**: back-lit / evenly illuminated plates
(a light box, fixed exposure, straight-down camera) are what unlock defensible numbers,
especially for turbidity. See the imaging protocol in [USER_GUIDE.md](USER_GUIDE.md#9-imaging-protocol-for-publishable-turbidity).

---

## Calibration QC (all engines)

Every overlay draws the **detected dish circle** and flags a **tilt warning** when the dish
axis-ratio exceeds **1.03** — a tilted (non-orthographic) phone shot makes the dish elliptical
and biases every mm value. Image plates straight-on. If no dish is detected, the tools fall back
to **pixel-only** output and warn.

---

## Mode interactions (important)

- `--published` **forces** `--watershed` and `--sensitive` **off**, so a citable run is never
  altered by the extensions.
- `--watershed` (opt-in, all non-Published modes) splits touching/merged plaques via a
  distance-transform watershed and tags recovered plaques `SOURCE=watershed`. It recovers
  real-sized plaques on dense plates and **nothing** on well-separated ones (no
  over-segmentation). Apply it **uniformly** across all compared groups or not at all.
- The Precise classifier gate (`--clf`) is **off by default**.
