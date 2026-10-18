# Where everything is — the project map

A friendly "where do I find X" map of the whole project after all the recent work. For the
developer-oriented, load-bearing detail see [STRUCTURE.md](STRUCTURE.md); this page is the big picture.

---

## 0. The two products

| Product | What it is | Lives in |
|---|---|---|
| **Plaque Toolkit** (the app) | Measure plaque **size + turbidity** from plate photos (detect → hand-correct → export). | the repo root + `app/` + engines |
| **Plaque Stats & Violins** (the analysis package) | Turn grouped measurements into **violin SuperPlots + statistics**, and validate the tool vs manual (**agreement**). | `plaque_stats/` |

---

## 1. On a user's machine (the runnable stuff, wherever it is kept — a `Downloads/` folder in this example)

```
Downloads\
├── Plaque Size Tool\              ← THE REPO (a clone of github.com/mbaffour/plaque-toolkit; everything below is here)
├── Plaque Stats Analysis\         ← optional standalone stats workspace (a synced copy of plaque_stats/ made by
│                                     plaque_stats/sync_to_downloads.ps1) — double-click launchers,
│                                     plus  "Standalone App (no Python needed)\"  (the frozen .exe)
├── Output\                        ← the built installers, if you build them (gitignored):
│     PlaqueToolkitSetup.exe (Light) · PlaqueToolkitFullSetup.exe (Full, Precise built-in)
└── (data folders — e.g. the authors' `Plaques to measure\`, calibration plates — never in git)
```
- **GitHub:** `github.com/mbaffour/plaque-toolkit` (public) is the canonical copy; releases are tagged
  there and built by CI (see `docs/PUBLISHING_CHECKLIST.md`).

---

## 2. The repo top level (`Downloads\Plaque Size Tool\`)

```
Plaque Size Tool\
├── plaque_size_tool.py       ← THE validated engine (Trofimova & Jaschke 2021) + size CLI
├── plaque_gui.py             ← OpenCV editor + shared detect/measure/trace helpers
├── plaque_turbidity.py       ← cross-phage turbidity / OD / titer batch
├── plaque_app.py             ← desktop-app entry point (+ --uitest / --smoke self-tests)
├── app\                      ← the PySide6 desktop app (see §3)
├── precise\                  ← the Precise engine pipeline (PST ⊕ PlaqSeg + gates)
├── _plaqseg\                 ← PlaqSeg YOLO model weights + runner (external, inference only)
├── _research\                ← model training + validation history (see §5; mostly gitignored)
├── plaque_stats\             ← the stats & violin package (see §4)
├── build\                    ← PyInstaller specs + Inno Setup installers
├── docs\                     ← all documentation (see §6)
├── *.bat / "Plaque Toolkit (all versions)\"  ← double-click launchers
├── LICENSE · LICENSING.md · THIRD_PARTY_LICENSES.md · NOTICE   ← licensing
├── CITATION.cff · .zenodo.json   ← how to cite + Zenodo deposit metadata
└── Test_plates\ · Manual_images\ · plates\   ← upstream sample plates + manual figures + a drop folder
```
Utility scripts at root: `add_scale.py`, `scalebar.py`, `heic_to_tiff.py`, `summarize_plates.py`,
`measure_samples.py`, `compile_excel.py`, `make_figure.py`, `plot_sensitive_violin.py`, `plate_crop.py`,
`run_viralplaque.py`.

---

## 3. The desktop app (`app\`)

| File | Role |
|---|---|
| `ui.py` | Main window: **Measure · Batch · Compare turbidity · Analyze · Validate · Fiji agreement · About** tabs (seven). |
| `plaque_canvas.py` | The interactive editor (add/erase/trace, ROI re-scan, scale bar) + **labelling export** (`export_groundtruth` → `labels_*.json` + CSV). |
| `engine_api.py` | The one locked door to the engines (Published/Current/Sensitive/Precise). |
| `validate.py` · `agreement.py` · `fiji_*.py` | On-your-plates validation + tool-vs-Fiji agreement stats. |
| `workers.py` · `env_paths.py` | off-UI-thread detection · portable conda-env discovery. |

---

## 4. The stats & violin package (`plaque_stats\`)

