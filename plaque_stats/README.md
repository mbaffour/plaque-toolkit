# Plaque Stats & Violins

A small, self‑contained package for turning plaque measurements from **different samples** into
**publication‑ready, reproducible, customizable violin plots** plus **statistics and data
summaries**. It ships two front‑ends that read the **same data format** and give the **same numbers**:

- **`plaque_stats.py`** — a Python script/CLI (batch, scriptable, reproducible).
- **`app.R`** — an interactive R‑Shiny app (point‑and‑click, live preview, downloads).

It is built around the correct experimental design for plaque data: **the plate is the experimental
unit**, so by default the statistics are computed on **per‑plate means** (this avoids
pseudoreplication — treating hundreds of plaques from a few plates as if they were independent).

---

## 1. The data format (put your data in one of these)

**One row per plaque.** A tidy CSV (or TSV/Excel). There are two accepted shapes — pick whichever is
easier for you; both tools auto‑detect which one you gave them.

### Format A — WIDE  *(recommended; it's basically the app's per‑plaque export + two label columns)*

```csv
group,replicate,diameter_mm,area_mm2,turbidity
T4,plate1,2.34,4.30,0.12
T4,plate1,2.51,4.95,0.08
T4,plate2,2.20,3.80,0.10
T7,plate1,1.80,2.54,0.62
lambda,plate1,3.10,7.55,0.30
```

### Format B — LONG  *(one file can hold several metrics)*

```csv
group,replicate,metric,value
T4,plate1,diameter_mm,2.34
T4,plate1,diameter_mm,2.51
T7,plate1,diameter_mm,1.80
T4,plate1,turbidity,0.12
```

### The columns

| column | required? | what it is | example |
|---|---|---|---|
| **`group`** | **required** | the sample / condition / phage you are comparing — the x‑axis categories | `T4`, `T7`, `lambda`, `WT`, `mutant` |
| **`replicate`** | **strongly recommended** | the **plate** (biological/experimental unit). With it, stats are computed **per plate**; without it, plaques are pooled and you'll get a pseudoreplication warning | `plate1`, `2026‑07‑01_A` |
| **`value`** | LONG only | the number to analyse | `2.34` |
| **`metric`** | LONG only | which measurement each `value` is (lets one file hold diameter + area + turbidity) | `diameter_mm` |
| *numeric columns* | WIDE | any measurement columns (`diameter_mm`, `area_mm2`, `turbidity`, …); you pick which to plot | `2.34` |

> **Coming from the Plaque Toolkit?** Its per‑plaque CSV already has `AREA_MM2`, `DIAMETER_MM`,
> `TURBIDITY_REL`, etc. To use it here: add a **`group`** column (the phage/sample) and a
> **`replicate`** column (the plate/photo), then stack the per‑plate files into one CSV. Rename to
> lower‑case (`diameter_mm`) or just pass `--value DIAMETER_MM`.

A ready‑to‑copy **`TEMPLATE.csv`** and two worked **`example_data_*.csv`** files are in this folder
(regenerate them any time with `python plaque_stats.py --make-example`).

---

## 2. What you get

For each run (both tools produce the same things):

- **A violin plot in the _Violin SuperPlot_ style** (Lord *et al.* 2020, *J Cell Biol*; Kenny &
  Schoen 2021, *Mol Biol Cell*) — the convention used in current top‑journal papers: a soft,
  **neutral‑grey violin** for the distribution, individual **plaque points coloured by plate**, the
  **plate means as large outlined markers**, and the summary drawn as **mean ± SEM of the plate
  means** (the value the statistics actually use). **No boxes.** Colour‑blind‑safe, minimal
  Nature‑style axes (only left/bottom spines), and fully customizable.
- **`summary_by_group.csv`** — n plaques, n plates, mean, SD, SEM, 95% CI, median, Q1/Q3, IQR,
  min/max, CV%.
- **`summary_by_replicate.csv`** — the per‑plate means (what the stats use).
- **Statistics** — an omnibus test + pairwise post‑hoc (see §4), with effect sizes.
- **`report.md`** — a plain‑language summary **and a paste‑ready Methods/Results sentence**.
- **`run_config.json`** — every setting + package versions, for reproducibility.

*(All output files are suffixed by the metric — e.g. `report_diameter_mm.md`,
`violin_diameter_mm.png` — so analysing several metrics into one folder never overwrites. Reading
`.xlsx` needs `openpyxl`; `.csv` needs nothing extra.)*
- Figures export as **PNG (300 dpi), SVG and PDF** — SVG/PDF keep text **editable** in
  Illustrator / Inkscape.

---

## 3. Running it

### Python (`plaque_stats.py`)

