# Plaque Toolkit — Local validation results

> **Status: partial local validation (foundation for a resource paper).** These are real
> measurements on the authors' own plates, recorded for reproducibility and for the Methods /
> Supplementary of a future publication. This is **not** an independent or peer-reviewed
> validation, and the sample is small — see *Limitations* and *What's still needed*.

- **Date:** 2026-07-07 · updated 2026-07-08 with the **n = 100 independent Fiji method comparison** (§2B)
- **Operator:** in-house (JRR Micro Lab)
- **App:** Plaque Toolkit (repo tag `v1.0.2`), engines Published / Current / Sensitive / Precise
  (PST + PlaqSeg YOLO + ResNet gate). Only **Published** is the peer-reviewed algorithm
  (Trofimova & Jaschke 2021); Precise/Sensitive/Current are in-house.
- **Reference software:** Fiji / ImageJ **2.16.0 / 1.54p** (headless).

---

## 1. What was validated, and how

Two independent checks:

**(A) Detection + sizing vs hand-labelled ground truth.** Ground-truth plaque sets were made in
the app (auto-detect → hand-corrected) and exported as `labels_<img>.json` (schema
`plaque-groundtruth-v1`). Each engine's detections are matched to the ground truth **by position**
(a detection matches a GT plaque if their centres are within `0.5 ×` the GT radius), then scored:

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

| Plate | Plaques (GT) | Engine | Detected | Precision | Recall | Diameter agreement (matched) |
|---|---:|---|---:|---:|---:|---|
| IMG_3907 | 185 | **Precise** | 74 | **1.00** | 0.40 | r = 0.99, MAE 0.0025 mm, bias +0.0025 mm |
| IMG_3907 | 185 | Sensitive | 177 | 0.55 | 0.52 | r = 0.62 (noisier) |
| IMG_3912 | 89 | **Precise** | 25 | **1.00** | 0.28 | r = 1.00, MAE 0.000 mm |
| IMG_3912 | 89 | Sensitive | 117 | 0.33 | 0.44 | r = 0.79 |

*Current and Published detected very few plaques on these dense, small-plaque plates (≤10) and did
not align with the ground truth under position matching — a combination of stricter size/circularity
gates and calibration differences; reported here for completeness, not as a like-for-like number.*

**Interpretation.** On these plates **Precise has perfect precision (no false positives)** and its
**diameters match the hand labels to r ≈ 0.99 (MAE ≤ 0.0025 mm)** — what it reports is trustworthy.
It is **conservative on very dense plates** (recall ≈ 0.3–0.4 at 89–185 plaques/plate): it
under-counts rather than guessing. **Sensitive** lifts recall (≈ 0.44–0.52) at the cost of precision
and noisier sizes — appropriate for dense plates when followed by manual pruning.

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
| Proportional bias (slope) | 1.006 → none | — |

Figure: `PlaqueToolkit_vs_Fiji_BlandAltman.png` (method-comparison scatter + Bland–Altman).

**Interpretation.** Strong agreement — **ICC = 0.97**, tight limits (±≈0.1 mm on ~1.5 mm plaques ≈
6–9%). The tool reads **~1.8% smaller** than the manual traces on average: a small, *constant* offset
(regression slope ≈ 1.0, so no size dependence). **This is the citable Toolkit‑vs‑Fiji result.**

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
| Toolkit vs hand labels — pooled IMG_3907+3912 | 99 | 0.50 mm | +0.0018 mm | −0.034 … +0.038 mm | 0.991 | 0.991 |
| Toolkit vs Fiji, *same* outlines *(consistency)* | 95 | 1.42 mm | +0.0006 mm | −0.006 … +0.007 mm | 1.000 | 1.000 |

**Interpretation.** The **independent n = 100 comparison** (ICC 0.97, LoA ≈ ±0.1 mm) is the headline for
the paper. The two supporting checks isolate *where* the small offset comes from: measuring the tool's
*own* outlines in Fiji is essentially exact (ICC 1.00 — the calibration + area math are right), and the
tool's boundaries match careful hand labels closely (ICC 0.99). So the **~1.8% Toolkit−Fiji difference**
in the primary comparison reflects the honest gap between an *auto-detected* boundary and a *human's
manual trace*, not a calibration error — and it is small and size-independent (slope ≈ 1.0).

**Count-level (pseudoreplication note).** Plaque counts should be analysed with the **plate** as the
experimental unit, but only **2** ground-truth plates were available — too few for a plate-level count
correlation. The two plates show systematic under-counting on dense plates (Precise 74 vs 185; 25 vs
89), consistent with the recall in §2A. A defensible count-level validation needs **≥ 5–6 plates
spanning densities** (still to do).

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

- **Small sample.** Detection/sizing was scored on **2** ground-truth plates (185 + 89 plaques);
  the Fiji cross-check on **1** plate. Not yet enough for a strong published claim.
- **Precise under-detects on very dense plates** (recall ≈ 0.3–0.4). What it *does* report is highly
  accurate; use Sensitive + manual tools (Add / Draw shape / Detect area) for coverage on crowded
  plates.
- **Only Published is peer-reviewed.** Precise/Sensitive/Current are in-house and must not be
  described as "validated methods" in the literature sense.
- **The ground truth is the authors' own hand labelling** (single operator), not an external gold
  standard; inter-observer agreement was not assessed.
- **Turbidity** from top-lit phone photos is relative / screening-grade, not calibrated OD.

## 5. What's still needed for publication

(see `docs/PUBLISHING_CHECKLIST.md`)

1. **Size validation vs Fiji** — **done (§2B, n = 100 independent plaques; ICC 0.97).** Strong
   enough to cite. Optional strengthening: a **second labeller** on a subset for inter-observer
   agreement, and reporting how many plates the 100 plaques came from.
2. ~~**Negative controls** — false-positive rate on blank plates.~~ **Done (§2C):** Precise
   3.1 ± 3.0 FP/plate, Sensitive 12.4 ± 4.4. Still to do: density-match the blanks to the test
   plates, and repeat per imaging batch (the FP floor is setup-specific).
3. **Statistics** — size-agreement Bland–Altman + ICC is **done (§2D)**. Still to do:
   **count** validation at the **plate** level (count correlation + Bland–Altman on per-plate median
   Ø) once ≥ 5–6 ground-truth plates exist, and mixed-effects handling if plates are nested in
   biological replicates.
4. **A frozen validation script + data DOI** (Zenodo) so the numbers are reproducible from the
   archived inputs.

## 6. Reproducing these numbers

- **(A)** Validate tab → load `Verifications/labels_*.json` → score each engine; or
  `python -c "from app import validate; print(validate.score_label_file('Verifications/labels_IMG_3907.json', mode='precise'))"`.
- **(B)** `Export ▸ Fiji registration bundle`, then in Fiji (headless) open the crop, load the
  RoiSet, measure each ROI, and compare with the app's `_registration.csv` (or the in-app
  **Compare vs Fiji…**). Matcher: `app/fiji_match.py`.

*Ground-truth and plate images are the authors' data (git-ignored); paths above are local.*
