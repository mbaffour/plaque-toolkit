# Plaque Toolkit — Local validation results

> **Status: partial local validation (foundation for a resource paper).** These are real
> measurements on the authors' own plates, recorded for reproducibility and for the Methods /
> Supplementary of a future publication. This is **not** an independent or peer-reviewed
> validation, and the sample is small — see *Limitations* and *What's still needed*.

- **Date:** 2026-07-07 · updated 2026-07-08 with the **n = 100 independent Fiji method comparison** (§2B)
- **Operator:** in-house (JRR Micro Lab)
- **App:** Plaque Toolkit, measured with the v1.0.2 code (that tag is no longer on main; size outputs
  were verified byte-identical at 1.1.0, see CHANGELOG), engines Published / Current / Sensitive / Precise
  (PST + PlaqSeg YOLO + ResNet gate). Only **Published** is the peer-reviewed algorithm
  (Trofimova & Jaschke 2021); Precise/Sensitive/Current are in-house.
- **Reference software:** Fiji / ImageJ **2.16.0 / 1.54p** (headless).

---

## 0. What was validated — at a glance

A single-operator but **multi-pronged** local validation on the authors' own plates and labels:

| # | What was validated | Data | Headline result |
|---|---|---|---|
| 1 | **Hand-corrected ground truth** | plates labelled in-app (WT / 2-4 / G12E / DTR + the `IMG_39xx` sets) | the human reference the rest is scored against |
| 2 | **Detection** vs the hand labels | **9 GT plates, 745 plaques** (`validation/ground_truth/validate_*.csv`) | pooled Precise **precision 0.95 / recall 0.53 / F1 0.68** (21 FP); per-plate precision 0.00–1.00; the two densest plates (IMG_3907, IMG_3912) precision 1.00 at recall 0.40 / 0.28 (§2A). Matched-diameter r ≥ 0.99 is a *self-consistency* figure, not human agreement |
| 3 | **Size** vs **independent Fiji** tracing | **100 plaques** traced blind in Fiji | **ICC 0.97**, r 0.98, bias −1.8%, LoA −0.15…+0.09 mm, no proportional bias (§2B) |
| 4 | **False positives** on negative controls | **17 blank** plates | Precise **3.1 ± 3.0 FP/blank** (Sensitive 12.4) (§2C) — a second run with different settings gives 3.35 / 40.4 (TESTING_AND_VALIDATION.md); not yet reconciled, see §2C |
| 5 | **Agreement statistics** (Bland–Altman + ICC) | 3 comparisons | independent Fiji ICC 0.97; hand labels ICC 0.99; same-outline consistency ICC 1.00 / r 0.9999 (§2D) |
| 6 | **The ML classifier gate, on vs off** | WT/2-4/G12E/DTR (4 plates), threshold sweep | precision **+0.03** (0.67 → 0.70), recall −0.01, F1 unchanged at the operating point — a working precision filter (§2E) |
| 7 | **Resolution floor** — tiny plaques | **20** plaques ~0.3–0.5 mm, tool vs Fiji | means agree (bias ~4%) but per-plaque **ICC ≈ 0** — a shared imaging limit below ~0.5 mm, not a tool defect (§2F) |

**Boundary (stated plainly):** this is a **real local validation performed by the authors** — not an
independent or peer-reviewed one. Only the **Published** engine carries peer-reviewed validation; the
Precise engine and its classifier gate are validated **here, on these plates**, and should be
described that way in a paper.

---

## 1. What was validated, and how

Two independent checks:

**(A) Detection + sizing vs hand-labelled ground truth.** Ground-truth plaque sets were made in
the app (auto-detect → hand-corrected) and exported as `labels_<img>.json` (schema
`plaque-groundtruth-v1`). Each engine's detections are matched to the ground truth **by position**
(a detection matches a GT plaque if their centres are within `max(4 px, 0.5 ×` the GT radius`)`), then scored:

- **Precision / recall / F1** on detection (a detected plaque is a true positive only if it lands
  on a GT plaque);
- **Per-plaque diameter agreement** for the matched pairs — mean absolute error (MAE), bias
  (detected − GT), and Pearson *r* — using the area-equivalent diameter `d = 2·√(A/π)`.

