# Agreement — tool vs manual measurements

A small, self‑contained tool for the **method‑comparison / validation** question: *do the automated
tool's measurements agree with a manual reference* (e.g. **Plaque Toolkit vs manual Fiji/ImageJ
tracing**)? It reports the standard agreement statistics and a publication figure — the same analysis
used to validate the toolkit itself (ICC 0.97).

> **Visual walkthrough (how to use + how to interpret):** open **[`GUIDE.html`](GUIDE.html)** — it has
> an interactive Bland‑Altman explainer.

## What it computes
- **Pearson r** (correlation)
- **ICC(A,1)** — two‑way random effects, *absolute* agreement (Koo & Li 2016); unlike *r*, it penalises
  systematic bias, so it's the right agreement statistic.
- **Bland–Altman**: mean **bias**, **95% limits of agreement**, RMSE, % bias, MAE.
- **Proportional‑bias** check: least‑squares slope (1.0 = the disagreement does not grow with size).
- A two‑panel **figure** (method‑comparison scatter + Bland–Altman) in **PNG / SVG / PDF** (editable
  vectors), a **stats CSV**, a **report.md** with a paste‑ready sentence + interpretation, and
  `run_config.json`.

The maths are vendored verbatim from the desktop app's `app/agreement.py`, so numbers match.

## Data format
One row per item (plaque); **two numeric columns** — the tool measurement and the manual reference:

```csv
plaque_id,toolkit_mm,manual_mm
1,0.67,0.68
2,1.14,1.19
```
Columns are **auto‑detected** (names containing *tool/toolkit/auto/precise* vs
*manual/fiji/imagej/hand/reference*) or given with `--tool` / `--manual`.

## Run it
- **Double‑click** [`Run Agreement (tool vs manual).bat`](Run%20Agreement%20(tool%20vs%20manual).bat)
  — drop your CSV on it, or run it to use the bundled example.
- **Command line:**
  ```bash
  python agreement.py --make-example          # writes example_agreement.csv
  python agreement.py example_agreement.csv --unit mm --what "plaque diameter" --out results
  # explicit columns / labels:
  python agreement.py data.csv --tool toolkit_mm --manual manual_mm \
      --label-tool "Plaque Toolkit" --label-manual "Fiji/ImageJ" --formats png,svg,pdf
  ```

## Files
| file | what it is |
|---|---|
| `agreement.py` | the analysis engine + CLI |
| `Run Agreement (tool vs manual).bat` | double‑click launcher |
| `example_agreement.csv` | a synthetic paired example (120 plaques) |
| `GUIDE.html` | interactive how‑to + interpretation guide |
| `results/` | outputs (created on first run) |

## References
- Bland JM & Altman DG (1986). *Statistical methods for assessing agreement between two methods of
  clinical measurement.* Lancet 327:307–310.
- Koo TK & Li MY (2016). *A guideline of selecting and reporting intraclass correlation coefficients.*
  J Chiropr Med 15:155–163.
