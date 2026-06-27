# Plaque Size Tool — guide (core size measurement)

A focused guide to **`plaque_size_tool.py`** on its own: the command‑line tool that detects
bacteriophage plaques on a Petri‑dish photo and measures their **size** (area + diameter, in
pixels and mm). This is the validated core of the wider toolkit.

> Looking for turbidity comparison across phages, the interactive editor, or the desktop app?
> See **`USER_GUIDE.md`** / **`guide.html`**. This page is *only* the size CLI.

It is built on the peer‑reviewed Plaque Size Tool (Trofimova & Jaschke, *Virology* 2021). By
default the detection/sizing **algorithm is the published one**; two tiny numerical corrections are
applied (below) and can be turned off with `--published`.

---

## What it does
For each non‑overlapping plaque it finds, it reports the **area** and an **area‑equivalent
diameter** (`2·√(area/π)`) in pixels, and in **mm** when you give the dish diameter. It writes a CSV
of measurements and an annotated image with every plaque circled and numbered.

Supported inputs: **TIFF, JPG, PNG, and HEIC** (iPhone — read directly, EXIF‑orientation aware).

---

## Setup
Runs in the `plaque` conda env (Python 3.9, **numpy < 2**, opencv, pandas, Pillow, pillow‑heif,
imutils, matplotlib):
```
conda env create -f environment.yml          # or: conda create -n plaque python=3.9 && pip install -r requirements.txt
```
Run it with `conda run -n plaque python plaque_size_tool.py …`, or just drag images onto
**`Measure Plaques.bat`**.

---

## Usage
```
python plaque_size_tool.py (-i IMAGE | -d FOLDER) [-p MM] [-small] [--watershed] [--published]
```

| Flag | Meaning |
|------|---------|
| `-i PATH` | process one image |
| `-d PATH` | process every image in a folder (batch) |
| `-p MM` | Petri‑dish diameter in mm → enables the mm columns (e.g. `-p 100`) |
| `-small` | for plaques < ~2.5 mm or low‑resolution images |
| `--watershed` | also split **touching/merged** plaques and recover them (adds a `SOURCE` column) |
| `--published` | reproduce the **exact** published Plaque Size Tool output (disables the two corrections; also forces `--watershed` off) |
| `-debug` | write intermediate processing images |

**Examples**
```powershell
# one image, 100 mm dish
conda run -n plaque python "plaque_size_tool.py" -i "C:\imgs\plate1.heic" -p 100

# a whole folder of small-plaque plates
conda run -n plaque python "plaque_size_tool.py" -d "C:\imgs\plates" -p 100 -small

# split touching plaques too
conda run -n plaque python "plaque_size_tool.py" -i "C:\imgs\dense.tif" -p 100 --watershed

# exact published-tool output (for direct citation)
conda run -n plaque python "plaque_size_tool.py" -i "C:\imgs\plate1.tif" -p 100 --published
```

Either `-i` or `-d` is required. Output always goes to an **`out/`** folder next to where you run it.

---

## Output

**`out/data-green-<name>.csv`** — one row per plaque:

| Column | Unit | Meaning |
|--------|------|---------|
| `INDEX_COL` | – | plaque id (matches the number on the image) |
| `AREA_PXL` | px² | convex‑hull area |
| `DIAMETER_PXL` | px | area‑equivalent diameter, `2·√(area/π)` |
| `AREA_MM2` | mm² | area (0 if no `-p`) |
| `DIAMETER_MM` | mm | area‑equivalent diameter in mm |
| `MEAN_GRAY` | 0–255 | raw mean brightness inside the plaque |
| `TURBIDITY_REL` | 0–1 | **within‑plate** clarity index (0 = clearest plaque on this plate, 1 = lawn). *Relative to this plate only — not comparable across plates.* For comparable turbidity use the batch OD tool (`plaque_turbidity.py`). |
| `SOURCE` | – | only with `--watershed`: `auto` or `watershed` (recovered) |

**`out/out_<name>.<ext>`** — the image with plaques circled (green; watershed‑recovered in cyan)
and numbered. HEIC inputs are saved as `.png` (OpenCV can't write HEIC).

---

## Good to know
- **mm calibration** uses the detected dish diameter: `mm_per_px = plate_mm / dish_diameter_px`.
  Image plates **straight‑on** — a tilted photo makes the dish elliptical and biases every mm value.
  The tool **warns** if the detected dish axis‑ratio exceeds 1.03.
- **No `-p`** → measurements are reported in **pixels only** (mm columns are 0). If `-p` is given but
  no dish is detected, it warns and falls back to pixels.
- **Overlapping plaques** are skipped by default (the detector keeps non‑overlapping ones); use
  `--watershed` to split and recover touching ones.
- **The two default corrections** (vs `--published`): values are kept numeric (not truncated to 2 dp),
  and concentric "circle‑in‑circle" duplicates keep one plaque instead of deleting both. On the
  bundled test plates this leaves the **count unchanged** and changes individual diameters by
  **≤ ~0.04 mm**. Use `--published` for byte‑identical published output.
- **Size = convex‑hull area** → a slight *upper* bound that includes any halo (inherited from the
  published method; state this in a paper).

---

## Try it on the bundled samples
```powershell
conda run -n plaque python "plaque_size_tool.py" -i "Test_plates\large\Plate_2.tif" -p 100
conda run -n plaque python "plaque_size_tool.py" -i "Test_plates\small\Plate_1.tif" -p 100 -small
```
Then open `out\data-green-Plate_2.csv` and `out\out_Plate_2.tif`.

---

## Citation
> Trofimova E, Jaschke PR. *Plaque Size Tool: An automated plaque analysis tool for simplifying and
> standardising bacteriophage plaque morphology measurements.* Virology. 2021;561(April):1–5.
> doi:10.1016/j.virol.2021.05.011

Tool version: `plaque_size_tool.__version__` = 1.0.0 (this build). The mm‑precision/de‑dup
corrections, HEIC reading, `--watershed`, `--published`, and `TURBIDITY_REL` are additions to that
validated tool; the default detection/sizing algorithm is unchanged.
