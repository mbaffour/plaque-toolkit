# Third‑party components & licences

Plaque Toolkit bundles the components below. This file is the attribution/disclosure required by
those licences (Apache‑2.0 §4, AGPL‑3.0/LGPL‑3.0 conveyance, CC BY‑NC‑SA attribution). See
[`LICENSING.md`](LICENSING.md) for what each build (Light vs Full) is licensed as overall.

Legend — **Build**: L = shipped in the Light installer, F = Full only. SPDX identifiers are used.

## Core algorithm & this project

| Component | Version | Licence (SPDX) | Build | Source / copyright |
|---|---|---|---|---|
| **Plaque Toolkit** (this project) | 1.0.x | Apache‑2.0 | L,F | © 2026 Michael Baffour Awuah · https://github.com/mbaffour/plaque-toolkit |
| **Plaque Size Tool** (Trofimova & Jaschke 2021) — the detection/sizing algorithm behind the Published/Current/Sensitive engines; **modified** (see [`NOTICE`](NOTICE)) | — | Apache‑2.0 | L,F | © Ellina Trofimova, Ilya Trofimov · https://github.com/ellinium/plaque_size_tool |

## Deep‑learning stack (Full build only)

| Component | Version | Licence (SPDX) | Build | Notes / source |
|---|---|---|---|---|
| **Ultralytics YOLO** (runs the PlaqSeg model) | 8.4.79 | **AGPL‑3.0‑only** | F | Copyleft — governs the whole Full build. Paid Enterprise licence is the commercial alternative. https://github.com/ultralytics/ultralytics · https://www.ultralytics.com/license |
| **PlaqSeg detector weights** (`_plaqseg/models/small.pt`, `nano.pt`) — YOLO‑seg trained on OnePetri data | — | **CC‑BY‑NC‑SA‑4.0** (weights) + AGPL‑3.0 (runtime) | F | NonCommercial · Attribution · ShareAlike. Trained on the OnePetri dataset (below). |
| **ResNet‑18 precision‑gate classifier** (`_research/clf/plaque_clf.pt`) — trained partly on OnePetri patches | — | **CC‑BY‑NC‑SA‑4.0** | F | Inherits NonCommercial from OnePetri training data. Architecture from torchvision (BSD). |
| **OnePetri** (dataset + model lineage) — Shamash & Maurice 2021 | — | code **GPL‑3.0**; dataset **CC‑BY‑NC‑SA‑4.0** | F (derived) | © 2021 Michael Shamash · https://github.com/mshamash/OnePetri · doi:10.1089/phage.2021.0012 |
| **PyTorch** (torch) | 2.12 | BSD‑3‑Clause | F | https://github.com/pytorch/pytorch |
| **torchvision** | 0.27 | BSD‑3‑Clause | F | https://github.com/pytorch/vision |
| **scikit‑image** | 0.25 | BSD‑3‑Clause | F | recall‑pass helpers |

## GUI, imaging & numerics (both builds unless noted)

| Component | Version | Licence (SPDX) | Build | Notes / source |
|---|---|---|---|---|
| **PySide6 / shiboken6 (Qt for Python)** | 6.10–6.11 | **LGPL‑3.0‑only** | L,F | Qt ships as separate dynamic libraries you may **replace** with your own build of the same Qt major version (LGPL‑3.0 §4/§6). © The Qt Company. https://www.qt.io |
| **OpenCV** (opencv‑python) | 4.13 | Apache‑2.0 | L,F | https://github.com/opencv/opencv‑python |
| **NumPy** | 1.26 | BSD‑3‑Clause | L,F | pinned `<2` for the validated engine |
| **pandas** | 2.3 | BSD‑3‑Clause | L,F | |
| **SciPy** | 1.15 | BSD‑3‑Clause | F | |
| **matplotlib** | 3.9–3.10 | matplotlib licence (PSF‑based, permissive) | L,F | |
| **Pillow** | 11–12 | HPND (MIT‑CMU) | L,F | |
| **pillow‑heif** (HEIC decoding) | 1.x | BSD‑3‑Clause wrapper | L,F | wraps **libheif/libde265 (LGPL)** for decode. Some prebuilt wheels also bundle **x265 (GPL‑2.0)** for HEIC *encoding*; the toolkit only **decodes** HEIC. If you repackage and must stay fully permissive, use a decode‑only HEIF backend. |
| **imutils** | 0.5 | MIT | L,F | |
| **roifile** | 2024.9 | BSD‑3‑Clause | (tests) | ImageJ ROI I/O used in validation only |

## Build tooling (not shipped in the app)

| Tool | Licence | Notes |
|---|---|---|
| **PyInstaller** | GPL‑2.0‑or‑later **with a bootloader exception** | The exception explicitly permits shipping the frozen app under **any** licence; it does not impose GPL on the toolkit. |
| **Inno Setup** | free custom licence (permissive) | builds the Windows installers |

## Full licence texts

The complete licence texts of the copyleft components are shipped with the app:

- **AGPL‑3.0** — `dist/PlaqueToolkitFull/_internal/ultralytics-*.dist-info/licenses/LICENSE` (Full build), and https://www.gnu.org/licenses/agpl-3.0.txt
- **LGPL‑3.0** — https://www.gnu.org/licenses/lgpl-3.0.txt (with the GPL‑3.0 base text)
- **CC BY‑NC‑SA 4.0** — https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode
- **Apache‑2.0** — [`LICENSE`](LICENSE) (this repo) and each Apache component's own `LICENSE`.

*Licence identifications are made from each project's published metadata/LICENSE files as of the build
date; verify against the upstream projects before commercial redistribution.*