```
plaque_stats\
├── plaque_stats.py           ← the stats + violin engine (shared by all front-ends)
├── app_py.py                 ← browser app (Shiny) — upload, plot, DOWNLOAD EVERYTHING (zip)
├── app.R                     ← R-Shiny app (same numbers)
├── GUIDE.html                ← interactive guide (SuperPlot how-to + pseudoreplication demo)
├── Run Analysis App.bat · Run CLI (example).bat · Run R App.bat · Make Example…​.bat
├── pyproject.toml            ← pip install → `plaque-stats` / `plaque-stats-app`
├── build_exe\                ← PyInstaller spec → the no-Python frozen app
├── data\ · results\          ← drop-zone / outputs
└── agreement\                ← tool-vs-manual method comparison (validation)
      ├── agreement.py        ← Pearson r/R², ICC(A,1)+CI, Lin's CCC, Bland–Altman, paired t
      ├── app_py.py           ← its own browser app (download everything)
      ├── GUIDE.html          ← interactive guide (Bland–Altman explainer + how-to-read)
      ├── Run Agreement (tool vs manual).bat · Run Agreement App (browser).bat
      └── example_agreement.csv · example_output.png
```

---

## 5. Training, models & labels (the ML)  →  `_research\` (+ `_plaqseg\`)

| Where | What |
|---|---|
| `_plaqseg\models\small.pt`, `nano.pt` | The **PlaqSeg** YOLO detector — external, inference only (not trained here). |
| `_research\clf\plaque_clf.pt` + `infer.py` | The **deployed classifier** (the only committed `_research` artifacts). |
| `_research\clf\` (train_clf, loop/, external/…) | Classifier **training** code + data — author-local, gitignored, not in the public repo. |
| `_research\autoresearch\`, `groundtruth\`, `autotune\`, `neg_control.py` | The FP-reduction study, ground-truth building, Precise tuning, blank-plate counting — **author-local, gitignored, not in the public repo** (the docs cite their outputs). |
| **Labels for training** | A persistent, catalogued store: **`training_data\`** (labels + image copies + `catalog.csv` + metadata). Feed it from the app (**Export ▾ → Ground-truth labels**, auto-filed), from existing `labels_*.json`, or from **Fiji** — all via **`labelling\`**. Store engine: `label_store.py` (repo root). Gitignored (your data). |
| **`labelling\`** | The three ways in + the Fiji macro/importer + launchers. See [labelling/README.md](../labelling/README.md). |

Full detail: [TRAINING_AND_MODELS.md](TRAINING_AND_MODELS.md) · [MODEL_CARD.md](MODEL_CARD.md) · [labelling/README.md](../labelling/README.md).

---

## 6. Documentation (`docs\`) — by purpose

- **Start / use:** [USER_GUIDE](USER_GUIDE.md) · [INSTALL](INSTALL.md) · [ENGINES](ENGINES.md) · interactive `*.html`
- **For a paper:** [MANUSCRIPT_METHODS_AND_AI](MANUSCRIPT_METHODS_AND_AI.md) · [PAPER_METHODS](PAPER_METHODS.md) · [VALIDATION_RESULTS](VALIDATION_RESULTS.md) · [TRAINING_AND_MODELS](TRAINING_AND_MODELS.md) · [MODEL_CARD](MODEL_CARD.md) · [PUBLICATION](PUBLICATION.md) · [PUBLISHING_CHECKLIST](PUBLISHING_CHECKLIST.md)
- **How it works / dev:** [HOW_IT_WAS_BUILT](HOW_IT_WAS_BUILT.md) · [STRUCTURE](STRUCTURE.md) · this map · [DEVELOPER](DEVELOPER.md) · [CREDITS_AND_LINEAGE](CREDITS_AND_LINEAGE.md)
- Index: [docs/README.md](README.md).

---

## 7. Quick "where do I find…"

| I want to… | Go to |
|---|---|
| Measure plaques | app (`Plaque Toolkit.bat` / installer) or `plaque_size_tool.py` |
| Make violin plots + stats | `plaque_stats\` (`Run Analysis App.bat`) |
| Validate tool vs manual (Bland–Altman/ICC) | `plaque_stats\agreement\` |
| Label plates for training | app **Export ▾ → Ground-truth labels** · or `labelling\` (Fiji / ingest) → `training_data\` store |
| Retrain the classifier | `_research\clf\` (`train_clf.py`, `loop\train_loop.py`) |
| Cite / deposit | `CITATION.cff`, `.zenodo.json`, `PUBLISHING_CHECKLIST.md §5` |
| The installers | `Downloads\Output\` |
