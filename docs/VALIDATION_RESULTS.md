# Plaque Toolkit — Local validation results

> **Status: partial local validation (foundation for a resource paper).** These are real
> measurements on the authors' own plates, recorded for reproducibility and for the Methods /
> Supplementary of a future publication. This is **not** an independent or peer-reviewed
> validation, and the sample is small — see *Limitations* and *What's still needed*.

- **Date:** 2026-07-07
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

**(B) Cross-check vs Fiji/ImageJ.** The app exported a calibrated crop + an ImageJ ROI set
(`Export ▸ Fiji registration bundle`). In **headless Fiji** the crop was opened and each of the
app's ROIs measured (`List.setMeasurements` per ROI); Fiji's areas were converted to diameters and
compared to the app's for the identical outlines. This checks (i) that the exported crop carries
the correct millimetre calibration into Fiji, and (ii) that the two tools agree on size for the
same region.

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

### (B) vs real Fiji (IMG_4092, calibration plate)

| Check | Result |
|---|---|
| Crop pixel size read by Fiji | **0.03929 mm/px** (matches the app exactly) |
| App ROIs measured in Fiji | **95 / 95** |
| Diameter agreement (app vs Fiji, same outlines) | **r = 0.9999**, RMSE 0.0035 mm, bias −0.0006 mm |

**Interpretation.** The exported crop opens in Fiji at the correct millimetre scale and Fiji's
measurements of the app's outlines agree with the app to **r = 0.9999 (sub-0.004 mm)** — the
measurement pipeline and the Fiji bridge are internally consistent with an independent tool.

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

1. **More plates** across densities (sparse → confluent) and, ideally, a second labeller for
   inter-observer agreement.
2. **Negative controls** — score false-positive rate on blank/no-plaque plates
   (`260701 No Plaque Plates…`).
3. **Plate-level statistics** — report agreement per plate (Bland–Altman on median diameter, count
   correlation), not just pooled per-plaque.
4. **A frozen validation script + data DOI** (Zenodo) so the numbers are reproducible from the
   archived inputs.

## 6. Reproducing these numbers

- **(A)** Validate tab → load `Verifications/labels_*.json` → score each engine; or
  `python -c "from app import validate; print(validate.score_label_file('Verifications/labels_IMG_3907.json', mode='precise'))"`.
- **(B)** `Export ▸ Fiji registration bundle`, then in Fiji (headless) open the crop, load the
  RoiSet, measure each ROI, and compare with the app's `_registration.csv` (or the in-app
  **Compare vs Fiji…**). Matcher: `app/fiji_match.py`.

*Ground-truth and plate images are the authors' data (git-ignored); paths above are local.*
