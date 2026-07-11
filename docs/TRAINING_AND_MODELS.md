# Training & models — how the learned parts were built

This documents **exactly** how the deep-learning components of the Plaque Toolkit were built,
trained, tuned, and evaluated, so the work is reproducible and correctly credited. Every number
below is taken from a file in the repo (cited inline); where something is not recorded, it says so.

> **Read this together with** [`HOW_IT_WAS_BUILT.md`](HOW_IT_WAS_BUILT.md) (architecture),
> [`ENGINES.md`](ENGINES.md) (the four engines), and [`VALIDATION_RESULTS.md`](VALIDATION_RESULTS.md)
> (the measurement validation). The training scripts live under `_research/` (gitignored bulk;
> code + logs kept locally); the deployed model + inference code are `_research/clf/plaque_clf.pt`
> and `_research/clf/infer.py`.

---

## 0 · What is learned vs not (provenance at a glance)

| Component | Origin | Trained here? | Peer-reviewed? |
|---|---|---|---|
| **PST detection + sizing** (`plaque_size_tool.py`) | Trofimova & Jaschke 2021 (classical CV — adaptive-local threshold → contours) | No (classical, not ML) | **Yes** — the only citable method |
| **PlaqSeg YOLO** (`_plaqseg/models/small.pt`, `nano.pt`) | **External** pre-trained YOLO-seg, OnePetri lineage (Shamash & Maurice 2021) | **No** — inference only | No |
| **ResNet-18 plaque-vs-texture classifier** (`_research/clf/plaque_clf.pt`) | **Ours** — trained in-house (this document) | **Yes** | No |

The only learned component we trained is the **classifier gate**. PlaqSeg is a third-party model we
run for inference; PST is a classical algorithm. Nothing here changes the citable Published engine.

---

## 1 · The classifier: what it is and where it sits

A **ResNet-18 that decides, per candidate detection, "real plaque" vs "lawn texture / artifact."**
It is a **precision gate** applied *after* PST/PlaqSeg detection (`precise/combine.py`), not a
detector. Convention (`precise/combine.py`, `clf_crop`): each candidate is re-cropped to a
**scale-normalized 48×48 BGR patch** so the detection fills ~55 % of the frame (`CLF_PATCH = 48`,
`CLF_FILL = 0.55`); anything the model scores below `CLF_THR` (default **0.5**) is dropped. It is
**opt-in** in the CLI (`--clf`, off by default) and **on by default in the desktop app**
(`precise/pipeline.run_inprocess(..., clf=True)`).

**Architecture** (`_research/clf/train_clf.py`): `torchvision.resnet18` with ImageNet-1k pretrained
weights, final FC replaced by a 2-class head, whole network fine-tuned. Input is BGR→RGB, `/255`,
ImageNet mean/std normalized. The checkpoint stores `state_dict` + metadata (`arch`, `patch=48`,
`mean/std`, `default_thr=0.5`) so `infer.py` can rebuild it.

---

## 2 · Training data

**Positives** (real plaques): 48×48 patches centered on
- **in-house vision ground-truth centers** — an *independent, non-detector* labelling of plates
  `WT` (378), `2-4` (193), `G12E` (305) (`_research/clf/loop/ab_run.log`; built in
  `_research/groundtruth/`), plus detector-union centers from our own plates;
- optionally **external** sets (§5).

**Negatives** (artifacts): lawn texture, rim, label, specks, and — crucially — **hard negatives**
(bubbles, condensation, glare, marbling) mined from **blank, uninfected control plates**
(`_research/autoresearch/mine_negatives.py`, `mine_precise_survivors.py`), sanity-checked to sit far
from any true plaque so faint real plaques are never poisoned into the negative set.

All patches are the same **48×48** convention. Everything is **split by plate** — every augmentation
variant of a plate stays on one side of the split, so there is **no center/augmentation leakage**
and the held-out numbers measure real cross-plate generalization (`train_clf.py`, `HELDOUT_PLATES`).

---

## 3 · Base training (`_research/clf/train_clf.py`)

| Setting | Value |
|---|---|
| Backbone | ResNet-18, ImageNet-1k pretrained, 2-class head, full fine-tune |
| Optimizer | AdamW, **lr 3e-4**, weight decay 1e-4 |
| Batch / epochs | **64** / ≤ 12 with **early stop** (patience 4) on held-out F1 |
| Loss | class-balanced cross-entropy (weights ∝ 1/class count) |
| Seed | 1234 (deterministic) |
| Augmentation | flip + 90° rotations, small scale 0.85–1.15 + ±15° rot + ±3 px shift, brightness/contrast jitter, **random intensity inversion (50 %)** for stain-polarity robustness |
| Held-out plates | `I70T`, `WT2` (entirely held out) |

**Result** (`train_report.json`, `train_log.txt`) — held-out = 1604 patches (624 pos / 980 neg):