Scorer: `app/validate.py` (also reachable from the app's **Validate** tab). Match fraction 0.5.

**(B) Independent method comparison vs Fiji/ImageJ.** A sample of **100 plaques** was traced
**independently** in Fiji (the operator's own outlines, blind to the tool's boundaries; scale set from
a ruler / dish reference in the same plane), and Fiji's area for each was compared to Plaque Toolkit's
for the *same plaque*, paired by plaque. Agreement was assessed by Bland–Altman (bias + 95% limits of
agreement), ICC(A,1) absolute agreement, and Pearson *r*, on area and on the area-equivalent diameter.
A separate *consistency* check re-measured the tool's **own** exported outlines in headless Fiji
(`List.setMeasurements` per ROI) to confirm the calibration and area math carry into Fiji exactly.

---

## 2. Results

### (A) vs hand-labelled ground truth

Detection was scored on **9 hand-labelled plates** (IMG_3900 … IMG_3917; **745 plaques**). The
score tables are archived as `validation/ground_truth/validate_permode.csv` (pooled) and
`validate_perplate.csv` (per plate); the label files for the two densest plates (IMG_3907, IMG_3912)
are archived alongside them.

**Pooled (all 9 plates):**

| Engine | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| **Precise** | 397 | **21** | 348 | **0.95** | 0.53 | **0.68** |
| Current | 125 | 99 | 620 | 0.56 | 0.17 | 0.26 |
| Sensitive | 273 | 881 | 472 | 0.24 | 0.37 | 0.29 |

**Per plate (Precise):** precision ranged **0.00 – 1.00** and recall **0.00 – 0.90** (0.10 – 0.90
excluding IMG_3913, where no engine found any of its 32 plaques). The two densest plates:

| Plate | Plaques (GT) | Engine | Detected | Precision | Recall |
|---|---:|---|---:|---:|---:|
| IMG_3907 | 185 | **Precise** | 74 | **1.00** | 0.40 |
| IMG_3907 | 185 | Sensitive | 177 | 0.55 | 0.52 |
| IMG_3912 | 89 | **Precise** | 25 | **1.00** | 0.28 |
| IMG_3912 | 89 | Sensitive | 117 | 0.33 | 0.44 |

*Current and Published detected very few plaques on these dense, small-plaque plates (≤10) and did
not align with the ground truth under position matching — a combination of stricter size/circularity
gates and calibration differences; reported here for completeness, not as a like-for-like number.*

**Matched-diameter agreement is a self-consistency check, not human agreement.** The scorer also
reports diameter agreement on matched pairs (r ≥ 0.99, MAE ≤ 0.0025 mm; `size_mae_mm` ≈ 1e-17 on 7
of 9 plates). In the label files, plaques with `source = auto` or `region` are the **engine's own
contours** kept by the labeller, so a matched ground-truth contour is usually the engine's contour
and the comparison is engine-vs-itself. Sizing agreement with a **human** is given by the Fiji
comparison in §2B (n = 100), not by this number.

**Interpretation.** Across the 9 plates **Precise is highly precise (0.95; 21 false positives in
total)** — when it reports a plaque it is almost always real — but **conservative** (recall 0.53
pooled; ≈ 0.3–0.4 on the densest plates at 89–185 plaques/plate): it under-counts rather than
guessing, and on one plate (IMG_3913) it found nothing. **Sensitive** lifts recall on the dense
plates (≈ 0.44–0.52) at the cost of precision and noisier sizes — appropriate for dense plates when
followed by manual pruning.

### (B) vs independent manual Fiji measurement — method comparison (n = 100)

The primary size validation. **100 plaques were traced independently in Fiji/ImageJ** (the operator's
own outlines, not the tool's) and compared to Plaque Toolkit's measurement of the same plaques.
Diameters are area-equivalent (`d = 2·√(A/π)`).

| Metric | Diameter (mm) | Area (mm²) |
|---|---|---|
| n plaques | 100 | 100 |
| Mean (Toolkit / Fiji) | 1.55 / 1.57 | 1.94 / 2.01 |
| **Mean bias (Toolkit − Fiji)** | **−0.028** (≈ −1.8%) | −0.069 |
| **95% limits of agreement** | **−0.146 … +0.089** | −0.34 … +0.20 |
| **ICC(A,1)** | **0.974** | 0.973 |
| Pearson r | 0.979 | 0.978 |
| Proportional bias | none (see below) | — |

*Proportional-bias tests (diameter):* Bland–Altman regression of the difference on the mean gives
slope **+0.006, p = 0.78** (Spearman ρ = 0.03, p = 0.79) — the disagreement does **not** grow with
plaque size. Equivalently the least-squares slope of Toolkit on Fiji is **0.98**, not significantly
different from 1 (p = 0.46). *(The "1.006" in earlier drafts came from a different regression —
Fiji-**area** on Toolkit-area; the app and figure use the diameter slope 0.98.)* The mean bias, though
small, is statistically **real** (paired *t* = −4.76, **p = 6.6 × 10⁻⁶**): a consistent −1.8% offset,
not sampling noise.

Figure: `PlaqueToolkit_vs_Fiji_BlandAltman.png` (method-comparison scatter + Bland–Altman; red points
= the 8 plaques outside the 95% limits).

**Interpretation.** Strong agreement — **ICC = 0.97**, tight limits (±≈0.1 mm on ~1.5 mm plaques ≈
6–9%). The tool reads **~1.8% smaller** than the manual traces on average: a small, *constant* offset
(no size dependence, p = 0.78). **This is the citable Toolkit‑vs‑Fiji result.**

*Consistency sub-check:* measuring the tool's **own** exported outlines in Fiji (identical regions,
IMG_4092) gave r = 0.9999, bias −0.0006 mm — confirming the calibration and area math are exact. That
is an internal check; the **n = 100 independent comparison above** is the one to report.

### (C) Negative-control false-positive rate (blank plates)

Detection was run on **17 uninfected / no-plaque plates** (`260701 No Plaque Plates for
Calibration/`, iPhone HEIC). These have **no plaques**, so *every* detection is a false positive —
i.e. the empirical false-positive floor of the pipeline on this imaging setup.

| Engine | False positives / plate (mean ± SD) | Median | Range | Clean plates | 95% upper bound* |
|---|---|---:|---:|---:|---:|
| **Precise** | **3.1 ± 3.0** | 2 | 0–10 | 3 / 17 | ≈ 8.9 |
| **Sensitive** | **12.4 ± 4.4** | 11 | 7–24 | 0 / 17 | ≈ 21.0 |

<sub>*mean + 1.96·SD, a per-plate false-positive threshold.</sub>

> **Note.** Two blank-plate runs with different settings exist: this one, and the one quoted in
> [TESTING_AND_VALIDATION.md](TESTING_AND_VALIDATION.md) §2 (Published 0.88, Precise 3.35, Current
> 4.24, Sensitive 40.4 FP/blank over the same 17 plates). The per-plate data for neither is in the
> repository (`validation/` holds no blank-plate results), so the maintainer must archive one run
> under `validation/` and reconcile the two [owner to confirm: which run is canonical].

**Interpretation.** Precise has a **low but non-zero** false-positive floor (~3 per blank plate) —
round mid-grey lawn artifacts (bubbles, condensation droplets, specular glare, dust) that pass the
detector. **Sensitive is ~4× noisier** (~12 FP/plate, never zero) and should not be used for counting
without manual pruning. Consequences for reporting:

- **Counts:** subtract the density-matched negative-control floor (report mean ± SD), or threshold
  each plate off the 95% upper bound. Do not report raw counts from Sensitive without correction.
- **Sizes:** false positives are typically small artifacts; a size / circularity gate (or the
  `OVERLAP` / `CIRCULARITY` columns and manual erase) removes most. Size agreement (§2A) is measured
  only on matched true positives and is unaffected.

### (D) Size-agreement statistics — Bland–Altman + ICC

Proper agreement statistics on the matched diameter pairs (bias + 95% limits of agreement + ICC(A,1)
absolute agreement, not just correlation):

| Comparison | n | Mean Ø | Bias (Toolkit − ref) | 95% limits of agreement | ICC | r |
|---|---:|---:|---:|---|---:|---:|
| **Toolkit vs independent Fiji traces** *(primary — §2B)* | 100 | 1.55 mm | **−0.028 mm** (−1.8%) | **−0.146 … +0.089 mm** | **0.974** | 0.979 |
| Toolkit vs hand labels — pooled IMG_3907+3912 *(self-consistency; many labels are engine contours, §2A)* | 99 | 0.50 mm | +0.0018 mm | −0.034 … +0.038 mm | 0.991 | 0.991 |
| Toolkit vs Fiji, *same* outlines *(consistency)* | 95 | 1.42 mm | +0.0006 mm | −0.006 … +0.007 mm | 1.000 | 1.000 |

**Interpretation.** The **independent n = 100 comparison** (ICC 0.97, LoA ≈ ±0.1 mm) is the headline for
the paper. The two supporting checks isolate *where* the small offset comes from: measuring the tool's
*own* outlines in Fiji is essentially exact (ICC 1.00 — the calibration + area math are right), and the
tool's boundaries match the hand-label set closely (ICC 0.99 — largely because many of those labels
are the tool's own contours, so this row is a self-consistency check). So the **~1.8% Toolkit−Fiji difference**
in the primary comparison reflects the honest gap between an *auto-detected* boundary and a *human's
manual trace*, not a calibration error — and it is small and size-independent (slope ≈ 1.0).

**Count-level (pseudoreplication note).** Plaque counts should be analysed with the **plate** as the
experimental unit. The 9 ground-truth plates show systematic under-counting on dense plates (Precise
74 vs 185 on IMG_3907; 25 vs 89 on IMG_3912), consistent with the recall in §2A. A plate-level count
correlation / Bland–Altman on per-plate counts across those 9 plates has **not yet been computed**
(still to do).

### (E) The ML classifier gate — on vs off (`_research/clf/val/`, `val_gate.py`)

The Precise engine was scored **with and without** its ResNet-18 `--clf` gate on the four GT plates
(WT, 2-4, G12E, DTR), position-matched to the hand labels, across keep-thresholds 0.5–0.95:

| Gate | Mean precision | Mean recall | Mean F1 |
|---|---:|---:|---:|
| **off** | 0.672 | 0.328 | 0.382 |
| **on** (best thr 0.7) | **0.699** | 0.319 | 0.376 |

The gate **raises precision** — it removes a handful of PlaqSeg/PST false positives per plate (the
per-plate `n_clf_dropped` records which detector each drop came from) — at a **small recall cost**,
leaving F1 essentially unchanged on these plates (precision +0.03, recall −0.01, F1 unchanged on
4 plates). That is the intended behaviour of a **precision filter**, not a recall booster, and it is
why it ships **on** wherever Precise runs in-process (the Full installer, the unified `plaqueapp`
env, the web app — `pipeline.run_inprocess(clf=True)`) but **off by default on the CLI**
(`precise/run_precise.py --clf` / `PRECISE_CLF=1`) and in the two-env run-from-source app path,
which launches that CLI; `summary_<tag>.json` records `clf_gate` either way. (Recall here is
dominated by Precise's deliberate under-counting on very dense plates, §2A — not by the gate.)

### (F) Resolution floor — tiny plaques (n = 20)

An independent Fiji comparison on **20 very small plaques (~0.3–0.5 mm)** — below the primary
comparison's range (§2B starts at 0.84 mm) — to probe the small-size limit
(`validation/tiny_plaques.csv`; figure `validation/figures/agreement_tiny_diameter.*`).

| Metric | Tiny diameter | Tiny area |
|---|---|---|
| n | 20 | 20 |
| Mean (Toolkit / Fiji) | 0.43 / 0.42 mm | 0.149 / 0.138 mm² |
| **Mean bias (Toolkit − Fiji)** | **+0.015 mm (+3.6%)** | +0.011 mm² (+7.6%) |
| 95% limits of agreement | −0.10 … +0.13 mm | −0.07 … +0.09 mm² |
| **ICC(A,1)** | **≈ 0** (−0.01) | ≈ 0 (0.00) |
| Pearson r | ≈ 0 | ≈ 0 |

**The means agree (~4%), but individual tiny plaques do not correlate (ICC ≈ 0).** At ~0.4 mm a plaque
is only ~10 px across, so a **single-pixel** boundary difference between the tool's auto-outline and a
manual Fiji trace changes the area by **20–40%**. The measurement noise then exceeds the true
plaque-to-plaque size differences, so **neither method can rank tiny plaques** — this is a
**resolution floor of the imaging** and it limits *manual Fiji tracing as much as the tool*, not a
defect of either.

**Reporting rule:** treat sub-~0.5 mm plaque sizes as **group means** (reliable), not per-plaque
(unreliable in both methods). The primary size validation (§2B, n = 100, ≥ 0.84 mm, ICC 0.974) is
unaffected and remains the citable result. To size tiny plaques reliably per-plaque, image at higher
resolution (more pixels per plaque).

---

## 3. Quality-control finding fixed during validation

Validation against **real** Fiji revealed a calibration-inversion bug in the *Fiji registration
bundle* export (`mm_per_px = 1/ppm`, but `ppm` was already mm-per-pixel): the exported crop opened
in Fiji at 26.06 mm/px instead of 0.0393 (~680× off), and `Compare vs Fiji` coordinates were
inverted. A synthetic self-test had missed it because both sides shared the wrong value; only the
real-Fiji cross-check exposed it. **Fixed** (commit `6838bcf`) and re-confirmed by the r = 0.9999
result above. (The older *Cropped plate for Fiji* export was unaffected.) This is reported as
evidence that the cross-tool validation is doing real work.

---

## 4. Limitations

- **Small sample.** Detection was scored on **9** ground-truth plates (745 plaques) from one
  imaging set-up; the independent Fiji size comparison is n = 100 plaques from [owner to confirm: N]
  plates. Not yet enough for a strong published claim.
- **Resolution floor below ~0.5 mm.** On very small plaques (~0.3–0.5 mm, ~10 px across) the tool and
  manual Fiji agree on the *mean* size (~4% bias) but not plaque-by-plaque (ICC ≈ 0, n = 20; §2F) — a
  single-pixel boundary difference is 20–40% of the area, so measurement noise exceeds the true size
  differences in *both* methods. Report sub-0.5 mm sizes as group means, not per-plaque.
- **Precise under-detects on very dense plates** (recall ≈ 0.3–0.4; 0.53 pooled over 9 plates, and
  0 on IMG_3913). What it *does* report is almost always a real plaque (precision 0.95); use
  Sensitive + manual tools (Add / Draw shape / Detect area) for coverage on crowded plates.
- **Only Published is peer-reviewed.** Precise/Sensitive/Current are in-house and must not be
  described as "validated methods" in the literature sense.
- **The ground truth is the authors' own hand labelling** (single operator), not an external gold
  standard; inter-observer agreement was not assessed.
- **Turbidity** from top-lit phone photos is relative / screening-grade, not calibrated OD.

## 5. What's still needed for publication

(see `docs/PUBLISHING_CHECKLIST.md`)

1. **Size validation vs Fiji** — **done (§2B, n = 100 independent plaques; ICC 0.97).** Strong
   enough to cite, reported as "n = 100 plaques from [owner to confirm: N] plates". Optional
   strengthening: a **second labeller** on a subset for inter-observer agreement.
2. **Negative controls** — false-positive rate on blank plates. **Measured (§2C):** Precise
   3.1 ± 3.0 FP/plate, Sensitive 12.4 ± 4.4 — but a second run with different settings exists
   (TESTING_AND_VALIDATION.md §2) and neither run's per-plate data is in the repository; archive
   one under `validation/` and reconcile [owner to confirm]. Still to do: density-match the blanks
   to the test plates, and repeat per imaging batch (the FP floor is setup-specific).
3. **Statistics** — size-agreement Bland–Altman + ICC is **done (§2D)**. Still to do:
   **count** validation at the **plate** level (count correlation + Bland–Altman on per-plate median
   Ø) across the 9 ground-truth plates, and mixed-effects handling if plates are nested in
   biological replicates.
4. **A frozen validation script + data DOI** (Zenodo) so the numbers are reproducible from the
   archived inputs.

## 6. Reproducing these numbers

- **Archived data + figures:** [`validation/`](../validation/) — the n = 100 paired dataset
  (`paired_toolkit_vs_fiji.csv`, area + area-equivalent diameter), the hand-label ground truth, the
  per-engine score tables, and the agreement figures **regenerated from that data** by the repo's own
  tool. See [`validation/README.md`](../validation/README.md).
- **(A)** Validate tab → load `Verifications/labels_*.json` → score each engine; or
  `python app/validate.py Verifications --modes precise,current,sensitive,published` (the archived
  score tables are `validation/ground_truth/validate_permode.csv` / `validate_perplate.csv`; the
  images themselves are not in the repository, so the scorer cannot be re-run from the archive
  alone).
- **(B)** `Export ▸ Fiji registration bundle`, then in Fiji (headless) open the crop, load the
  RoiSet, measure each ROI, and compare with the app's `_registration.csv` (or the in-app
  **Compare vs Fiji…**). Matcher: `app/fiji_match.py`.

*The paired n = 100 dataset, the hand-label ground truth and the regenerated figures are archived in
[`validation/`](../validation/). Plate **photos** remain the authors' data and are git-ignored; the
`Verifications/` paths above are local.*
