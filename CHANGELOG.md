# Changelog

All notable changes to the Plaque Toolkit. The version lives in `_version.py`
(one source of truth — see `AUDIT-2026-09.md`, PT-13).

**Honesty policy for this file.** Any release that changes a *measurement number*
says so explicitly, under a "Numbers that change" heading, naming the engine and
the conditions. A release with no such heading changed no number.

---

## Unreleased — click-through 2026-11 (branch `claude/clickthrough-2026-11`, on top of 1.3.0)

Six testers used the apps the way a user would (desktop Measure/Batch/Compare, desktop Analyze,
the Python web apps, the R Shiny app, the statistics engine, detection) and reported about 150
findings; fixers then worked through them one area at a time, each fix with a regression test
that fails on the old code. This entry grows as each area is merged. `plaque_size_tool.py`
default and `--published` CSVs and the turbidity `plaques_all.csv` / `per_phage.csv` stay
byte-identical to the frozen v1.1.0 baseline (`releases/v1.1.0/run_baseline.sh`).

### Numbers that change

* **Titer 95 % interval (`qc.csv`: `PFU_PER_ML_CI95_LO` / `_HI`; Compare tab).** These columns
  did not exist in 1.1.0; the unreleased audit build computed them as n ± 1.96·√n. They are now
  the exact (Garwood) Poisson limits, which are wider and asymmetric at low counts (a plate with
  0 plaques gets an upper limit instead of 0–0). `PFU_PER_ML` itself is unchanged.
* **R Shiny app, unequal spread.** With **Variances: auto** (the new default control) the app
  runs Welch ANOVA + Games-Howell when Levene's test rejects equal variances, as the Python
  engine does; before, it ran classic ANOVA + Tukey regardless. Choose **equal** to get the old
  test. Data read with decimal commas (`1,5`) are now read as 1.5, not 15.
* **R Shiny app, statistical unit.** A file with no plate column, or UPPER-CASE headers, used to
  be tested per plaque while the report said "per plate". The unit is now detected
  case-insensitively and the report names the unit that was actually tested.
  A sample with a single plate no longer switches the whole analysis to per-plaque statistics:
  the plate stays the unit, that sample's comparisons are n/a, and the omnibus test covers the
  samples that can be tested (as in the Python engine).
* **Statistics engine (`plaque_stats.py`), test choice with 8 or more plates per sample.** When
  the plate means look normal but Levene's test rejects equal variances, **auto** now runs Welch
  ANOVA + Games-Howell; before, it switched to Kruskal-Wallis. Below 8 plates per sample (the
  usual case) nothing changes, and the shipped example gives the same p-values and summary
  numbers as before (`tests/test_ct_r1_stats_engine.py::test_gate_*`). The R app follows the
  same rule.
* **Statistics engine, files that were read wrongly.** Sample names such as `None`, `NA`, `nan`,
  `007`, `1.0` or `phage #3` used to be dropped, renamed or cut at the `#`; they are now kept as
  typed, so analyses of such files gain the samples they were missing. `--unit replicate` on a
  file without a plate column used to test plaques while saying "plate"; it is now an error. A
  sample with a single plate no longer switches the whole analysis to per-plaque statistics:
  the plate stays the unit and that sample's comparisons are n/a.
* **Statistics engine, effect-size label.** For Kruskal-Wallis, `epsilon_squared` now holds
  H/(N−1); the value that used to be under that name is reported as `eta_squared_H`.