| Run | n_train (pos/neg) | best epoch | Held-out F1 @0.5 (P / R) | Tuned-threshold F1 |
|---|---|---|---|---|
| **local only** *(winner)* | 5828 (2888/2940) | 4 | **0.978** (0.964 / 0.992) | 0.979 @ thr 0.625 |
| local + VACV | 8328 (5388/2940) | 8 | 0.975 (0.976 / 0.974) | 0.977 @ thr 0.425 |

**Adding the external VACV positives *hurt* slightly (ΔF1 = −0.0027)**, so the winner was
**local-only** (`"external_helped": false`). This is an honest negative result on external data (§5).

---

## 4 · The leave-one-plate-out fine-tuning loop (`_research/clf/loop/`)

The base model was then improved by an **iterative hard-negative-mining loop**
(`train_loop.py`, `ab_loop.py`): each round mines the model's confident false positives on blank
lawn, adds them as negatives, retrains, and evaluates under a strict **leave-one-plate-out (LOO)**
protocol across the three GT plates (`WT`, `2-4`, `G12E`) — the plate being scored is never a
training source, so the objective can't leak.

An explicit **A/B on the OnePetri external positives** (`ab_run.log`), 4 rounds each:

| Arm | Best LOO F1 (round) | Deploy checkpoint |
|---|---|---|
| **without** OnePetri | 0.9541 (r4, thr 0.40) | `loop/plaque_clf_without_onepetri.pt` |
| **with** OnePetri | 0.9544 (r4, thr 0.50) | `loop/plaque_clf_with_onepetri.pt` |

**Verdict: ΔF1 = +0.0003 — OnePetri's 6000 positives made no meaningful difference** (both beat the
prior 0.954). Per-plate LOO F1 spans ~0.93–0.97. So, as with VACV, the external phage data was
*not* the lever; the in-house GT + hard-negative mining under LOO was.

**The deployed model.** `_research/clf/plaque_clf.pt` is **byte-identical (md5 `72413d31…`) to
`_research/clf/loop/plaque_clf_onepetri.pt`** — the OnePetri-augmented loop fine-tune, promoted via
`promote_and_validate.py` (which backs the pre-loop model up to `plaque_clf_v1.pt`). Checkpoint map:

| File(s) (same md5) | Role |
|---|---|
| `plaque_clf.pt` = `loop/plaque_clf_onepetri.pt` | **DEPLOYED** (LOO F1 ≈ 0.95) |
| `plaque_clf_v1.pt` = `plaque_clf_preloop.pt` | pre-loop backup |
| `plaque_clf_pre_onepetri.pt` = `loop/plaque_clf_loop.pt` | loop model before the OnePetri arm |
| `loop/plaque_clf_with_onepetri.pt` / `loop/plaque_clf_without_onepetri.pt` | the two A/B deploy models |

---

## 5 · External datasets — provenance, licences, and why they didn't help

Documented in full in `_research/clf/external/SOURCES.md` and `external2/SOURCES.md`.

| Dataset | What / source | Licence | Used how | Effect |
|---|---|---|---|---|
| **VACVPlaque** | 211 phone photos of crystal-violet **Vaccinia** plaques + instance masks; Sci Data 2025, RODARE 3003 | **CC-BY-4.0** (open) | test split → **11,943** 48×48 positives (capped to 2500 in training) | ΔF1 **−0.0027** — auxiliary only; different organism + inverted stain polarity |
| **OnePetri** (phage) | annotated bacteriophage plaques on Roboflow Universe (SEA-PHAGES source) | **CC-BY-NC-SA 4.0** (non-commercial) | 6000 positive patches → A/B arm | ΔF1 **+0.0003** — negligible |
| PlaqSeg / Carbon16 | — | no openly-downloadable, peer-reviewed dataset found | not obtained | — |

**Honest transfer caveats** (`external/SOURCES.md §5`): VACV is a different organism with inverted
contrast polarity, so it is used only as auxiliary/pretraining diversity — which is *why* the
augmentation includes random polarity inversion. **Licence note for the paper/repo:** OnePetri is
**CC-BY-NC-SA** (non-commercial, share-alike) → these third-party images are **not redistributable**
and are kept in the gitignored `_research/` tree, **never shipped** in the app or installers. See
[`LICENSING.md`](../LICENSING.md) / [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).

---

## 6 · False-positive-reduction study — an honest ceiling (`_research/autoresearch/REPORT.md`)

A dedicated round tried to push the classifier/gates to cut false positives on **17 real blank
(no-plaque) control plates**, held out by plate (train IMG_4070–4081, test IMG_4082–4086), under a
hard constraint: don't reduce real counts.

