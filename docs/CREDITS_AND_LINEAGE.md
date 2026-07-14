# What we built on — credits, repos, and licences

This toolkit is not built from nothing. It stands on a published, peer-reviewed method, a
community-trained deep model, an open real-phage dataset, and a stack of open-source
libraries. This page is an honest, itemized attribution: **exactly** which programs,
repositories, models, datasets, and libraries the toolkit depends on, under which licences,
and — just as importantly — **what is original to this project** and what is not.

If you use the toolkit in a publication, see the one-line citation pointer at the end and
read [PUBLICATION.md](PUBLICATION.md) for what is and isn't defensible.

---

## 1. The core we build on — the Plaque Size Tool

The heart of the toolkit is a published, peer-reviewed method that we preserve **unchanged**
as the **Published** engine:

> Trofimova E, Jaschke PR. *Plaque Size Tool: An automated plaque analysis tool for
> simplifying and standardising bacteriophage plaque morphology measurements.* Virology
> 2021;561:1–5. [doi:10.1016/j.virol.2021.05.011](https://doi.org/10.1016/j.virol.2021.05.011)

- **Repository:** [`ellinium/plaque_size_tool`](https://github.com/ellinium/plaque_size_tool)
- **What it does:** adaptive-local thresholding → contour detection → keep non-overlapping,
  roughly-circular contours → measure convex-hull area, with a mm scale calibrated from the
  detected Petri-dish diameter.
- **How we use it:** the upstream detection/sizing algorithm lives essentially unchanged in
  `plaque_size_tool.py`. When run in **Published** mode it reproduces the original
  byte-for-byte (including its quirks), so a citable run can never be altered by any in-house
  feature. This is the **only** peer-reviewed, citable mode in the toolkit.
- The original upstream manual is preserved verbatim at [UPSTREAM_README.md](UPSTREAM_README.md).

**Credit:** all of the validated detection/sizing science is theirs, not ours.

---

## 2. The deep model and dataset behind the Precise engine

The **Precise** engine fuses the classic PST geometry with a deep plaque detector. Two
external components make that possible.

### PlaqSeg — the YOLO-seg plaque detector

- **Source / cite:** **PlaqSeg**, from **PlaqSegDesktop** by *Carbon16* — release `app-v0.2.1`
  (2026-03-19), <https://github.com/Carbon16/PlaqSegDesktop> (release:
  <https://github.com/Carbon16/PlaqSegDesktop/releases/tag/app-v0.2.1>). Cite this if you use the
  Precise engine. The detector weights' underlying training data are OnePetri (below).
- **What it is:** a YOLO segmentation model trained to detect bacteriophage plaques, used as
  the **primary** detector inside the Precise pipeline (weights ship as
  `_plaqseg/models/small.pt` / `nano.pt`; inference is tiled with global NMS).
- **How we use it:** it does the heavy lifting on dense plates where PST alone fuses touching
  plaques.
- **Important honesty note:** **PlaqSeg is NOT peer-reviewed.** Treat Precise as the best
  available *detector*, not as a citable *method*. Any counts/sizes from it must be validated
  on your own plates (see [PUBLICATION.md](PUBLICATION.md)).

### The OnePetri dataset — real bacteriophage plates

- **What it is:** a Roboflow dataset of **real bacteriophage plates**, used to train/run the
  deep detector and to mine classifier training patches.
- **Source:** Roboflow Universe, workspace
  [`michael-shamash-rf-universe`](https://universe.roboflow.com/michael-shamash-rf-universe)
  (OnePetri).
- **Licence:** **CC BY-NC-SA 4.0** — Attribution, **NonCommercial**, ShareAlike.
  - **This is a non-commercial licence.** Anything derived from OnePetri data (including the
    trained detector and the classifier patches mined from it) inherits the **NC**
    (non-commercial) and **SA** (share-alike) obligations. Do not use OnePetri-derived
    artifacts in a commercial product without checking the licence terms and attributing the
    source.

---

## 3. The plaque-vs-texture classifier (ResNet-18)

An optional learned **precision gate** that decides, per candidate, whether a detection is a
real plaque or lawn texture.

- **Architecture:** a **ResNet-18** with a 2-class head, built on **torchvision**
  (`_research/clf/`: `plaque_clf.pt` weights + `infer.py`).
- **Training data:** detector-union labels **plus** an independent vision ground-truth set
  **plus** OnePetri real-phage patches — 15,659 boxes total (see [ENGINES.md](ENGINES.md)).
  Because part of the training data is OnePetri-derived, the classifier inherits the OnePetri
  **CC BY-NC-SA (non-commercial)** obligations (§2).
- **Honesty note:** its *training* labels are partly **detector-derived** (not a blinded manual
  ground truth), so the training set can carry detector biases. Its **outputs, in the Precise
  engine, were validated locally by the authors** (precision 1.00 vs hand labels; ICC 0.97 vs
  independent Fiji — [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md)); it is **not** independently
  or peer-reviewed. Opt-in, default OFF on the CLI.
- **Full details:** exact architecture, hyperparameters, training data, and evaluation are in the
  [**model card**](MODEL_CARD.md) and [TRAINING_AND_MODELS.md](TRAINING_AND_MODELS.md). Key facts:
  the deployed `plaque_clf.pt` is the leave-one-plate-out fine-tune (**LOO F1 ≈ 0.95**), and the
  external datasets barely helped (VACV −0.0027, OnePetri +0.0003 F1).

---

## 4. Tools evaluated or considered (and why they were / weren't adopted)

We looked at several established segmentation tools before settling on the current design.
For transparency, here is what we considered and the decision on each.

| Tool | What it is | Decision |
|---|---|---|
| **ilastik** | Interactive pixel classification | **Used for labelling.** A cheap, fast way to produce ground-truth / training masks, not wired into the runtime detection path. |
| **Cellpose / Omnipose** | Deep cell segmentation | **Not adopted for detection.** Omnipose is tuned for **elongated bacterial cells** — off-target for **round plaques**. |
| **PlaqSeg** | Plaque-specific YOLO-seg | **Adopted** as the Precise primary detector — it is already **plaque-specific**, unlike the general cell-segmentation tools. |

In short: ilastik earned a place as a **labelling** aid; Omnipose/Cellpose target the wrong
object class (elongated cells, not round plaques) and were not adopted for detection; PlaqSeg
was adopted because it is purpose-built for plaques.

---

## 5. Libraries and packaging

The runtime and build stack rests on the following open-source projects. (Full pin lists live
in `environment.yml` / `requirements.txt`, `environment-precise.yml`, and
`requirements_full.txt`; see [DEVELOPER.md](DEVELOPER.md).)

**Core imaging / numerics**

- **OpenCV** — image I/O, thresholding, contour detection, ellipse fitting.
- **NumPy** — array numerics. The **validated engine pins `numpy < 2`** (the upstream tool
  used `np.warnings`, removed in NumPy 2.0). NumPy 1.26 is the version that satisfies both the
  PST `numpy<2` pin and torch/ultralytics, enabling the single-env in-process Precise build.
- **scikit-image** — flat-field / blob-recovery helpers in the Precise recall pass.

**Deep learning (Precise engine)**

- **PyTorch (CPU)** — model runtime for PlaqSeg and the ResNet-18 classifier.
- **torchvision** — the ResNet-18 backbone for the classifier.
- **ultralytics** — YOLO segmentation inference for PlaqSeg.

**Data / images**

- **pandas** — per-plaque / per-phage tables and CSV output.
- **Pillow** and **pillow-heif** — image decoding, including **HEIC** (iPhone) support.
- **tifffile / Pillow** — reading/writing **Fiji-calibrated TIFF** plate crops.

**App and figures**

- **PySide6 (Qt for Python)** — the desktop app and the native `QGraphicsView` editor.
- **matplotlib** — QC figures, box/histogram plots, annotated exports.

**Packaging**

- **PyInstaller** — freezing the app into the light and Full builds.
- **Inno Setup** — the Windows installers (`PlaqueToolkitSetup.exe` and
  `PlaqueToolkitFullSetup.exe`).

**Licences (SPDX).** OpenCV `Apache-2.0`; NumPy / pandas / SciPy / roifile `BSD-3-Clause`;
scikit-image `BSD-3-Clause`; matplotlib `matplotlib/PSF`; Pillow `HPND`; pillow-heif `BSD-3-Clause`
(wraps LGPL libheif/libde265); imutils `MIT`; **PyTorch / torchvision `BSD-3-Clause`**;
**ultralytics `AGPL-3.0`** (copyleft — governs the whole **Full** build; see §7); **PySide6 / Qt
`LGPL-3.0`** (dynamically linked, relinkable). The full per-component table with copyright notices is
in the repo root at [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md); the overall per-build
licensing is in [`LICENSING.md`](../LICENSING.md).

---

## 6. What is ORIGINAL to this toolkit

Everything in this section is **in-house** work — new code and new pipelines built on top of
the components above. (In-house does **not** mean validated: only the Published engine carries
peer-reviewed validation — see [PUBLICATION.md](PUBLICATION.md) and §7.)

- **The Precise fusion pipeline + gates** — the whole `precise/` orchestration that fuses PST
  geometry with PlaqSeg, the artifact masks (lawn ROI, blue-label, dish-boundary reject), the
  density switch, the gated PST-sensitive recall with a center-vs-ring contrast floor, and the
  union/dedup logic.
- **The ML precision gate** — wiring the ResNet-18 plaque-vs-texture classifier in as an
  optional per-candidate gate.
- **Cross-phage turbidity / optical density (OD)** — the transmitted-light densitometry and
  titer batch analysis (`plaque_turbidity.py`).
- **The PySide6 desktop app + native editor** — the Measure / Compare / About tabs and the
  hand-correctable `QGraphicsView` plaque editor.
- **Set-plate manual calibration** — user-set dish diameter for the mm scale.
- **Fiji-calibrated plate crops** — the TIFF crop workflow carrying a physical scale.
- **Batch + Validate tabs** — batch processing and the on-your-own-plates validation workflow.
- **HEIC support** — decoding iPhone HEIC input.
- **Watershed splitting** — distance-transform watershed to split touching/merged plaques
  (opt-in, non-Published modes).
- **The validation harnesses** — the negative-control (uninfected-lawn) and manual
  ground-truth scoring harnesses used to measure the in-house engines.

The **Current** and **Sensitive** engines are also in-house: near-identical refinements of the
published algorithm (bug-fixes, numeric values, corrected roundest-contour dish calibration,
lowered size gates).

---

## 7. Licence and validation honesty in one place

- **Published engine** — reproduces the peer-reviewed Trofimova & Jaschke 2021 method; the
  only citable mode. Credit the paper.
- **PlaqSeg** — **not peer-reviewed.** Best available detector, not a citable method.
- **OnePetri** — **dataset** is **CC BY-NC-SA 4.0 (non-commercial, share-alike, attribution)**;
  **code** is **GPL-3.0** (Shamash & Maurice 2021, doi:10.1089/phage.2021.0012). Everything trained
  on the dataset inherits the CC BY-NC-SA terms.
- **Software licences.** The **Full** build runs on **Ultralytics YOLO (AGPL-3.0, copyleft)** → the
  Full installer as a whole is **AGPL-3.0**, with its deep-model weights **CC BY-NC-SA 4.0
  (non-commercial)**; free for non-commercial research, full source public. The **Light** build has
  no YOLO/weights and is **Apache-2.0 (free for any use)**. Qt/PySide6 is **LGPL-3.0** in both.
  Details: [`LICENSING.md`](../LICENSING.md), [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).
- **Classifier** — trained partly on detector-derived labels + OnePetri patches; **validated
  locally by the authors** as part of the Precise engine but **not independently/peer-reviewed**;
  **CC BY-NC-SA 4.0 (non-commercial)** by inheritance.
- **Current / Sensitive / Precise / classifier / turbidity** — in-house; **do not inherit the
  published validation.** Validate on your own plates before publishing.

---

## How to cite

For the correct citation and the full validation playbook — what you may cite as published,
what you must validate yourself, and suggested Methods text — see **[PUBLICATION.md](PUBLICATION.md)**.

The short version: cite **Trofimova & Jaschke, 2021** (doi:10.1016/j.virol.2021.05.011) and
use the **Published** engine for any number that goes into a paper.

---

*See also: [HOW_IT_WAS_BUILT.md](HOW_IT_WAS_BUILT.md) (build-and-design narrative),
[ENGINES.md](ENGINES.md) (engines in depth), [PUBLICATION.md](PUBLICATION.md) (validation
playbook), and [UPSTREAM_README.md](UPSTREAM_README.md) (the original upstream manual).*
