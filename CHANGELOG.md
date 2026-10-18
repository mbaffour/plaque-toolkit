# Changelog

All notable changes to the Plaque Toolkit. The version lives in `_version.py`
(one source of truth — see `AUDIT-2026-09.md`, PT-13).

**Honesty policy for this file.** Any release that changes a *measurement number*
says so explicitly, under a "Numbers that change" heading, naming the engine and
the conditions. A release with no such heading changed no number.

---

## Unreleased — the 2026-10 audit (branch `claude/audit-2026-10`)

A second audit, this time of the desktop app, the statistics packages, the Precise/ML
engine, the web app, packaging and every document, plus a fresh pass over the engines.
Every change is traceable to a finding in [`AUDIT-2026-10.md`](AUDIT-2026-10.md)
(PT-23 … PT-85). Before any change, v1.1.0 was frozen in
[`releases/v1.1.0/`](releases/v1.1.0/MANIFEST.md) and every fix was checked against it:
**every `data-green-*.csv` in every engine mode, and every turbidity measurement file, is
byte-identical to v1.1.0 on the bundled plates.**

### Numbers that change

None of these touches `plaque_size_tool.py --published` output.

* **Turbidity, 16-bit input (PT-27).** Detection now runs on the same 8-bit conversion
  `plaque_size_tool.py` uses, so both tools find the same plaque set on a 16-bit TIFF
  (1.1.0 could differ by 10 plaques on one plate; 1.0.x matched). 8-bit input is unchanged.
* **Turbidity with `--blank` plus `--flat`/`--dark` (PT-28).** The flat/dark correction is
  applied to the blank in its own frame before alignment; previously it cancelled out of
  every OD whenever the blank dish was not exactly where the sample dish is. Blank-only and
  lawn-relative runs are unchanged.
* **Desktop app, Batch tab, Published (PT-33).** No longer runs the engine with `-small`
  unless the new "Small plaques" box is ticked; Batch Published now equals the Measure tab
  and the CLI cell for cell (it differed on every bundled plate).
* **Desktop app and editor, Published `DIAMETER_MM` (PT-30).** Uses the Published rounding
  (diameter from the 2-dp area), as the CLI does: 0.01 mm on about 3 % of plaques.
* **Precise (PT-36).** PlaqSeg boxes cut by an internal tile edge are dropped (they
  double-counted a plaque straddling a seam and added a spurious small diameter).
  `PLAQSEG_KEEP_EDGE=1` restores the old behaviour.
* **Statistics (PT-41, PT-42, PT-44).** LONG files with several metrics now require
  `--value <metric>` (they were pooled across metrics); Welch's ANOVA + Games–Howell replace
  ANOVA + Tukey when Levene rejects equal variances; grouped control comparisons are
  Holm-adjusted within each group (raw p kept as `p_raw`).

### Output files that change (columns added, no cell changed)

* `summary.csv`: `MM_CALIBRATED`; plates in natural order (`Plate_2` before `Plate_10`);
  dish-less plates show blank mm cells instead of averaged zeros.
* `qc.csv`: `NATIVE_MAX`, `FULL_SCALE`, `FLAT_APPLIED`, `DARK_APPLIED`; with
  `--dilution`/`--volume-ul` also `PFU_PER_ML_CI95_LO/HI` and `COUNT_IN_RANGE_30_300`.
* `run_metadata.json`: `run_id`, `n_failed`, `previous_runs`, per-image `error`.
* `summary_<tag>.json` (Precise): `settings`, `yolo`, `library_versions`, `toolkit_version`.
* `pairwise`/grouped CSVs: `p_raw`; agreement stats: `ba_slope`, `ba_slope_p`,
  `loa_ci_halfwidth`.

### Added

* `plaque_size_tool.py -o/--out`; `summarize_plates.py -r/--recursive` (also reads the
  app's `data_<plate>.csv` and the Batch tab's `out_batch/<plate>/`); `--order` on
  `compile_excel.py`, `plot_sensitive_violin.py`, `make_figure.py` (PT-22); `--no-small` on
  `measure_samples.py`, `run_viralplaque.py`, `add_scale.py`; `run_viralplaque.py --plate`.
* The Batch tab's "Small plaques" checkbox.
* Provenance (`run_metadata.json`) from the editor's Save and the app's Export all, with
  `edited: true` when hand edits are present.
* `tests/test_audit_2026_10.py`: 32 regression tests (85 in total).
* `releases/v1.1.0/`: the frozen record of the previous release and its outputs.

### Fixed

* Same-named images in different sub-folders of a `-d` batch no longer overwrite each
  other (named `<subfolder>__<stem>` on collision); the same for turbidity plate labels.
* A corrupt file no longer aborts a `-d` batch: it is recorded in `run_metadata.json`, the
  rest is measured, and the run exits non-zero. Provenance is flushed after every image and
  earlier runs in the same folder are kept under `previous_runs` instead of overwritten.
* `-p 0` / `-p 90mm` are rejected (they produced all-zero mm columns / a traceback).
* Every walker skips the toolkit's own output folders and files (a second run ingested
  `out/out_<plate>.tif` as a plate).
