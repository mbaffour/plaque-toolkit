# Plaque Toolkit — User Guide

> **New here?** Start with the top-level [README](../README.md). For the four detection
> engines and which one to cite, see [ENGINES.md](ENGINES.md); to publish, see
> [PUBLICATION.md](PUBLICATION.md); to install, see [INSTALL.md](INSTALL.md). This page is the
> **how-to-do-each-task** guide.

A cross-platform Python toolkit for measuring bacteriophage **plaques** on Petri‑dish photos:
**size** (area & diameter in mm), **turbidity** (clarity / optical density), **count**, and
**titer (PFU/mL)** — with an interactive editor, batch cross‑phage comparison, and
publication‑ready figures.

It is built on the **published, peer‑reviewed Plaque Size Tool** (Trofimova & Jaschke,
*Virology* 2021). The validated detection/sizing algorithm is preserved as the **Published**
engine; the toolkit adds turbidity, a GUI, the **Sensitive** and **Precise** detection modes,
iPhone/HEIC support, overlap (watershed) segmentation, and quality control — all in-house and
**not** independently validated ([ENGINES.md](ENGINES.md), [PUBLICATION.md](PUBLICATION.md)).

> **Engine note.** This guide's launchers default to the **Current (corrected)** engine and let
> you switch to **Published**, **Sensitive**, or (in the app / `Precise Detect (best engine).bat`)
> **Precise**. The deep-learning **Precise** detector (PST + PlaqSeg YOLO) is now built — it ships
> in the all-in-one installer and via the two-env run-from-source path.

---

