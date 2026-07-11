# Model card — plaque-vs-texture classifier

A concise, paper-ready model card (after Mitchell *et al.* 2019) for the only model **we trained**.
Full training narrative and the numbers' sources are in
[TRAINING_AND_MODELS.md](TRAINING_AND_MODELS.md); provenance/licence context is in
[CREDITS_AND_LINEAGE.md](CREDITS_AND_LINEAGE.md).

> This card is for the **ResNet-18 classifier** only. The **PlaqSeg** YOLO detector is an
> **external** pre-trained model (not trained here); the **PST** detector/sizer is a classical
> algorithm (Trofimova & Jaschke 2021). Neither has a model card here.

---

## Model details
- **Name / role:** plaque-vs-texture patch classifier — an optional **precision gate** that, per
  candidate detection, decides *real plaque* vs *lawn texture / artifact*. It is **not** a detector.
- **Architecture:** `torchvision` **ResNet-18**, ImageNet-1k pretrained, final FC → 2-class head,
  whole network fine-tuned. (`_research/clf/train_clf.py`)
- **Input:** a **48×48 BGR** patch, scale-normalized so the candidate fills ~55 % of the frame
  (`CLF_PATCH = 48`, `CLF_FILL = 0.55`); converted to RGB, `/255`, ImageNet mean/std normalized.
- **Output:** P(plaque) ∈ [0, 1]; kept if ≥ `CLF_THR` (**default 0.5**).
- **Deployed checkpoint:** `_research/clf/plaque_clf.pt` — **byte-identical (md5 `72413d31…`) to
  `_research/clf/loop/plaque_clf_onepetri.pt`**, the OnePetri-augmented, leave-one-plate-out
  fine-tuned model. Inference: `_research/clf/infer.py`.
- **Version / date:** v1 (fine-tuned), 2026. Toolkit tag `v1.0.2`.
- **Licence:** inherits **CC BY-NC-SA 4.0 (non-commercial)** from OnePetri-derived training patches.

## Intended use
- **Intended:** reduce false positives inside the **Precise** engine on bacteriophage plaque
  plates, as a reviewable filter behind PST/PlaqSeg detection. Opt-in (`--clf`, off by default in
  the CLI; on by default in the desktop app).
- **Users:** researchers measuring phage plaques, who visually review results.
- **Out of scope:** a standalone detector; a substitute for human review; use as a citable
  "validated method"; non-plaque imaging; commercial use (licence).

## Training data
Positives = 48×48 patches on **in-house vision ground-truth centres** (`WT` 378, `2-4` 193,
`G12E` 305) + detector-union centres from our own plates, optionally + external positives.
Negatives = lawn texture / rim / label / specks + **hard negatives mined from blank control
plates**. Split **by plate** (every augmentation of a plate stays on one side → no leakage).
External sets (auxiliary): **VACVPlaque** (CC-BY-4.0, 11,943 patches) and **OnePetri** (CC-BY-NC-SA,
6000 patches). Details + licences: [TRAINING_AND_MODELS.md §2/§5](TRAINING_AND_MODELS.md).

## Training procedure
AdamW **lr 3e-4**, weight decay 1e-4; batch **64**; ≤ 12 epochs with **early stop** (patience 4) on
held-out F1; class-balanced cross-entropy; seed 1234. Augmentation: flips + 90° rotations, small
scale/rotate/shift, brightness/contrast jitter, and **random intensity inversion** (stain-polarity
robustness). Fine-tuning loop: 4 rounds of hard-negative mining under leave-one-plate-out.

## Evaluation
| Protocol | Held-out | Result |
|---|---|---|
| **Cross-plate** (base, `train_clf.py`) | plates `I70T` + `WT2` (1604 patches) | **F1 0.978** (P 0.964 / R 0.992 @0.5) |
| **Leave-one-plate-out** (fine-tune loop) | each of `WT` / `2-4` / `G12E` in turn | **F1 ≈ 0.95** (best 0.9544) |
| **Deployed, in the Precise engine** — *authors' validation* | GT plates + n = 100 vs Fiji | detection **precision 1.00**, diameter **r ≥ 0.99** vs hand labels; **ICC 0.97** vs independent Fiji ([VALIDATION_RESULTS.md](VALIDATION_RESULTS.md)) |
| **External-data A/B** | same held-out | VACV **−0.0027** F1; OnePetri **+0.0003** F1 (both negligible) |
| **Engine-level FP** (negative controls) | 17 blank plates | Precise **≈ 3 FP/blank** (irreducible by gate/classifier tuning) |

Scoring: position match (centre within `0.5 ×` GT radius) → precision / recall / F1
(`app/validate.py`, `_research/clf/gt_sanity.py`, `_research/clf/loop/gt_eval.py`).

## Limitations & ethical considerations
- **Locally validated, not independently peer-reviewed.** As part of the Precise engine, the model
  was validated by the authors on their own plates (precision 1.00 vs hand labels; ICC 0.97 vs Fiji —
  [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md)); only the **Published** engine is
  peer-reviewed/citable. Its *training* labels are partly detector-derived — a training-set caveat,
  not a validation gap.
- **Small, single-operator ground truth** (a few plates, one labeller); no inter-observer check.
- **Imaging ceiling, not the model:** residual false positives are genuinely plaque-like artifacts
  (bubbles, debris) on top-lit phone photos — a dedicated study showed they are **not** reducible by
  classifier or gate tuning. Back-lit, even illumination helps at the source.
- **Distribution:** validated only on the authors' phage plates; treat other organisms / imaging
  setups as out-of-distribution until validated locally.
- **Licence:** non-commercial (CC BY-NC-SA) by inheritance; do not ship in a commercial product.

## Reproduce
`_research/clf/train_clf.py` (base) · `_research/clf/loop/train_loop.py`, `ab_loop.py`,
`promote_and_validate.py` (loop + A/B + deploy) · run in the `plaqseg`/`plaqueapp` env (torch +
torchvision). See [TRAINING_AND_MODELS.md](TRAINING_AND_MODELS.md).