* Turbidity: a named `--dark`/`--flat` that cannot be read stops the run (it used to drop
  both silently and record them as applied); references of another size are fitted per
  plate (mixed-size folders crashed); zero-plaque runs write header-only CSVs (the app's
  Compare tab raised on the 1-byte files); the console no longer reports "polarity passed"
  in lawn-relative mode; `FRAC_SATURATED` is per channel; `--dilution < 1` is rejected
  (it is the reciprocal factor); a Sensitive measurement earlier in the app session no
  longer leaks its size gates into a "Published" turbidity batch.
* `cv2.imwrite` failures (non-ASCII paths on Windows) can no longer pass silently: a
  checked writer encodes with the same encoder and raises if the file is not written.
* App: Precise never shows another engine's plaques under its label; Orient works on an
  `out/<stem>_oriented.png` copy so exported labels validate (they scored 0 % recall);
  the pasted-Fiji parser takes the value, not the row number; "Compare vs Fiji" on an
  uncalibrated plate uses pixel diameters instead of 0 mm; an editor error can no longer
  leave the Measure tab locked; the frozen build no longer launches itself as "python".
* Editor: a drag released over a button no longer adds a plaque; Undo restores the
  Sensitive state as well as the plaques.
* Statistics: groups with one plate report "n/a" instead of crashing or "ns"; a Tukey p
  that underflows to 0 is significant in bracket selection; the two-group sentence quotes
  plate means ± SEM when the test ran on plate means; the browser app's replicate selector
  no longer defaults to the group column; "p 0.958" → "p = 0.958".
* Agreement: columns are matched by whole tokens and never the same column twice (the
  CLI compared the **area** columns in a "diameters" report on the repo's own validation
  file); the chosen pair is always printed; proportional bias and limits-of-agreement
  confidence intervals are reported.
* Precise: engine globals are restored after its PST passes; the smoke gate writes to a
  temp folder (it wrote inside the `.app` that was then uploaded); `run_precise.py`
  explains a missing `plaqseg` env instead of a raw `ModuleNotFoundError`.
* Packaging: the macOS bundle ships the licence texts and reads its version from
  `_version.py` (it said 1.0.0); installers say 1.1.0; `pip install .` includes
  `provenance.py` and the other run-time modules; `pillow-heif` and `openpyxl` declared.
* `label_store`: ids cannot collide (digest in the id, refuse to overwrite); stored labels
  keep the image's name and digest, not the user's absolute path.
* Web app: temp folders are purged between requests.
* Helper scripts: `run_viralplaque.py` records a failed/timed-out ImageJ run as
  `count = None` with a note (not 0) and no longer hard-codes a 100 mm dish;
  `measure_samples.py` flags a dish-less plate `NO DISH` and keeps errors in their own
  column; `compile_excel.py` / `plot_sensitive_violin.py` give a clear message on an empty
  tree; `scalebar.py` relabels a bar it had to shorten; `heic_to_tiff.py` honours EXIF
  orientation and no longer claims the engines cannot read HEIC.
* Documentation: the real test suite is described (not "21 checks"); `PUBLICATION.md`
  describes the test rule the code uses; `TURBIDITY_REL` is defined correctly in the HTML
  guides; the Precise ground truth is reported from the 9-plate scoring in `validation/`
  (precision 0.95, recall 0.53), and the engine-vs-itself sizing claim is relabelled; the
  de-dup rule, the dish rule, the classifier default, the seven app tabs, the version
  citations and the `qc.csv` columns are stated as the code has them.

### Known issues / owner decisions

See `AUDIT-2026-10.md` → "Owner decisions": the release bump, `TURBIDITY_REL` (PT-17),
the sRGB luma order (PT-80), the negative-control figures (PT-63), the weights licence
(PT-68/PT-16), the web app's deployment pin, and the still-open items from 2026-09
(PT-1 default flip, PT-7 table date, PT-8, PT-12 column rename).

---

## 1.1.0 — 2026-10-13

The 2026-09 audit release. Every change below is traceable to a finding in
[`AUDIT-2026-09.md`](AUDIT-2026-09.md).

### Numbers that change

* **Turbidity OD on 16-bit input (PT-2).** `plaque_turbidity.py` used to truncate a
  16-bit linear TIFF to 8 bits and then apply an inverse-sRGB gamma unconditionally.
  Such input is now read at native depth and linearised according to what the file
  actually is, which corrects errors of **0.53–0.89 OD**. Runs on ordinary 8-bit
  sRGB photographs are unaffected. Any previously recorded OD from a 16-bit linear
  capture should be re-measured.
* **Agreement report wording (PT-4).** The "paste-ready" manuscript sentence is now
  derived from the statistics instead of hard-coding "closely agreed / highly
  correlated". Reports whose statistics did not support the old adjectives now read
  differently. No statistic changed — only the sentence describing it.

**No size-measurement number changes in this release.** `plaque_size_tool.py`'s
default (Current) and `--published` outputs are byte-for-byte identical to 1.0.x on
the bundled `Test_plates` set, in both modes; this was verified by diffing every
`data-green-*.csv` against the pre-audit code.