## Table of contents
1. [The 30‑second version](#1-the-30-second-version)
2. [What it measures](#2-what-it-measures)
3. [Which tool should I use?](#3-which-tool-should-i-use)
4. [Setup (one time)](#4-setup-one-time)
5. [The drag‑and‑drop launchers](#5-the-drag-and-drop-launchers)
6. [Command‑line reference](#6-command-line-reference)
7. [Output files & data dictionary](#7-output-files--data-dictionary)
8. [Understanding turbidity (important)](#8-understanding-turbidity-important)
9. [Imaging protocol for publishable turbidity](#9-imaging-protocol-for-publishable-turbidity)
10. [Special modes: --watershed and --published](#10-special-modes)
11. [Using it in a paper (stats, QC, methods)](#11-using-it-in-a-paper)
12. [Optional / future work](#12-optional-future-work)
13. [Troubleshooting](#13-troubleshooting)
14. [Files in this folder](#14-files-in-this-folder)
15. [Citation](#15-citation)

---

## 1. The 30‑second version

**Easiest — the desktop app.** Install via **`Output\PlaqueToolkitSetup.exe`** (or the Precise-included
**`Output\PlaqueToolkitFullSetup.exe`**), double‑click the built **`dist\PlaqueToolkit.exe`**, or run the
app from source with **`Plaque Toolkit.bat`** (see [INSTALL.md](INSTALL.md)). One window does it all:
- **Measure tab** — pick the **engine** (Published / Current / Sensitive / Precise) → open an image →
  auto‑detect → edit by hand (drag to add, Trace‑click, right‑click remove) → live size + turbidity table →
  scale bar → Save.
- **Compare turbidity tab** — pick a folder of phages (+ optional blank/flat references) → optical‑density
  turbidity, clarity class, count/PFU titer, per‑phage stats table, and box/histogram figures.
- **About tab** — versions and engine/validation notes.

iPhone **HEIC works directly**. (Rebuilding the installers is covered in
[DEVELOPER.md](DEVELOPER.md).)

---

**Prefer scripts? The 30‑second launcher version:**

**I have one image and want size + a quick turbidity read:**
> Drag the image onto **`Measure Plaques.bat`** → press `N` (normal plaques) → type `100`
> (dish mm) → the `out\` folder opens with `data-green-<image>.csv`.

**I want to compare turbidity across phages (the real, publishable measure):**
> Put one image per phage in a folder → drag the **folder** onto **`Compare Turbidity.bat`** →
> answer the prompts → read `out_turbidity\per_phage.csv` and the figures.

iPhone **HEIC images work directly** — no conversion needed.

---

## 2. What it measures

| Quantity | Where you get it |
|---|---|
| Plaque **area** (px² and mm²) | every tool |
| Plaque **diameter** (px and mm) | every tool |
| Plaque **count** | every tool |
| **Brightness** inside each plaque (`MEAN_GRAY`, 0–255) | every tool |
| **Turbidity / clarity** — within‑plate index | size tool & GUI |
| **Turbidity — absolute optical density (OD)** + clarity class | turbidity batch tool |
| **Titer (PFU/mL)** | turbidity batch tool (`--dilution` + `--volume-ul`) |
| **Per‑phage statistics + box/histogram figures** | turbidity batch tool |

mm values require the dish diameter (`-p`, e.g. `100`). Without it you still get pixel values.

---

## 3. Which tool should I use?

```
Do you want to COMPARE turbidity across different phages/plates?
│
├── YES → Compare Turbidity.bat  (or plaque_turbidity.py)
│         absolute OD, clarity class, count + PFU/mL, per-phage stats, figures.
│         This is the tool for a publication comparison.
│
└── NO, just measure one plate (or a few independently)
     │
     ├── Need to hand-correct (add missed / remove false plaques)?
     │      → Edit Plaques (GUI).bat   (interactive editor)
     │
     └── Just want the numbers automatically?
            → Measure Plaques.bat       (size + within-plate turbidity)
```

| Tool | File | Best for |
|---|---|---|
| **Measure Plaques** | `plaque_size_tool.py` | Fast automatic size + count + turbidity index for one image or a folder. |
| **Edit Plaques (GUI)** | `plaque_gui.py` | Reviewing/correcting detection by hand before saving. |
| **Compare Turbidity** | `plaque_turbidity.py` | Cross‑phage turbidity (OD), titer, stats, figures — the publishable comparison. |
| **HEIC → TIFF** | `heic_to_tiff.py` | Only if you want TIFF copies; all tools already read HEIC directly. |

---

## 4. Setup (one time)

Already done on this machine. To reproduce elsewhere:

```powershell
conda env create -f environment.yml      # creates env 'plaque' (Python 3.9)
# or:
conda create -n plaque python=3.9 -y
conda run -n plaque pip install -r requirements.txt
```

> **Important:** numpy must stay **< 2** (pinned in `requirements.txt`). The upstream tool used
> an API that numpy 2.0 removed. Don't `pip install --upgrade numpy` in this env.

You run tools either via the `.bat` launchers (double‑click / drag) or with
`conda run -n plaque python <tool>.py ...`.

---

## 5. The drag‑and‑drop launchers

These are the easiest way — no commands. Each prompts for plaque size (Normal/Small) and dish
diameter, then opens the results folder.

### `Measure Plaques.bat` — automatic size + turbidity
- **Drag one or more images** onto it (HEIC/TIFF/JPG/PNG).
- Press `N` (normal) or `S` (small, <2.5 mm); type the dish mm (default 100).
- Results appear in `out\`: `data-green-<image>.csv` + an annotated `out_<image>` image.

### `Edit Plaques (GUI).bat` — interactive editor
- **Drag one image** onto it (or double‑click to pick a file).
- A window opens with auto‑detected plaques outlined. Controls:
  | Action | How |
  |---|---|
  | Add a missed plaque (circle) | left‑press at centre, drag to edge, release |
  | Add a missed plaque (auto‑trace) | click **Mode** → **Trace**, then left‑click the plaque |
  | Remove a plaque | right‑click it |
  | Undo / Save / Help | buttons (or keys `u` / `s` / `h`) |
- Click **Save** → writes `out\data-green-<image>.csv` (+ a `SOURCE` column: `auto` / `manual` /
  `watershed`) and an annotated image. Manual additions are appended to the automatic ones.

### `Compare Turbidity.bat` — cross‑phage turbidity (batch)
- **Name each image after its phage** (e.g. `T4.heic`, `T7.heic`).
- **Drag the folder** onto it.
- Answer: plaque size, dish mm, and (optionally) paths to a **blank‑agar** image and a
  **flat‑field** image (press Enter to skip — see [§9](#9-imaging-protocol-for-publishable-turbidity)).
- Results appear in `out_turbidity\` (see [§7](#7-output-files--data-dictionary)).

---

## 6. Command‑line reference

Run from the `Plaque Size Tool` folder. Prefix everything with `conda run -n plaque python`.

### `plaque_size_tool.py` — size + count + turbidity index
```
plaque_size_tool.py  (-i IMAGE | -d FOLDER)  [-p MM] [-small] [--watershed] [--published]
```
| Flag | Meaning |
|---|---|
| `-i PATH` | one image |
| `-d PATH` | a folder of images (batch) |
| `-p 100` | dish diameter in mm (enables mm columns) |
| `-small` | plaques < 2.5 mm / low‑res images |
| `--watershed` | also split touching/merged plaques ([§10](#10-special-modes)) |
| `--published` | reproduce the *exact* published tool output ([§10](#10-special-modes)) |

Output → `out\data-green-<name>.csv` and `out\out_<name>.<ext>`.

Example:
```powershell
conda run -n plaque python "plaque_size_tool.py" -i "C:\imgs\plate1.heic" -p 100 --watershed
```

### `plaque_gui.py` — interactive editor
```
plaque_gui.py  [IMAGE | -i IMAGE]  [-p MM] [-small] [--watershed] [--published] [-o OUTDIR]
```
No image → a file picker opens. Same outputs as the size tool plus a `SOURCE` column.

### `plaque_turbidity.py` — cross‑phage turbidity (the publishable one)
```
plaque_turbidity.py  -d FOLDER  [-p MM] [-small]
                     [--blank BLANK_IMG] [--flat FLAT_IMG] [--dark DARK_IMG]
                     [--core 0.6] [--group-by-prefix]
                     [--dilution 1e6 --volume-ul 10]
                     [--watershed] [--published] [--no-overlay] [--no-plots] [-o OUTDIR]
```
| Flag | Meaning |
|---|---|
| `-d FOLDER` | folder of plate images (filename = phage label) |
| `--blank IMG` | blank‑agar plate = the clear reference `I₀` → enables **absolute OD** |
| `--flat IMG` | flat‑field (bare light box) → corrects uneven illumination |
| `--dark IMG` | dark frame (lens covered) → removes the black‑level offset |
| `--core 0.6` | measure only the central 60 % of each plaque (avoids halo/edge contamination) |
| `--group-by-prefix` | treat `T4_1`, `T4_2` as replicates of phage `T4` |
| `--dilution`, `--volume-ul` | compute PFU/mL titer |
| `--watershed` | split touching plaques first |
| `--no-overlay`, `--no-plots` | skip the QC overlays / figures |

Output → `out_turbidity\` (default).

Example (full, with references and titer):
```powershell
conda run -n plaque python "plaque_turbidity.py" -d "C:\phages" -p 100 ^
   --blank "C:\refs\blank.tif" --flat "C:\refs\flat.tif" ^
   --group-by-prefix --dilution 1e6 --volume-ul 10
```

### `heic_to_tiff.py` — convert HEIC → TIFF (rarely needed)
```
heic_to_tiff.py  -d FOLDER  [-o OUTFOLDER]
```

---

## 7. Output files & data dictionary

### Size tool / GUI → `out\`
- **`data-green-<name>.csv`** — one row per plaque:

| Column | Unit | Meaning |
|---|---|---|
| `INDEX_COL` | – | plaque id |
| `AREA_PXL` | px² | convex‑hull area |
| `DIAMETER_PXL` | px | area‑equivalent diameter, `2·√(area/π)` |
| `AREA_MM2` | mm² | area (0 if no `-p`) |
| `DIAMETER_MM` | mm | area‑equivalent diameter in mm |
| `MEAN_GRAY` | 0–255 | mean brightness inside the plaque |
| `TURBIDITY_REL` | 0–1 | **within‑plate** clarity index (0 = clearest plaque here, 1 = lawn). *Not* cross‑plate comparable — see [§8](#8-understanding-turbidity-important). |
| `SOURCE` *(GUI / `--watershed` only)* | – | `auto` / `manual` / `watershed` |

- **`out_<name>.<ext>`** — annotated image (plaques circled + numbered; watershed‑recovered in cyan).

### Turbidity batch tool → `out_turbidity\`
- **`plaques_all.csv`** — every plaque, every plate: `PHAGE, PLATE, PLATE_INDEX, AREA_PXL,
  DIAMETER_MM, MEAN_GRAY, TRANSMITTANCE (I/I₀), OD (−log₁₀(I/I₀)), OD_LAWN, TURBIDITY (OD/OD_lawn,
  0–1), CLARITY (clear/intermediate/turbid)`.
- **`per_phage.csv`** — the comparison table. Per phage: `N_PLATES, N_PLAQUES`, and for each metric
  a `*_PLAQUE_MEAN` (pooled) plus `*_PLATE_MEAN` / `*_PLATE_SD`. **Use the PLATE‑level columns for
  statistics** (see [§11](#11-using-it-in-a-paper)).
- **`qc.csv`** — per plate: `DISH_FOUND, I0_LEVEL, LAWN_I, OD_LAWN, ILLUM_CV (illumination
  unevenness), FRAC_DARKER_THAN_LAWN, FRAC_OVERCLEAR, FRAC_SATURATED (clipped pixels),
  POLARITY_OK, ABSOLUTE_OD, COUNT, PFU_PER_ML`.
- **`overlay_<plate>.png`** — QC image: dish outline + plaques coloured green→red by turbidity.
- **`compare_<metric>.png`, `hist_<metric>.png`** — per‑phage box plots & histograms of diameter
  and turbidity (publication figures).
- **`run_metadata.json`** — provenance: tool version, all settings, library versions, and a hash
  of every input image (for reproducibility / methods).
- **`errors.csv`** — only if some image failed (the batch continues past bad files).

---

## 8. Understanding turbidity (important)

Plaque turbidity = how cloudy vs clear a plaque is (a lytic phenotype signal). There are **two
different turbidity numbers** in this toolkit — use the right one:

1. **`TURBIDITY_REL` from the size tool / GUI** = a **within‑plate relative index** (0 = clearest
   plaque on *that* plate, 1 = the lawn). Great for ranking clear‑vs‑turbid **on one plate**.
   **Do NOT compare it across plates or phages** — each plate is scaled to its own plaques.

2. **`OD` / `TURBIDITY` from the turbidity batch tool** = **(apparent) optical density**,
   `OD = −log₁₀(I/I₀)`, anchored to **shared physical references** (clear agar `I₀` and the
   bacterial lawn). Comparable across plates/phages — the publishable measure. **Note:** it is a
   true *absorbance* only with radiometrically **linear input** (camera RAW / linear TIFF, ideally
   `--dark`+`--flat`); from iPhone HEIC/JPEG (tone‑mapped) it is an *apparent* OD — a within‑session
   relative measure. Use RAW/linear input for any absolute‑OD claim in a paper.

For the cross‑phage comparison you actually want, run **`Compare Turbidity.bat`** /
`plaque_turbidity.py`, ideally with a `--blank` reference. Without `--blank` it reports only a
relative `TRANSMITTANCE` (qualitative).

---

## 9. Imaging protocol for publishable turbidity

Turbidity is only as good as the imaging. For defensible numbers (transmitted light):

- **Light box** as the only light source. Camera fixed (tripod), straight down, dish centred.
- **Manual everything**: fixed exposure, ISO, focus, **white balance**; **HDR off**. (On iPhone,
  shoot **Apple ProRAW** if possible — HEIC is heavily processed and only semi‑quantitative.)
- Same dish position each shot; lids off (condensation scatters light).
- In one session capture, with identical settings:
  1. a **flat‑field** image (bare light box) → `--flat`
  2. a **blank‑agar** plate, no bacteria → `--blank` (the `I₀` clear reference; **the key one**)
  3. optionally a **dark frame** (lens covered) → `--dark`
  4. all your **phage plates** — filename = phage (use `<phage>_<rep>.ext` + `--group-by-prefix`
     for replicates)
  5. re‑image one plate twice → for a reproducibility number
- **Check `qc.csv` every run:** `POLARITY_OK` should be `True` (clear plaques brighter than lawn),
  `FRAC_SATURATED` ≈ 0 (no clipped pixels), `ILLUM_CV` low (use `--flat` if high).

---

## 10. Special modes

### `--watershed` — split touching/overlapping plaques
The validated detector drops plaques that are fused into a non‑circular blob. `--watershed`
(opt‑in, all tools) splits those blobs — one at a time, using a distance‑transform watershed with
local‑maxima seeding — and recovers the extra plaques, measured by the same math and tagged
`SOURCE=watershed` (drawn cyan). It recovers **real‑sized** plaques on dense plates and **nothing**
on well‑separated ones (no over‑segmentation). It is **off by default** and **forced off** in
`--published` mode, so it never changes the validated result unless you ask for it. (This is the
classical equivalent of what the deep‑learning PlaqSeg app does for overlap.)

### `--published` — exact validated output
By default the size pipeline applies two tiny numerical corrections (un‑truncated mm values; a
fixed concentric‑duplicate rule). On the 17 bundled plates this leaves the plaque **count
unchanged**; individual‑plaque `DIAMETER_MM` differs by **≤ ~0.04 mm** (the concentric‑pair de‑dup
can keep a slightly different surviving contour) — below imaging resolution. If you want output
**identical** to the published Plaque Size Tool (e.g. to cite it directly with no caveat), add
`--published`. The detection *algorithm* is the published one either way.

---

## 11. Using it in a paper

- **Report `OD` as the primary turbidity metric** (a relative optical density — call it *absorbance*
  only with linear/RAW input, see §8); `TURBIDITY` (0–1) is an interpretable secondary scale;
  `CLARITY` gives categorical clear/turbid.
- **Statistics — avoid pseudoreplication.** The **plate is the biological replicate, not the
  plaque.** Use the `*_PLATE_MEAN` / `*_PLATE_SD` columns in `per_phage.csv`, with ≥3 plates per
  phage; compare phages with a non‑parametric test (Mann–Whitney / Kruskal–Wallis) on the
  per‑plate means, or a mixed model with plate as a random effect.
- **State these caveats in Methods:** (1) plaque size is **convex‑hull area**, a slight *upper*
  bound that includes any halo (inherited from the published method); (2) image plates **straight‑on
  (orthographic)** — a tilted phone shot makes the dish elliptical and biases the mm scale (the size
  tool now **warns** when the detected dish axis‑ratio > 1.03); (3) apply `--watershed` **uniformly**
  across all compared phages or not at all; (4) PFU counts are **detected (accepted) plaques only** —
  validate they fall in the 30–300 countable range; (5) for quantitative OD use **RAW/linear input
  with `--dark`/`--flat`**.
- **Methods text** can state: detection & sizing used the validated Plaque Size Tool (cite
  Trofimova & Jaschke 2021) — add "with minor numerical‑precision corrections" or run `--published`
  for an exact‑match; turbidity was measured as transmitted‑light relative optical density vs a
  cell‑free agar reference. Note that turbidity is greyscale densitometry, not a separately
  validated assay.
- **Provenance** is in `run_metadata.json` (versions, settings, image hashes) — keep it.

---

## 12. Optional / future work

- **PlaqSeg deep‑learning detection is now built in** as the **Precise** engine (PST + PlaqSeg
  YOLO‑seg, with size + turbidity measurement) — see [ENGINES.md](ENGINES.md). It runs from the
  all‑in‑one installer (no conda) or the two‑env run‑from‑source path. It is in‑house and
  **not** independently validated.
- **Validate Sensitive/Precise/the classifier on your own plates** before publishing counts or
  sizes from them — the validation playbook is in [PUBLICATION.md](PUBLICATION.md).
- A Cellpose/StarDist deep‑learning backend for the very hardest dense plates.
- Radial OD profile → explicit halo / bull's‑eye detection.

---

## 13. Troubleshooting

| Symptom | Fix |
|---|---|
| `mm columns = 0` / warning "no Petri dish detected" | the dish rim wasn't found; ensure the whole dish is in frame, or report pixels only. |
| 0 plaques found | try `-small`; check the image isn't blurry/over‑exposed; open the annotated image to see what was detected. |
| HEIC won't open in the **size CLI/GUI** | it should work directly; if not, run `heic_to_tiff.py` and use the TIFF. |
| Turbidity values look inverted / `POLARITY_OK=False` | imaging isn't true transmitted light (clear plaques should be *brighter* than the lawn). |
| `TURBIDITY`/`OD` blank in the batch output | you didn't pass `--blank`; only relative `TRANSMITTANCE` is reported then. |
| numpy errors after a `pip upgrade` | reinstall `numpy<2` (`conda run -n plaque pip install "numpy<2"`). |
| Touching plaques missed | add `--watershed`. |
| Precise mode says it's "not available" | the PlaqSeg env or `_plaqseg/models/small.pt` is missing — use the all‑in‑one installer, or create the `plaqseg` env ([INSTALL.md](INSTALL.md)). Other modes keep working. |
| One bad image kills a batch | the turbidity tool skips it and logs `errors.csv`; the size CLI stops — run that image separately. |

---

## 14. Files in this folder

A short orientation; the full map of every top-level item is in [STRUCTURE.md](STRUCTURE.md).

| File | What it is |
|---|---|
| `plaque_size_tool.py` | size + count + turbidity‑index CLI (the validated engine + extensions) |
| `plaque_gui.py` | interactive add/remove editor |
| `plaque_turbidity.py` | batch cross‑phage turbidity (OD), titer, stats, figures |
| `precise/`, `_plaqseg/` | the **Precise** engine (PST + PlaqSeg YOLO) and its model weights |
| `heic_to_tiff.py` | HEIC → TIFF converter |
| `Measure Plaques.bat` / `Edit Plaques (GUI).bat` / `Compare Turbidity.bat` / `Precise Detect (best engine).bat` | drag‑and‑drop launchers |
| `app/` + `plaque_app.py` | the unified PySide6 desktop app (front‑end over the engines) |
| `dist\PlaqueToolkit.exe` | built portable app |
| `Output\PlaqueToolkitSetup.exe` / `…FullSetup.exe` | the shareable installers (Precise built into the Full one) |
| `install.bat` / `uninstall.bat` | install the built app to the Start menu (no admin) / remove it |
| `build/` | PyInstaller specs + Inno Setup installer scripts (see [DEVELOPER.md](DEVELOPER.md)) |
| `requirements.txt` / `environment.yml` / `environment-precise.yml` | dependencies (numpy<2 pinned) |
| `Test_plates\` | bundled sample images (large/ + small/) to try |
| `out\` / `out_turbidity\` | results (created on first run) |
| `../README.md` | project entry point |
| `USER_GUIDE.md` | **this guide** |

---

## 15. Citation

If you use this for published work, cite the underlying tool:

> Trofimova E, Jaschke PR. *Plaque Size Tool: An automated plaque analysis tool for simplifying
> and standardising bacteriophage plaque morphology measurements.* Virology. 2021;561(April):1–5.
> doi:10.1016/j.virol.2021.05.011

The turbidity measurement, GUI, batch OD comparison, and watershed/HEIC/QC extensions are
additions to that validated tool (describe them in your methods as above).