```bash
pip install -r requirements.txt        # pandas numpy matplotlib scipy (+ optional tabulate, openpyxl)

# make the example/template files
python plaque_stats.py --make-example

# analyse: compare diameter across groups, using the plate as the unit
python plaque_stats.py example_data_wide.csv \
    --group group --value diameter_mm --replicate replicate \
    --out results --title "Plaque diameter by phage"
```

Common options (everything is also settable from a JSON `--config`):

| flag | meaning |
|---|---|
| `--value diameter_mm` | which measurement to analyse (WIDE) / which `metric` (LONG) |
| `--replicate replicate` | the plate column (omit if you truly have no replicates) |
| `--unit auto\|replicate\|plaque` | statistical unit (default `auto` → per‑plate when replicates exist) |
| `--parametric auto\|parametric\|nonparametric` | force a test family (default `auto`, chosen from normality + Levene) |
| `--order T4,T7,lambda` | x‑axis order |
| `--palette "#0072B2,#E69F00,#009E73"` | custom colours |
| `--annotate auto\|all\|adjacent\|none` | which pairs get significance brackets |
| `--violin-fill auto\|neutral\|group` | violin fill (default `auto`: neutral grey in SuperPlot mode) |
| `--formats png,svg,pdf,tiff` | which figure formats to write |
| `--title / --ylabel / --xlabel / --width / --height / --dpi / --log-y / --no-points / --no-box / --theme` | figure customization |

### R‑Shiny (`app.R`)

```r
# first time only:
install.packages(c("shiny","ggplot2","dplyr","tidyr","readr","DT","rstatix","ggpubr","scales","svglite"))

# then, from the folder that contains plaque_stats/:
shiny::runApp("plaque_stats", launch.browser = TRUE)
# (or open app.R in RStudio and click "Run App")
```

Upload your CSV (or click **Load example data**), pick the `group` / `replicate` / value columns,
toggle the options, and **download** the figure (PNG/SVG/PDF) and the summary/stats tables. The
**Data format** tab restates the format above.

---

## 4. The statistics (and why plate‑level)

The **plate is the experimental unit**, so by default every test runs on **per‑plate means**, not on
individual plaques (pooling plaques is *pseudoreplication* and inflates significance). You can override
with `--unit plaque` (the report will flag it).

| situation | omnibus | pairwise post‑hoc |
|---|---|---|
| **2 groups**, ~normal | Welch's *t*‑test | — (+ Cohen's *d*) |
| **2 groups**, non‑normal | Mann–Whitney U | — |
| **>2 groups**, ~normal | one‑way ANOVA | Tukey HSD |
| **>2 groups**, non‑normal | Kruskal–Wallis | Dunn (Holm‑adjusted) |

Normality is judged per group (Shapiro–Wilk) with an equal‑variance check (Levene); `auto` picks the
non‑parametric family if either fails. Significance stars: `*** p<0.001, ** p<0.01, * p<0.05, ns`.

> The Python and R tools use the same logic and are cross‑checked to give the **same p‑values** on the
> same data.

---

## 5. Reproducibility & customization

- **Reproducible:** point jitter is seeded (`--seed`); every run writes `run_config.json` with all
  settings + `numpy`/`pandas`/`scipy` versions. Re‑running the same command reproduces the figure.
- **Customizable:** palette, group order, labels/title, show/hide points·box·mean·brackets, log axis,
  figure size and dpi, statistical unit and test family — all exposed in both tools.
- **Editable output:** SVG/PDF keep text as text for final tweaks in a vector editor.

---

## References (the visual scheme & stats)

- Lord SJ, Velle KB, Mullins RD, Fritz‑Laylin LK. **SuperPlots: Communicating reproducibility and
  variability in cell biology.** *J Cell Biol* 2020;219(6):e202001064. doi:10.1083/jcb.202001064
- Kenny M, Schoen I. **Violin SuperPlots: visualizing replicate heterogeneity in large data sets.**
  *Mol Biol Cell* 2021;32(15):1333–1334. doi:10.1091/mbc.E21‑03‑0130
- Okabe M, Ito K. *Color Universal Design* (the colour‑blind‑safe qualitative palette).

---

## 6. Files in this package

| file | what it is |
|---|---|
| `plaque_stats.py` | the Python analysis script / CLI |
| `app.R` | the R‑Shiny interactive app |
| `TEMPLATE.csv` | a blank‑ish template to copy your data into |
| `example_data_wide.csv` / `example_data_long.csv` | worked examples (3 phages × 3 plates) |
| `requirements.txt` | Python dependencies |
| `README.md` | this file |

Licensed the same way as the toolkit's permissive components — **Apache‑2.0** (only common permissive
libraries are used: pandas/numpy/matplotlib/scipy for Python; ggplot2/rstatix/ggpubr for R).