### Added

* `--upstream-exact` on `plaque_size_tool.py` (PT-1): a bit-for-bit reproduction of
  the *original* upstream read path — red-channel `ImageStat` brightness gate, lossy
  temp-file dimming, no EXIF transpose — for reproducing a number the upstream tool
  itself produced. Implies `--published`. Opt-in; the Published default is unchanged
  and the decision to flip it belongs to the maintainer (see AUDIT-2026-09.md →
  "Owner decisions"). Documented in `docs/UPSTREAM_EXACT.md`.
* `run_metadata.json` beside every size CSV (PT-9), written by the new
  `provenance.py` from both `plaque_size_tool.py` and `app/batch_measure.py`:
  engine name, the settings used, toolkit version, library versions, and a per-image
  digest, count, brightness and mm/px. Purely additive — no measurement column moved.
* A real automated test suite (`tests/`, pytest) covering PT-1 through PT-6 and PT-9,
  plus a `Tests` GitHub Actions workflow that runs it and `--smoke` (PT-7, partial).
* `find_python.bat` (PT-5): runtime interpreter resolution for every Windows launcher.
* `_version.py` (PT-13): the single source of truth for the version.

### Changed

* Zero-plaque plates now always write a header-only CSV and stay in `summary.csv`
  with `N_PLAQUES = 0` (PT-3). Previously they wrote nothing and vanished from the
  summary, biasing every mean count and titer upward and silently defeating the
  negative-control protocol.
* `--precise-smoke` is a gate that can actually fail (PT-6): it now requires
  `n_final >= PRECISE_SMOKE_MIN` (default 1) *and* that the overlay was written, and
  exits non-zero otherwise. `build_macos.sh` checks both the exit status and the
  verdict line.
* Every launcher resolves Python at run time instead of hard-coding the author's own
  `C:\Users\...` path (PT-5).
* Versions reconciled to `1.1.0` across `pyproject.toml`, `setup.py`, `app/__init__.py`,
  the engine modules and `CITATION.cff` (PT-13). `pyproject.toml` gained a real
  `[project]` table.
* `plaque_turbidity.py`'s `run_metadata.json` now reports the toolkit version that
  produced the data rather than a stale hand-maintained module string (PT-9/PT-13).
* The matplotlib floor is `>=3.9` in `requirements.txt` and `environment.yml` too, not
  just in `pyproject.toml`/`setup.py` (PT-10). On 3.5–3.8 the turbidity comparison
  plots raised `TypeError` inside a broad `except` and were silently skipped while the
  run still reported success.

### Also in this release (landed on `main` after v1.0.6, before the audit)

These changes predate the audit and are not covered by the audit's measurement-identity
check above. None of them touch `plaque_size_tool.py` or `plaque_turbidity.py` (verified with
`git log -- plaque_size_tool.py plaque_turbidity.py`).

* **Analyze tab**: an in-app, publication-grade plotting workbench.
* **`plaque_stats`**: a grouped control-comparison mode (second factor vs a control), case-insensitive
  column auto-detection with a warning when replicate == subgroup, per-violin *n* and
  mean/median value labels (toggleable), and the stats/comparison guides surfaced inside the
  running tools. The standalone (no-Python) build now bundles `GUIDE.html`, and the launchers
  free their port before starting.
* **Agreement tool** (`plaque_stats/agreement`): tool-vs-manual method comparison with rigorous
  agreement statistics, a browser app, download-all, built-in area→diameter conversion,
  legible regression equation and line keys on both panels, and clean p-value formatting
  (`p < 0.001`). The real *n* = 100 tool-vs-Fiji dataset and a tiny-plaque check (*n* = 20) are
  archived under `validation/` with regenerated figures and reports; the sub-0.5 mm
  resolution floor is documented.
* **Web app** (`webapp/`): a browser measurement app (Precise engine online) with a Hugging Face
  Spaces deploy.
* **Labelling pipeline** (`labelling/`, `label_store.py`): app export → ingester → training store,
  a Fiji helper, and docs; the Full build bundles `label_store` so the installed app auto-files
  ground truth.
* **Docs and citation**: classifier-training methodology (OnePetri + LOO/hard-negative loops),
  genuinely educational interactive HTML guides, PlaqSeg (Carbon16/PlaqSegDesktop `app-v0.2.1`)
  cited as the Precise engine's detector, and co-author Jolene Ramsey (PI) added to
  `CITATION.cff` and `.zenodo.json`.
* **Privacy**: the author's sample plate photos were removed from the repository. This rewrote
  the public history, so the `v1.0.1`–`v1.0.6` tags are not ancestors of `main`.

### Known issues

See `AUDIT-2026-09.md` for the full disposition of all 22 findings, including the
ones deliberately left open (PT-8, PT-11, PT-12, PT-14 through PT-22) and the
maintainer decisions that are not the toolkit's to make.

---

## 1.0.x and earlier

Not tracked in this file. See the git history and `docs/HOW_IT_WAS_BUILT.md`.
