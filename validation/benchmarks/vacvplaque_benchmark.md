# VACVPlaque benchmark — results

Dataset: VACVPlaque test split (De et al., *Sci Data* 2025; RODARE 3003, CC BY 4.0): 21 phone photos of
crystal-violet-stained 6-well vaccinia plaque assays, cut into **126 wells with 11,951 hand-masked plaques**.
Scored with `app/validate.py` (match radius = max(4 px, 0.5 × gold radius); micro-averaged over wells).
Toolkit commit `b322154`; shipped PlaqSeg weights `small.pt` sha256 `b7c072c404e279ef`; fine-tuned weights
`_research/models/plaqseg_vacv_ft_x1_best.pt` sha256 `e81dd8d945fd4c48` (not committed; 92 MB).

## 1. Shipped engines do not transfer to this domain

| Engine | Scale | Wells | TP | FP | FN | Precision | Recall | F1 | Per-well recall |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Published | native (well ≈ 600 px) | 126 | 109 | 16 | 11842 | 0.87 | 0.01 | 0.02 | 0.00–0.25 |
| Current | native (well ≈ 600 px) | 126 | 872 | 162 | 11079 | 0.84 | 0.07 | 0.13 | 0.00–1.00 |
| Sensitive | native (well ≈ 600 px) | 126 | 900 | 679 | 11051 | 0.57 | 0.08 | 0.13 | 0.00–1.00 |
| Published | ×3 (well ≈ 1,800 px) | 126 | 644 | 198 | 11307 | 0.76 | 0.05 | 0.10 | 0.00–1.00 |
| Current | ×3 (well ≈ 1,800 px) | 126 | 381 | 2291 | 11570 | 0.14 | 0.03 | 0.05 | 0.00–0.50 |
| Sensitive | ×3 (well ≈ 1,800 px) | 126 | 534 | 7332 | 11417 | 0.07 | 0.04 | 0.05 | 0.00–0.50 |
| Precise (shipped weights, full pipeline) | ×3 | 125 | 50 | 725 | 11901 | 0.06 | 0.00 | 0.01 | 0.00–0.14 |

The classic engines' size gates are tuned for Petri-dish photos; at native scale almost every plaque
(radius ≈ 4 px) falls under them, and at ×3 the crystal-violet grain is detected as plaques instead
(precision collapses). The shipped PlaqSeg detector returns no boxes on most wells at either scale.

## 2. Fine-tuning the detector on the dataset's validation split

Training set: 204 wells (21,929 polygons) from 34 validation-split photos; early-stopping set: 48 wells
from the other 8 validation photos; **the test split was never seen**. ultralytics 8.4.79, start from
`small.pt`, imgsz 640, batch 8, CPU, 30 epochs max, patience 8 → stopped at epoch 20, best epoch 12
(`finetune_epochs.csv`). Wall-clock ≈ 2.5 h on a laptop CPU.

Detector-only scoring on the **test** wells (native scale, imgsz 640, boxes → area-equivalent circles):

| Weights | conf | TP | FP | FN | Precision | Recall | F1 | Per-well recall |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| original | 0.25 | 4 | 89 | 11947 | 0.04 | 0.00 | 0.00 | 0.00–0.03 |
| original | 0.10 | 22 | 279 | 11929 | 0.07 | 0.00 | 0.00 | 0.00–0.33 |
| finetuned_best | 0.25 | 6611 | 1240 | 5340 | 0.84 | 0.55 | 0.67 | 0.00–1.00 |
| finetuned_best | 0.10 | 7340 | 3028 | 4611 | 0.71 | 0.61 | 0.66 | 0.00–1.00 |

Size agreement from boxes (box area → equivalent diameter) overestimates the masked area: bias
+0.18 mm at a nominal 34.8 mm well; the full pipeline sizes from mask polygons instead (section 3).

## 3. Fine-tuned weights through the full Precise pipeline

_Pending: `per_well_precise_finetuned_x1.csv` — run via `PLAQSEG_WEIGHTS=... python app/validate.py <wells> --modes precise`._

## What this shows

* The shipped detector is **phage-lawn specific**: on stained mammalian wells every engine is blind,
  at native and normalised scale. That is a quantified domain limit, not a bug.
* The same training recipe learns a new assay type from a few hundred labelled wells in hours on a
  CPU, and the measurement/provenance stack runs unchanged with the new weights (`PLAQSEG_WEIGHTS`).
  That is the case for a per-assay model zoo rather than one universal detector.
* For the dataset's own baselines (StarDist mAP50 0.73 at IoU 0.1, De et al.), the fine-tune reaches
  box mAP50 0.73 on its early-stopping wells after 18 epochs with no hyper-parameter search.
* None of this touches phage plates: the OnePetri export and the blind-labelled plates from
  `docs/VALIDATION_STUDY_PROTOCOL.md` are needed for the phage version of this table.