* **Desktop app, engines Current and Sensitive: plaque sizes and the mm scale.** (Published in
  the app and on the command line, the command-line default, and Precise are unchanged.)
  * The app used to run these two engines with the small-plaque threshold only, which outlines
    any plaque wider than about 50 px roughly 30 px too small, and outlines a plaque that has a
    dark centre and a paler halo at the dark centre. A new **Plaque size** choice (Auto /
    Standard / Small; Auto is the default) runs both thresholds and gives every plaque the
    standard (halo) edge where it can: the standard outline where the standard pass finds the
    plaque; touching halos divided between their plaques (`SOURCE` = `split`, flag `SPLIT`);
    plaques only the small pass finds added as they are. A haloed plaque whose halo could not be
    separated keeps its dark-centre outline and is flagged **`CORE?`**; a split piece that
    overlaps its neighbours too much to size within 5 % is flagged **`NO_SIZE`**. Both are
    **counted but left out of every size summary** (the Measure median and mean, Batch
    `median_diam_mm` / `mean_diam_mm` with a new `n_sized` column, and what the Analyze tab
    imports), and the app says "sizes from N of M plaques". Old app → Auto, plaques / plaques
    sized / median: `sample.tif` 42 / 42 / 2.81 mm → 41 / 21 / 5.93 mm; Plate_6 96 / 96 /
    1.87 mm → 89 / 62 / 3.16 mm; Plate_8 27 / 27 / 3.89 mm → 27 / 22 / 5.39 mm (the
    command-line default gives 5.97, 3.79 and 5.57 mm on 16, 48 and 19 plaques). Choose
    **Small** for the old behaviour. The ±5 % rule comes from a sweep of 168 synthetic plates
    (`validation/split_sweep/`); the halo thresholds were set on the bundled plates and have
    not been validated on other images, and whether the halo or the dark centre is the right
    edge for a given phage is the experimenter's call.
  * The dish, and so the mm scale, now comes from the standard pass. On four bundled plates the
    old dish was a threshold halo 4–5 % too wide (Plate_8, 11, 14, 17), so every mm size on them
    grows by about that much; Plate_2, which had no dish, now gets one.
  * In Small mode a plaque that was outlined twice (core and halo) is counted once (Plate_6:
    96 → 89 plaques).
  * Detections whose centre lies outside the dish are dropped and counted in the flag line
    (none on the bundled plates).
  * `TURBIDITY_REL` is relative to the clearest plaque on the plate, so it moves when Auto adds
    plaques.
* **Fiji agreement, ICC 95 % interval.** The interval is now the exact McGraw & Wong F interval
  instead of a bootstrap, which was too narrow at small n (83–90 % coverage at 5–10 pairs). On the
  shipped validation file (n = 100): 0.963–0.982 → **0.949–0.986**. No interval is given below
  5 pairs. The ICC itself (0.974), r, CCC, the bias (−0.028 mm) and the 95 % limits of agreement
  (−0.146 to +0.089 mm) are unchanged.
* **Fiji agreement, interval of the limits of agreement.** Bland & Altman's 1999 standard error
  replaces the √(3/n) approximation: half-width 0.0206 → 0.0204 mm on the shipped file.
* **Fiji agreement, pasted columns.** A header such as `AREA_MM2`, a row-number column, `.62`,
  `1,234.5` or a non-numeric line used to shift or change the pairs without notice; they are now
  read correctly or refused with the line named.
* **QC flags.** A round plaque that is only large is flagged `LARGE?`; `MERGED?` is for a shape
  far from round (low solidity or an elongated outline). `EDGE` is measured against the lawn
  edge (0.93 of the dish radius), so it now fires for plaques at the rim. New flags `NESTED`
  (an outline inside another) and `BRIGHT` (brighter than its surroundings: a bubble or glare,
  not a plaque). `TINY` now means an outline under 12 px across (too few pixels for a reliable
  size), not "found only by the small pass" (the `SOURCE` column says that). Batch
  `per_plate.csv` gains `n_split` and `n_core`. No measurement column changes.

### Desktop app: Compare and Batch tabs

* Compare no longer crashes the app on macOS (the worker threads get a 16 MB stack; the 512 KB
  default overflowed under matplotlib), and an engine error or a bad folder shows a message
  instead of closing or hanging the window. Inputs are checked before a run starts (folder
  contents, dilution ≥ 1, volume > 0, both titer boxes or none).
* Compare shows a per-plate table (count, PFU/mL with its 95 % interval, countable 30–300),
  removes its own stale figures before drawing new ones, and draws histograms on shared bins
  with plain-language axis labels. Figures and their **legend keys** are written as PNG, SVG and
  PDF, with **Legend key…**, **Place key on figure** and **Open output folder**.
* Batch numbers plaques top-to-bottom like the Measure tab, lists images in natural order
  (`plate2` before `plate10`), shows whole counts and blanks instead of `nan`, reports
  `file: reason` for every image it could not read, and adds `n_edge` / `n_overlap` /
  `n_merged` per plate.
