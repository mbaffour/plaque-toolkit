# Plaque Toolkit

*Nicknamed **"Frankenstein's Plaque Lab"** — it stitches several tools into one.*

A desktop + command-line toolkit for measuring bacteriophage **plaques** on Petri-dish
photos: **size** (area and diameter in mm), **turbidity** (clarity / optical density),
**count**, and **titer (PFU/mL)** — with an interactive editor, batch cross-phage
comparison, and publication-ready figures. Runs on **Windows** and **macOS (Apple Silicon)**.

It is built on the **published, peer-reviewed Plaque Size Tool**
(Trofimova & Jaschke, *Virology* 2021, [doi:10.1016/j.virol.2021.05.011](https://doi.org/10.1016/j.virol.2021.05.011)).
The validated detection/sizing algorithm is preserved unchanged as a selectable **Published**
mode; everything else (turbidity, the GUI, the Sensitive and Precise detection modes, HEIC
support, watershed splitting, the ML classifier) is an **in-house extension** that has **not**
been independently validated. The distinction matters for publication — see
[**Engines**](docs/ENGINES.md) and [**Publication**](docs/PUBLICATION.md).

> **Honesty note.** Only **Published** mode reproduces a peer-reviewed method and may be
> cited as such. **Current**, **Sensitive**, **Precise**, and the classifier are useful but
> unvalidated; to publish counts/sizes from them you must validate them on your *own* plates
> (see [PUBLICATION.md](docs/PUBLICATION.md)).

---

## 60-second quick start

### Option A — the desktop app (point-and-click)

- **Already installed?** Open **Plaque Toolkit** from the Start menu (or run
  `dist\PlaqueToolkit.exe`).
- **Installer:** run **`Output\PlaqueToolkitSetup.exe`** (~85 MB; Published/Current/Sensitive
  modes) or **`Output\PlaqueToolkitFullSetup.exe`** (~302 MB; **Precise built in**, no conda
  needed). See [INSTALL.md](docs/INSTALL.md).
- **From source (any OS):** `conda env create -f environment.yml` then double-click
  **`Plaque Toolkit.bat`** (Windows) / **`Plaque Toolkit.command`** (macOS) /
  **`Plaque Toolkit.sh`** (Linux).

The app has a **Measure** tab (engine dropdown, drag-and-drop, summary card, editable canvas,
scale bar), a **Compare turbidity** tab, and an **About** tab. Plaques are numbered **1…N from
the top** (row 1 = the topmost plaque), and the green **Export all** button writes the CSV +
annotated figure in one click.

### Option B — drag-and-drop launchers (no app, no commands)

Drag a photo (or folder) onto one of the `.bat` files in this folder. iPhone **HEIC works
directly**.

| Drag onto… | What it does |
|---|---|
| **`Measure Plaques.bat`** | Auto-measure size + turbidity → CSV + annotated image in `out\` |
| **`Edit Plaques (GUI).bat`** | Open the click-editor to add/remove plaques by hand, then save |
| **`Batch Plates (CSV per plate).bat`** | Measure a whole folder → one CSV per plate + `summary.csv` |
| **`Original Plaque Size Tool (1 plate).bat`** / **`(batch).bat`** | The exact **Published** (citable) engine |
| **`Compare Turbidity.bat`** | Cross-phage optical-density turbidity, clarity, titer, figures |
| **`Precise Detect (best engine).bat`** | The best detector (PST + PlaqSeg YOLO) |
| **`Add Scale Bar.bat`** | Stamp a physical "5 mm" scale bar onto a photo |
| **`Plaque Toolkit (app).bat`** | Launch the desktop app from source |

There is also a **`Plaque Toolkit (all versions)\`** hub with an interactive HTML readme that
builds the exact command for you.

---

## The four detection engines

This is the core concept. Pick the engine for the job; only one is citable.

| Engine | What it is | Validation status | Use it for |
|---|---|---|---|
| **Published** | The exact Trofimova & Jaschke 2021 algorithm, byte-for-byte. | **Peer-reviewed & validated.** The only citable mode. Reproduces the literature within ~0.04 mm. | Numbers that go in a paper. |
| **Current** | Same algorithm + bug-fixes + a corrected dish/calibration (picks the roundest large contour so the dark surround can't hijack the mm scale) + non-truncated values. | In-house. Differs from Published only by ≤ ~0.04 mm / count unchanged on the bundled plates. | Routine day-to-day measuring (the **default**). |
| **Sensitive** | Current with the size gates lowered to catch sub-0.4 mm plaques. | **In-house, not validated.** Higher recall **but more false positives** — verify by eye. | Finding tiny plaques; exploratory counts. |
| **Precise** | PST dish + calibration → artifact masks → **PlaqSeg YOLO** primary → density switch → gated PST-sensitive recall → union; optional learned plaque-vs-texture classifier gate. | **In-house, not validated;** PlaqSeg itself is not peer-reviewed. | The best detector on dense, countable plates. |

Full detail, including *why* ImageJ and the published ViralPlaque macro fail on these
top-lit iPhone plates: [**docs/ENGINES.md**](docs/ENGINES.md).

---

## Documentation map

| Doc | What's inside |
|---|---|
| [**docs/USER_GUIDE.md**](docs/USER_GUIDE.md) | How to do each task: measure, edit, batch, compare turbidity, scale bars, outputs, troubleshooting. |
| [**docs/ENGINES.md**](docs/ENGINES.md) | The four detection modes in depth: how each works, when to use it, and its validation status. |
| [**docs/INSTALL.md**](docs/INSTALL.md) | Install on Windows / macOS / Linux: the two installers, run-from-source, and the optional Precise environment. |
| [**docs/PUBLICATION.md**](docs/PUBLICATION.md) | The honest validation playbook: what to validate, how (Fiji ground truth, Bland-Altman/ICC, plate-level stats, negative control), and what to write in Methods. |
| [**docs/DEVELOPER.md**](docs/DEVELOPER.md) | File map, the two-env vs unified-env design, the ML classifier, and how to rebuild the installers. |
| [**docs/STRUCTURE.md**](docs/STRUCTURE.md) | Every top-level file/folder mapped to its purpose. |
| [**docs/PLAQUE_SIZE_TOOL.md**](docs/PLAQUE_SIZE_TOOL.md) | Focused reference for the core `plaque_size_tool.py` size CLI. |
| [**docs/CREDITS_AND_LINEAGE.md**](docs/CREDITS_AND_LINEAGE.md) | Every upstream tool/model/dataset/library, its licence, and what's original here. |
| [**docs/VALIDATION_RESULTS.md**](docs/VALIDATION_RESULTS.md) · [**docs/PAPER_METHODS.md**](docs/PAPER_METHODS.md) | The local validation numbers, and paste‑ready Methods/Results text. |
| [**LICENSING.md**](LICENSING.md) · [**THIRD_PARTY_LICENSES.md**](THIRD_PARTY_LICENSES.md) | Per‑build licensing and every bundled component's licence. |
| `docs/STATS_EXPLAINED.html`, `docs/TOOL_ATLAS.html`, `docs/guide.html`, `docs/setup_and_run.html` | Interactive/visual HTML guides. |

The original upstream Plaque Size Tool manual (install via pip, Colab link, original CLI
options) is preserved at [**docs/UPSTREAM_README.md**](docs/UPSTREAM_README.md).

---

## What it measures

| Quantity | Where |
|---|---|
| Plaque **area** (px² and mm²) and **diameter** (px and mm) | every engine |
| Plaque **count** | every engine |
| **Brightness** inside each plaque (`MEAN_GRAY`, 0–255) | every engine |
| **Turbidity** — within-plate clarity index (`TURBIDITY_REL`) | size tool & GUI |
| **Turbidity** — absolute optical density (OD) + clarity class | Compare Turbidity tool |
| **Titer (PFU/mL)** | Compare Turbidity tool |
| **Per-phage statistics + box/histogram figures** | Compare Turbidity tool |

mm values require the dish diameter (`-p`, e.g. `100`). Without it you still get pixel values.

---

## Citation

If you use this for published work, cite the underlying validated tool, and describe any
in-house extensions you used (and your own validation of them) in your Methods — see
[PUBLICATION.md](docs/PUBLICATION.md).

> Trofimova E, Jaschke PR. *Plaque Size Tool: An automated plaque analysis tool for
> simplifying and standardising bacteriophage plaque morphology measurements.* Virology.
> 2021;561(April):1–5. doi:10.1016/j.virol.2021.05.011

The upstream source is at <https://github.com/ellinium/plaque_size_tool>.

If you use the **Precise** engine (Full build), also cite **OnePetri**, whose dataset/model lineage
it derives from:

> Shamash M, Maurice CF. *OnePetri: accelerating common bacteriophage Petri dish assays with
> computer vision.* PHAGE. 2021. doi:10.1089/phage.2021.0012

## Large files (contributors)

This repo already contains some large binaries (test-plate `.tif` images and model
weights `.pt`, tens of MB each). To keep the repo from growing further, **new** large
assets should be added via **[Git LFS](https://git-lfs.com/)** or attached as **GitHub
release assets** rather than committed as ordinary blobs:

```bash
git lfs install          # once per machine
# *.tif, *.tiff, *.heic and *.pt are already routed to LFS in .gitattributes,
# so any new/changed file matching those patterns is tracked automatically.
```

Existing history is intentionally left untouched (no rewrite), so already-committed
files stay as they are — this only changes how *future* large files are stored.

## License

**Free and open for everyone** — see **[LICENSING.md](LICENSING.md)** for the details, and
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for every bundled component.

- Our own source code is **Apache‑2.0** ([LICENSE](LICENSE)), building on the peer‑reviewed
  **Plaque Size Tool** (also Apache‑2.0).
- The **Light** installer (`PlaqueToolkitSetup.exe`) is entirely permissive — **Apache‑2.0, free for
  any use including commercial.**
- The **Full** installer (`PlaqueToolkitFullSetup.exe`) adds the **Precise** engine, which is built on
  **Ultralytics YOLO (AGPL‑3.0)** and **PlaqSeg/classifier weights trained on the OnePetri dataset
  (CC BY‑NC‑SA 4.0, NonCommercial)**. It is therefore **free for non‑commercial research use** under
  AGPL‑3.0 with the model weights under CC BY‑NC‑SA 4.0. For commercial use, use the Light build (or
  see [LICENSING.md](LICENSING.md)).

Attribution: Plaque Size Tool (Trofimova & Jaschke 2021), OnePetri (Shamash & Maurice 2021),
Ultralytics YOLO, Qt/PySide6, and the libraries listed in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
