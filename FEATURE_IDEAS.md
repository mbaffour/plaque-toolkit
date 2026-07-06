# Feature ideas

A short, prioritised list of concrete, high-value additions for the Plaque Toolkit.
These are **proposals**, not yet implemented — each is scoped to build on machinery that
already exists in the repo (so it stays low-risk and additive) and is written so a
contributor can pick one up without further discovery.

The guiding constraint is the repo's honesty policy (see `README.md` and
`docs/PUBLICATION.md`): anything that changes a **measurement** must stay out of the
citable **Published** engine. All ideas below are reporting / QC / workflow features that
sit *around* detection and never alter the validated numbers.

---

## 1. Per-plaque QC / uncertainty flag in the CSV

**What.** Add a `QC_FLAG` column (and a short `QC_REASON`) to the per-plaque output written
by `plaque_size_tool.save_data()` (`plaque_size_tool.py:249`, cols list) and the GUI's
`save_results()` (`plaque_gui.py:425`). Each plaque gets an at-a-glance quality tag such as
`OK`, `EDGE` (touches the dish rim / image border), `TINY` (below the size gate — only
present in Sensitive), `MERGED?` (very high area vs. median → likely two plaques), or
`LOW_CONF` when the optional plaque-vs-texture classifier
(`_research/clf/infer.py`, `prob_plaque`) scored it near the decision threshold.

**Why.** The toolkit already computes most of the inputs (area, the dish contour, and a
classifier probability) but throws the confidence away — the CSV only records the accepted
plaques. A per-row flag lets a user sort a plate by "needs a look" instead of eyeballing
every plaque, and directly supports the validation workflow in `docs/PUBLICATION.md`
(review the flagged ones, trust the rest). It is purely additive: an extra column, no
change to any measured value, so **Published** mode stays byte-for-byte identical if the
column is left blank there.

**Rough scope.** New helper `qc_flags(df, plate, lawn, clf=None)` returning two columns;
append them to the DataFrame before `to_csv`. ~1 small module + 2 call sites.

---

## 2. Cross-plate summary export with plaque-count uncertainty

**What.** Extend `summarize_plates.py` (currently mean/median/min/max of diameter + area
per plate) with (a) a **titer column** when a dilution factor / plated volume is supplied,
(b) a count **confidence interval** (Poisson/`sqrt(N)` on the raw count is the standard for
plaque assays), and (c) an optional `--format xlsx` writer alongside the existing `summary.csv`
so non-CSV users get a formatted workbook (the repo already ships `compile_excel.py`, so the
Excel dependency and style are established).

**Why.** `summarize_plates.py:17` already aggregates the per-plate CSVs but stops at raw
size stats. Titer (PFU/mL) and a count CI are the two numbers a phage biologist actually
reports, and adding them at the *summary* layer keeps detection untouched. Reusing
`compile_excel.py` avoids a new dependency.

**Rough scope.** ~30 lines in `summarize_plates.py` for the CI + optional titer columns;
reuse `compile_excel.py` for the `--format xlsx` branch.

---

## 3. Calibration presets manager

**What.** A tiny JSON store (e.g. `~/.plaque_toolkit/presets.json`) of named
calibration/detection profiles — dish diameter in mm, engine (Published / Current /
Sensitive / Precise), sensitive size gates, watershed on/off — with a dropdown in the GUI's
Measure tab and a `--preset NAME` flag for the CLIs. Ship 2–3 built-ins (e.g.
`90mm-standard`, `iPhone-topLit`, `tiny-plaques`).

**Why.** Dish size and engine choice are re-entered on every run today (`--plate`,
`--sensitive`, etc. in `measure_samples.py:56` and the GUI controls). Labs that always shoot
the same plate format want to set it once. A preset only bundles *existing* parameters —
it changes nothing about how any engine computes numbers, so it's low-risk and doesn't touch
the validated path.

**Rough scope.** A ~40-line `presets.py` (load/save/list JSON), one dropdown + save button
in `plaque_gui.py`, and a `--preset` argument that pre-fills the existing flags in the CLI
entry points.

---

## 4. Batch folder processing with a manifest + resume

**What.** Give `measure_samples.py` a plain "drop a folder, get one row per image" mode
that (a) writes a `manifest.csv` recording input path, engine, preset, mm/px, count, run
timestamp, and status per image, and (b) **skips images already present in the manifest**
so an interrupted 200-plate run can resume instead of restarting.

**Why.** `measure_samples.py` already walks sample subfolders and writes `SUMMARY.csv`
(`measure_samples.py:87`), but it re-does everything on every invocation and assumes the
`<root>/<SAMPLE>/<photo>` layout. A flat-folder + resumable mode is the workflow most users
reach for first, and a manifest makes a large batch auditable (which engine/preset produced
which row). Additive: it's a new code path next to the existing one.

**Rough scope.** A manifest reader/writer + an `--resume` flag and a flat-folder branch in
`measure_samples.py`. ~50 lines, no change to `measure_one()`.

---

## 5. Negative-control / blank-plate check

**What.** An optional `--control IMAGE` (or a "Blank plate" slot in the GUI) that runs the
selected engine on a phage-free plate and reports how many "plaques" it detects. If the
count is above a small threshold, surface a warning in the summary and stamp a
`control_false_positives` column.

**Why.** `docs/PUBLICATION.md` explicitly asks users to validate with a negative control;
right now that has to be done by hand. Wiring it into the same run makes the false-positive
rate a first-class output and reinforces the toolkit's honesty framing — a strong,
low-effort differentiator for a portfolio piece. It reuses the detection call unchanged and
only *reports*, so it can't affect measured values.

**Rough scope.** One extra detection call on the control image + a threshold check and a
warning line in the summary. ~25 lines.

---

### Priority

1. **#1 QC / uncertainty flag** — highest value-per-line; leans on data already computed.
2. **#2 summary export (titer + CI)** — the numbers biologists actually report.
3. **#4 batch manifest + resume** — biggest workflow win for large runs.
4. **#3 calibration presets** — nice ergonomics, purely bundles existing params.
5. **#5 negative-control check** — small, and directly reinforces the validation story.