* The turbidity QC overlay labels each plaque with its `PLATE_INDEX` from `plaques_all.csv`.

### Desktop app: Measure tab

* One export path: the CSV, the figure and the provenance record all use the engine flags of the
  result on screen and the editor's current calibration. Edited results say `(edited)`.
* One figure style for the canvas and the saved figure, a **Labels** choice (numbers, numbers +
  mm, none), a **legend key** with **Place key on figure**, and PDF/SVG saves.
* Leaving unsaved edits asks first; calibration can be undone; redo and Ctrl+Z work; a failed
  open keeps the previous image; Precise shows "(not installed)" when it is not.
* Pixel mode works without a mm scale; Add/Draw are guarded at the image edge; the image fits
  the view after a resize; small windows scroll instead of overlapping.
* The QC column has tooltips and a tint, and `LARGE?` (see above).

### Desktop app: Analyze tab

* **Export everything (ZIP)** contains exactly the samples, order, 2nd-factor tags, colours and
  statistics shown on screen. Sample names such as `None`, `NA`, `007` or `phage #3` no longer
  close the app or vanish from the ZIP (before, the ZIP could report a different test and
  p-value from the screen).
* The **Legend key…** button works when clicked.
* **Save study / Load study** reproduce the study exactly (names as typed, sample order, empty
  plates and samples); the tab asks before replacing or closing an unsaved study; its own Long
  export loads.
* **Imported plate files** need a diameter-in-mm column, or you choose the column (µm / px
  columns are never offered); semicolon files and decimal commas are read; JSON, binary files
  and diameters ≤ 0 are refused; an empty file becomes a zero-plaque plate only if you confirm.
* Plates are numbered plate1, plate2… within each sample (the file name is kept as the source);
  plates can be renamed, samples reordered, and adding the same measured plate twice asks first.
* New **Variances** (Auto / Equal / Unequal-Welch) and **Compare** (All pairs / vs one sample,
  Dunnett) options; Brackets offers **Letters**; Median offers only IQR, 95 % CI or none; log Y
  with values ≤ 0 explains itself and offers to hide them.
* Statistical warnings (for example a sample with one plate) appear next to the result; the
  Summary shows plate-level mean, SD and SEM; a sentence under the figure says what the bar,
  whisker, n and N are; the Report lists the test choice, power, plate-to-plate variation and
  any rows left out.
* The palette colours the plates; controls with no effect in the current mode are greyed;
  "Transparency" is now "Opacity".
* Figures save at the chosen size with one DPI for every format; a typed extension wins and
  names with dots keep them. Errors clear on the next action; a failed analysis removes the old
  results; the figure is no longer squeezed into a second scroll box.

### Detection in the desktop app (`plaque_gui.py`, Measure / Batch / Validate)