**Baseline false positives per blank plate:** Published **0.88**, Precise **3.35**, Current 4.24,
Sensitive 40.4 (Precise end-to-end held-out ≈ 2.6). Then:
- **Retraining** with +574 blank hard-negatives reached **98–99.5 % crop-level rejection**, but
  **end-to-end blank FP barely moved (2.6 → 2.4)** while real counts dipped — the surviving FPs are
  genuinely *plaque-like* (bubbles with dark rings, debris), not cleanly separable from real plaques.
- A **photometric bubble filter** was implemented and **rejected** — it flags ~30 % of real plaques.
- Sweeping the PST-recall `CONTRAST_FLOOR` gate cut blank FP negligibly but violently perturbed real
  plates — **not a usable lever**.

**Conclusion:** the residual **~3 FP per blank plate on Precise is irreducible by classifier/gate
tuning on this data** — a real imaging ceiling, not a tuning failure. **No candidate model passed the
acceptance gate, so nothing was deployed** — `plaque_clf.pt` is unchanged since the §4 loop. (A
grayscale-input robustness bug was found and fixed during this round.) The practical upshot: use
**Published** when a near-zero FP rate matters; use **Precise + a few seconds of editor review**
otherwise. These are the **defensible negative-control numbers** for a methods section.

---

## 7 · Precise-engine gate tuning (`_research/autotune/`)

A deterministic search (`autotune.py`) tunes the **Precise-only** gate parameters against a
non-circular objective built from *your own* data (the Published path is never touched):

```
fitness = micro-F1 on hand-labelled plates  −  fp_weight × (mean false positives per blank)
```

with a **search / held-out split** so the winning config is reported on plates the search never saw.
Tunable gates and their shipped defaults (source of truth = `precise/combine.py`):

| Param | Default | Meaning |
|---|---|---|
| `CONTRAST_FLOOR` | 0.030 | center-vs-ring contrast a PST-recall candidate must clear |
| `LAWN_FRAC` | 0.80 | lawn ROI = inner fraction of dish radius |
| `DENSE_FACTOR` | 1.5 | density switch (trust PlaqSeg alone above this) |
| `MATCH_TOL_SCALE` | 1.0 | PlaqSeg/PST de-dup match-radius multiplier |
| `CLF_THR` | 0.5 | classifier keep-threshold |

---

## 8 · Ground truth & the evaluation harness

Ground-truth plaque sets were built **in the app** (auto-detect → hand-correct → `Export ▾ →
Ground-truth labels`, schema `plaque-groundtruth-v1`; `app/plaque_canvas.py`) and under
`_research/groundtruth/` (detect → tile → human review → finalize). Detections are scored against GT
by **position match** (a detection is a true positive only if its centre is within `0.5 ×` the GT
radius), giving precision / recall / F1 plus per-plaque diameter agreement
(`app/validate.py`, `_research/score_methods.py`, `_research/clf/gt_sanity.py`,
`_research/clf/loop/gt_eval.py`). The final **measurement** validation (Toolkit vs independent Fiji,
n = 100, ICC 0.97) is reported separately in [`VALIDATION_RESULTS.md`](VALIDATION_RESULTS.md).

---

## 9 · PlaqSeg — external, inference only

`_plaqseg/models/small.pt` and `nano.pt` are **pre-trained YOLO-segmentation weights of the OnePetri
lineage** (Shamash & Maurice, *PHAGE* 2021; weights GPL-3.0). They were **not trained in this
project** and PlaqSeg is **not peer-reviewed**. We use them for **inference only**, tiled over the
dish with global NMS (`_plaqseg/run_plaqseg.py`). Credit and licences: `CREDITS_AND_LINEAGE.md`,
`THIRD_PARTY_LICENSES.md`.

---

## 10 · Honest summary

- The **classifier is the only model we trained.** It is a ResNet-18 precision gate at **LOO F1 ≈
  0.95** on our GT plates; it is **opt-in** and does not replace visual review.
- **External phage/plaque datasets barely moved the needle** (VACV −0.0027, OnePetri +0.0003) — the
  gains came from in-house ground truth + leave-one-plate-out + hard-negative mining.
- **Only the Published engine is peer-reviewed/citable.** The classifier, Precise, and PlaqSeg are
  in-house/external extensions validated on our own plates, not independently.
- **Third-party training images (OnePetri, CC-BY-NC-SA) are non-redistributable** and are never
  shipped; they live only in the gitignored `_research/` tree.

### Reproduce
Base train: `_research/clf/train_clf.py` · Loop + A/B: `_research/clf/loop/train_loop.py`,
`ab_loop.py`, `promote_and_validate.py` · Precise tuning: `_research/autotune/autotune.py` ·
FP study: `_research/autoresearch/` (`mine_negatives.py`, `retrain.py`, `eval.py`,
`sweep_contrast.py`, `REPORT.md`) · Scoring: `app/validate.py`, `_research/score_methods.py`.
*(Run the training in the `plaqseg`/`plaqueapp` env — torch + torchvision.)*
