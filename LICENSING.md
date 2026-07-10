# Licensing — Plaque Toolkit

**Short version: this software is free and open for everyone.** How *freely* you can reuse it
depends on **which build** you take, because the optional deep‑learning detector is built on
components that carry stronger obligations than our own code does.

| | **Light build** — `PlaqueToolkitSetup.exe` | **Full build** — `PlaqueToolkitFullSetup.exe` |
|---|---|---|
| Contains | Published / Current / Sensitive engines, GUI, turbidity, batch, validation | everything in Light **plus** the **Precise** engine (PlaqSeg YOLO + ResNet classifier) |
| Governing licence | **Apache‑2.0** | **AGPL‑3.0** (code) **+ CC BY‑NC‑SA 4.0** (the model weights) |
| Free for research / academic use | ✅ | ✅ |
| Free for **commercial** use / resale | ✅ | ❌ *(the model weights are **NonCommercial**)* |
| You may modify & redistribute | ✅ (keep the notices) | ✅ **if** you also release your source (AGPL) **and** stay non‑commercial + ShareAlike (weights) |

**Our own source code is licensed Apache‑2.0** (see [`LICENSE`](LICENSE)). Apache‑2.0 is one‑way
compatible *into* AGPL‑3.0, so it can serve as the permissive core of either build.

---

## The Light build — Apache‑2.0 (free for any use, including commercial)

The Light installer contains **no** PyTorch, no Ultralytics/YOLO, and **none** of the trained
`.pt` model weights. Everything in it is permissively licensed:

- **Plaque Size Tool** (Trofimova & Jaschke 2021), the peer‑reviewed detection algorithm behind the
  Published/Current/Sensitive engines — **Apache‑2.0** (© Ellina Trofimova, Ilya Trofimov;
  <https://github.com/ellinium/plaque_size_tool>). Our copies are modified; changes are noted in
  [`NOTICE`](NOTICE).
- OpenCV (Apache‑2.0), NumPy / pandas / SciPy / roifile (BSD), matplotlib (PSF/matplotlib), Pillow
  (HPND), imutils (MIT).
- **PySide6 / Qt** — **LGPL‑3.0**. Qt is shipped as separate, dynamically‑loaded shared libraries
  that you may replace with your own build of Qt of the same major version; the LGPL‑3.0 text and
  this relink right are provided in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
- pillow‑heif for HEIC decoding (BSD‑3 wrapper over libheif/libde265, LGPL). *(Note: some prebuilt
  pillow‑heif wheels also bundle the x265 encoder (GPL‑2.0); the toolkit only **decodes** HEIC, which
  uses the LGPL path — see THIRD_PARTY_LICENSES.md if you repackage.)*

**This build is the clean, permissive product**: use it, sell it, embed it — just keep the
attribution notices.

---

## The Full build — AGPL‑3.0 + non‑commercial model weights

The Full installer adds the **Precise** engine, which brings two components with stronger terms:

1. **Ultralytics YOLO** (runs the PlaqSeg segmentation model) — **AGPL‑3.0**. AGPL‑3.0 is a strong
   copyleft licence: distributing software that bundles it means the **whole conveyed work is
   governed by AGPL‑3.0**, and the complete corresponding source must be available to every user.
   That source is this public repository. *(Ultralytics also sell a paid Enterprise licence that
   removes the copyleft obligation — see <https://www.ultralytics.com/license>. We do not use it;
   we comply by being open‑source.)*

2. **The PlaqSeg detector weights and the ResNet‑18 classifier weights**
   (`_plaqseg/models/*.pt`, `_research/clf/plaque_clf.pt`) are trained on the **OnePetri** dataset,
   which is **CC BY‑NC‑SA 4.0** (Attribution — **NonCommercial** — ShareAlike). Anything trained on
   that data inherits those terms, so the weights are **non‑commercial**, must be **attributed**, and
   must be shared **alike**.

**What that means for you:** the Full build is **free to use for non‑commercial research**, free to
study and modify, and you may redistribute it provided you (a) keep it open‑source under AGPL‑3.0,
(b) keep it non‑commercial and ShareAlike for the model weights, and (c) keep the attributions. It is
**not** licensed for commercial use — for that you would need to retrain PlaqSeg + the classifier on
non‑OnePetri data and obtain an Ultralytics Enterprise licence (see
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)).

Because AGPL‑3.0 forbids adding restrictions to the AGPL‑covered *code*, the NonCommercial term
applies to the **model‑weight data files specifically** (which are not AGPL code), while the software
around them is AGPL‑3.0. If you want a build with no such conditions, use the **Light** build.

---

## Attribution (please cite/credit)

- **Plaque Size Tool** — Trofimova E, Jaschke PR. *Plaque Size Tool: an automated plaque analysis tool
  for simplifying and standardising bacteriophage plaque morphology measurements.* Virology
  2021;561:1–5. doi:10.1016/j.virol.2021.05.011
- **OnePetri** (dataset + lineage of the deep detector) — Shamash M, Maurice CF. *OnePetri: …
  bacteriophage plaque assays.* PHAGE 2021. doi:10.1089/phage.2021.0012 ·
  <https://github.com/mshamash/OnePetri> (code GPL‑3.0; dataset CC BY‑NC‑SA 4.0)
- **Ultralytics YOLO** — <https://github.com/ultralytics/ultralytics> (AGPL‑3.0)
- Full per‑component list with licence texts: [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

See also [`docs/CREDITS_AND_LINEAGE.md`](docs/CREDITS_AND_LINEAGE.md) for the full lineage and what is
original to this project, and [`docs/PUBLICATION.md`](docs/PUBLICATION.md) for what is citable.

*This document explains the licences of the components as we understand them; it is not legal advice.
If you plan to distribute commercially, confirm the terms with each upstream project (and a lawyer).*