* **Plaque size: Auto / Standard / Small** on the Measure and Batch tabs (replaces Batch's "Small
  plaques" box). Changing it marks the result on screen as out of date. The table's `SOURCE`
  column says which pass found each plaque; `run_metadata.json` records the choice. On the
  command line the same code is opt-in: `--multiscale` gives exactly the app's Auto result
  (same plaques, `SOURCE` values and, with `--qc`, flags; ignored, with a note, under
  `--published`). The shared code is the new `plaque_scales.py`; the default command-line run
  never loads it.
* `pip install` now includes `plaque_qc` and `plaque_scales` (without them `--qc` and
  `--multiscale` failed outside a checkout); `tests/test_packaging_modules.py` checks that every
  module the command-line tools import is packaged.
* **Dish warnings.** The app and the command line say when the dish looks wrong (far smaller than
  the image, far off-centre, or more than 2 % cut off by the frame) instead of silently reporting
  millimetres from it. Warnings go to the flag line / stdout and `run_metadata.json`, never
  into a CSV.
* **Precise** reports `n_outside_roi` and `max_det`; its two-environment runner honours
  `PLAQSEG_WEIGHTS` and `PLAQSEG_IMGSZ`. Which plaques Precise keeps, and its mm scale, are
  unchanged.
* The app's Published path is pinned by a fixture recorded before these changes
  (`tests/fixtures/ct_r1_published_app_pin.json`: three bundled plates and `sample.tif`).

### Fiji agreement, Validate and Help (desktop tabs, `agreement.py` CLI)

* **Pasted columns** are read line by line (headers, row numbers, decimal commas, one-line
  lists); unequal lists are refused with both counts; a preview shows the pairs as read.
* **One sentence everywhere.** The desktop tab, the CLI and the web app build the paste-ready
  sentence from the same code, including the proportional-bias statement and the interval of
  the limits. Below 20 pairs the report adds a 95 % prediction interval for one new difference;
  the limits of agreement themselves stay bias ± 1.96 SD at every sample size.
* **Legend key** for the agreement figure (Legend key…, text starter, Place key on figure; key
  files beside each CLI figure), one colour for points within the limits, and the figure no
  longer changes after other plots have been drawn.
* A note explains an ICC interval that is wide because the two methods differ by a systematic
  offset. Identical or constant columns and fewer than 3 pairs are refused in plain words.
* **Compare vs Fiji** aligns pixel-unit Fiji results (scale searched from 0.005× to 200×), reads
  tab and semicolon tables and XM/YM headers, and will not save a match of fewer than half the
  plaques.
* **Validate** scores only plaque label files, lists unusable ones as failed with the reason,
  disables Precise when it is not installed, and gains **Save results (CSV)…** and a paste-ready
  sentence.
* Result tables show 4 significant digits (p as `< 0.001`); copy and sort use the full values.
* **About** lists all seven tabs; Help documents' table-of-contents and cross-document links work.
* Agreement CLI: an unknown `--tool` / `--manual` column is a one-line message listing the
  numeric columns.

### Statistics engine and CLI (`plaque_stats/plaque_stats.py`)

* **Reading files.** Labels are kept exactly as typed; comma, semicolon and tab files and decimal
  commas are read; every dropped row is counted and reported ("N rows dropped: reason"). A
  mistyped `--order` or `--value` name is an error instead of a silently smaller analysis.
* **New options.** `--equal-var auto|yes|no` (Welch ANOVA + Games-Howell on request),
  `--posthoc dunnett --control NAME` (each sample against one control, with simultaneous 95 %
  intervals), `--equivalence-margin` (TOST), `--annotate letters` (compact letter display),
  `--log-y-drop-nonpositive`. `--no-box` is removed (it did nothing).
* **Every report now says more.** The pairwise table adds the difference with its 95 % interval
  and Hedges' g; a power sentence says what difference the design can detect and how many plates
  a given difference needs; one line gives the share of variance that lies between plates; the
  post-hoc test is named; the "Test choice" paragraph is written from what actually ran.
* **Spread note** (same rule and wording as the R app): no warning from the raw SD ratio; a
  neutral note under 5 plates per sample on the classic path; a warning only when a
  Bonferroni-adjusted F test on the extreme pair is significant.
* **With `--center median`** the error bar is IQR or a bootstrap 95 % interval of the median
  (seeded, resampling plates); median with SD or SEM is refused with a plain message.
* **Figures.** The n label reads "n = 70 plaques / N = 3 plates". With more than 5 samples the
  automatic annotation is one row of stars above each sample for its comparison with the first
  sample (marked "ref."; the caption and the report say so, and how many pairs are in the
  table) instead of a stack of brackets; `--annotate all` / `adjacent` keep bracket lines. Tick
  labels tilt when they would collide; titles and captions wrap; log axes get plain-number
  ticks and a sane lower limit, and refuse values ≤ 0 unless told to drop them (the count is
  then stated). A key with many rows goes below the plot in several columns and the saved
  figure grows taller than the chosen height, so the plot keeps its size.
  **The default figure changed**: plate points take their colours from the chosen palette
  (Okabe-Ito by default) instead of a fixed plate palette, and when colours run out the marker
  shape changes so no two plates look alike. When a palette has fewer colours than samples the
  repeats get a hatch (violins) or another marker (points) and the report says so. The shipped
  3-sample example renders byte-identically before and after the many-sample changes.
* The power sentence never advises fewer than 3 plates per sample and is marked as a rough
  guide.
* **Legend key.** Fixed colour words for every shipped palette; the text starter ends with what
  the violins, points, bar and whisker are, what the brackets, stars or letters mean and the
  star thresholds with the test's name; `make_figure.py` still runs without the key module.
* Errors the engine raises for bad input are `StatsError` (a `ValueError`), so an app that
  embeds the engine can show them instead of exiting.

### Python web apps (`plaque_stats/app_py.py`, `plaque_stats/agreement/app_py.py`)

* A second file with different columns, an unreadable file or an unusual one shows a plain
  message instead of ending the session; a failed upload clears the old results. Semicolon files
  and decimal commas are read, and a line under the upload says how the file was read and how
  many rows were used.
* **Statistics app.** A LONG file with UPPER-CASE headers is no longer analysed with all its
  metrics pooled; "per plate" without a plate column is refused; Replicate "(none)" means none.
  Samples are picked and ordered from a list of the names in the data (a typo can no longer
  drop a sample). New **Variances**, **Compare to** (Dunnett) and **Brackets** (including
  letters) controls; median offers only IQR, CI or none; a box hides values ≤ 0 on a log axis.
  A status line under the figure says which test ran, on what, with n, and what the bar and
  whisker show. The preview is exactly the PNG download; the ZIP matches the screen and
  includes the input file, a dated report and no server paths.
* **Agreement app.** Every figure has a **legend key** download, a legend text starter and one
  **Place key on figure** switch; the key files are in the ZIP. Diameter columns are chosen
  first; area columns are labelled as areas in mm² unless converted (before, the shipped
  validation file loaded as area against area but was labelled "plaque diameter (mm)"); id
  columns are never guessed as measurements. The same column twice, too few pairs or identical
  columns give a plain message; the ICC interval reads "n/a (needs 5 pairs)" when it cannot be
  computed. The "Both" preview is readable at 1024 px and on a phone.

### R Shiny app (`plaque_stats/app.R`)

* **Variances** control (auto / equal / unequal) with Welch ANOVA + Games-Howell; Mann-Whitney,
  n = 1 groups and star thresholds now match the Python engine.
* **Spread note.** No warning from the raw SD ratio. When classic ANOVA + Tukey ran with fewer
  than 5 plates in any group, a neutral note says the equal-spread assumption cannot be checked;
  a warning appears only when a Bonferroni-adjusted F test on the extreme pair is significant.
* Files: semicolon and tab delimiters, decimal commas, cp1252, UPPER-CASE headers; empty,
  header-only, binary and `.xlsx` files give a plain message instead of a blank app; the number
  of dropped rows is reported.
* **The default figure changed** (deliberately): the mean/median line is drawn, brackets sit
  above the data and clear of the n labels, points take their sample's colour when there are no
  replicates, the jitter is seeded so points do not move between redraws, PNGs have a white
  background under the key, and a log axis says how many non-positive values it dropped.
* Paste-ready sentence quotes plate means ± SEM with the test, the post-hoc and exact p;
  the Statistics tab has formatted p-values and a **Download statistics** button.
* Paper style: the status line says what was applied and what was ignored; a style that names
  none of the loaded samples changes nothing.
* Legend key: plates get unique colour + shape pairs (24 tested); two samples never share a
  colour. Known limits: a PDF asked for in a font the PDF device lacks falls back to the default
  sans and says so; a key too large for the figure is not placed and the app says so (the
  stand-alone key is complete).
* `Run R App.bat` installs `jsonlite` and `zip`.
* **Same answer in R and Python.** `tests/test_ct_r1_parity.py` runs the R app's statistics and
  the Python engine on 8 data sets × 9 option combinations and requires the same test, the same
  unit and the same p-values (omnibus to 1e-6, pairwise to 1e-5).

---

## 1.3.0 — unreleased: paper style for the R Shiny app (branch `claude/paper-style`, on top of 1.2.0)

The R Shiny app (`plaque_stats/app.R`) reads the `paper_style.json` that CFU Plot Studio 0.4.0
writes, so one style file gives every figure of a paper the same strain colours and font. See
README → "One style for the whole paper (R Shiny app)". **No measurement or statistic
changes**: this release touches the R app's figure styling only, and with every input at its
default the figure is byte-identical to 1.2.0 (`tests/test_paper_style.py` renders the default
violin, the composed figure with the key, the coloured/framed variant and the stand-alone key
files with the 1.2.0 `app.R` and with this one, in separate R processes, and compares the SVGs
byte for byte).

* **Colours keyed by sample NAME.** A per-session colour registry (`extend_colour_registry()`,
  `registry_colours()`, the same semantics as CFU Plot Studio) replaces the positional palette
  in `style_map()`: loading another CSV keeps every name's colour and gives a new name the first
  colour of the current theme no other name uses; choosing another theme or typing custom hex
  reassigns the loaded names in level order (names not loaded keep theirs). The legend key and
  text starter follow, as they are built from the same map.
* **Font family and the shared look.** New sidebar inputs **Font** (Default sans, Arial,
  Helvetica, Times New Roman, Serif, Custom…), **Base font size**, **Axis colour** and **Axis
  line width**, threaded through `theme_classic()`, the n row, the significance brackets
  (`stat_pvalue_manual(..., family =)` reaches `geom_bracket`), the key placed on the figure and
  the key files, so figure and key share one font and size. `resolve_font_family()` checks a
  named font with systemfonts and falls back to the default sans when the machine lacks it; the
  app says so once (notification) and in the status line.
* **Paper style on start.** `paper_style_path()`: `CFU_PAPER_STYLE` if set, else
  `paper_style.json` beside `app.R`. Read after the first flush with jsonlite through an explicit
  allowlist: `font_family`/`font_family_custom` → Font, `font_size` → Base font size,
  `axis_color` → Axis colour, `axis_line_width` → Axis line width, `sample_palette` → merged
  into the registry by name (names the data lacks are kept; the violins are then coloured by
  sample even under the grey SuperPlot default). `title_size`, `time_palette`, `plot_title`,
  `legend_position`, `x_angle`, `download_width`, `y_min`, … are ignored. The status line says
  `Paper style: <path>, saved <when>` or `No paper style (looked for <path>)`; an unreadable file
  says so and applies nothing. `plaque_stats/paper_style.json` is git-ignored.
* Tests: `tests/test_paper_style.py` drives `tests/r_paper_style_check.R` (shiny::testServer;
  skipped without R or the app's packages, as the legend key test is): byte-identical defaults
  vs commit 176656b (skipped with a note when the commit is absent), name-keyed colours across
  two files, the Times New Roman fixture, a fixture asking for a font this machine lacks, and no
  file at all. Fixtures in `tests/fixtures/` are real CFU Plot Studio 0.4.0 output.
* Not yet: the Python front-ends (`plaque_stats.py`, `app_py.py`, the Analyze tab) do not read
  the paper style.

---

## 1.2.0 — unreleased: legend key (branch `claude/legend-key`, on top of the 2026-10 audit)

Every figure that colours its samples, plates or phages now ships a **legend key**: a
stand-alone key image (same formats as the figure; names stay text in SVG/PDF), a
**legend text starter** sentence, and a **Place key on figure** switch. See README →
"Legend key". **No measurement or statistic changes**: this release touches figure export
and annotation only. `plaque_stats` (the statistics engine) goes to 1.1.0.

* One helper, `plaque_stats/legend_key.py`, draws the stand-alone key, the on-figure key
  and the text starter. Each figure builds its key from the same colour dict it is drawn
  from and carries it (`fig.legend_key`), so callers never hold a copy.
* Figure changes (appearance only): the violin SuperPlot's in-plot legend is now the key,
  so when the violins are coloured by sample (or there are no plates and the points carry
  the sample colour) the samples are listed too; with grey violins and plates (the default)
  it is the same plate legend as before. In the Analyze tab the old "legend" checkbox is now
  "Place key on figure", beside Save figure. The grouped plot's key matches its marks when
  there are no replicates (translucent points, no outline).
* R Shiny app (`plaque_stats/app.R`): the key replaces ggplot's plate legend (placed beside
  the plot by "Place key on figure"). Fixed on the way: with violins coloured by sample AND
  plates, the plate fill scale silently replaced the sample colours of the violins (two
  `scale_fill_manual` calls); each violin is now drawn in its own mapped colour, and more
  than nine plates recycle the plate palette instead of erroring.

### Every figure, and whether it has a key

| Figure | Where it is made | Encodes samples/groups? | Key |
|---|---|---|---|
| Violin SuperPlot | `plaque_stats.plot_violin` — Analyze tab (screen, Save figure, ZIP), Plaque Stats CLI, Plaque Stats web app (`plaque_stats/app_py.py`) | samples (violin / point colour), plates (plate-mean colour) | **yes** — button, text box, switch; files in every bundle |
| Grouped control-comparison plot | `plaque_stats.plot_grouped` — same three places | 2nd-factor values (colour), control marked | **yes** |
| Sample violin figure | `make_figure.py` | samples (violin colour) | **yes** — `--legend-key`, `--key-on-figure` |
| Overlaid histograms `hist_<metric>.png` | `plaque_turbidity.write_plots` — CLI batch and Compare turbidity tab | phages (bar colour) | **yes** — always written in the batch output; text starter in the tab |
| Box plots `compare_<metric>.png` | `plaque_turbidity.write_plots` | no — one style, the phage is the x label | none needed |
| Sensitive-mode violin | `plot_sensitive_violin.py` | no — every violin the same blue, samples are x labels | none needed |
| Stats / pairwise table images | `plaque_stats.save_stats_table`, `save_pairwise_table` | no — tables | none needed |
| Fiji agreement (method comparison + Bland–Altman) | `app/agreement.py` (Fiji agreement tab), `plaque_stats/agreement/agreement.py` (CLI + web app) | no samples — point/line classes (within/outside limits, bias, ±1.96 SD) already have their own in-figure key | none needed |
| Annotated plates, side-by-side comparison | `plaque_gui.annotate_plaques` / `save_figure` / `save_comparison`, editor export, `plaque_size_tool` `out_*` images, web app (`webapp/app.py`) download, Precise overlays, dish-check JPEGs | no samples — outline colour marks auto vs manual detection on a single plate | none needed |
| Editor canvases | `plaque_gui` editor, `app/canvas_editor.py`, `app/plaque_canvas.py` | interactive, not exported figures | none needed |
| R Shiny app violin | `plaque_stats/app.R` (ggplot2) | samples (violin colour), plates (plate-mean colour) | **yes** — the R twin of the helper inside `app.R` (`style_map` → `key_entries` → `key_plot` / `text_starter`); Legend key download (ZIP of PNG/SVG/PDF + text), text starter with Copy, Place key on figure |

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

* **Precise, dense plates (PlaqSeg cap).** The detector kept at most 300 boxes per tile call
  (an ultralytics default); the cap is now 1,000 (`PLAQSEG_MAX_DET`). Counts on tiles with more
  than 300 candidate plaques can rise. Found on the VACVPlaque benchmark.
* **Precise, blue-lawn plates.** The blue pen-label mask is ignored when it would cover more than
  30 % of the dish (it is then the lawn colour); phage plates with a small pen label are unaffected.

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
* **Per-plaque QC flags** (`plaque_qc.py`): `EDGE` (touches the image border or dish rim),
  `MERGED?` (far larger than the plate's median, or irregular), `TINY` (only exists because of
  `-small`/`--sensitive`), `OVERLAP`, `LOW_CONF` (Precise classifier score). Opt-in on the CLI
  (`plaque_size_tool.py --qc` adds `QC_FLAG`/`QC_REASON`; the default CSV is unchanged) and always
  present as `QC_FLAG` in the app's table, `data_<plate>.csv` and the Batch tab's `all_plaques.csv`.
* Provenance (`run_metadata.json`) from the editor's Save and the app's Export all, with
  `edited: true` when hand edits are present.
* `tests/test_audit_2026_10.py`: 32 regression tests (85 in total).
* `releases/v1.1.0/`: the frozen record of the previous release and its outputs.
* `validation/benchmarks/`: an external benchmark on the public VACVPlaque dataset (converter,
  YOLO training-set exporter, results), `PLAQSEG_WEIGHTS` / `PLAQSEG_IMGSZ` / `PLAQSEG_MAX_DET`
  overrides so alternative or fine-tuned detector weights run through the unchanged pipeline, and
  a `DIAMETER_PXL` column in the Precise CSV. See `validation/benchmarks/vacvplaque_benchmark.md`.

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
