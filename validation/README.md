# Validation data & figures — Plaque Toolkit

The **data and figures** behind the toolkit's local validation. The full write-up, interpretation and
limitations are in [`docs/VALIDATION_RESULTS.md`](../docs/VALIDATION_RESULTS.md); this folder is the
archived, reproducible evidence.

> **Scope & honesty.** A real, single-operator **local** validation on the authors' own plates — **not**
> an independent or peer-reviewed one. Only the **Published** engine is peer-reviewed; Precise / Sensitive
> / Current are in-house and validated *here, on these plates*. Plaque **photos are intentionally not
> included** (author data); the numbers, labels and figures below reproduce every result without them.

## Primary result — Toolkit vs manual Fiji/ImageJ (n = 100)

**`paired_toolkit_vs_fiji.csv`** — 100 plaques, **sampled randomly across plates**, each measured by both
the Plaque Toolkit and by independent manual tracing in Fiji/ImageJ. One row per plaque; these are pairs
only — plaque identity/coordinates are not needed for a method comparison.

| column | meaning |
|---|---|
| `plaque_id` | row id (1–100) |
| `area_tool_mm2`, `area_fiji_mm2` | measured **area** (mm²) — the raw measurement |
| `diam_tool_mm`, `diam_fiji_mm` | **area-equivalent diameter**, `d = 2·√(A/π)` (derived from the areas) |

**Headline agreement** (reproduced from this file):

| metric | diameter | area |
|---|---|---|
| n | 100 | 100 |
| bias (Toolkit − Fiji) | **−0.028 mm** (−1.8%) | −0.069 mm² (−3.5%) |
| 95% limits of agreement | −0.146 … +0.089 mm | −0.342 … +0.204 mm² |
| **ICC(A,1)** | **0.974** | 0.973 |
| Pearson r | 0.979 | 0.978 |
| Lin's CCC | 0.974 | 0.973 |
| regression slope | 0.985 | 0.951 |

Strong agreement (ICC 0.97); a small **constant** ~1.8 % offset with no size dependence; tight limits.

### `figures/`
Regenerated from `paired_toolkit_vs_fiji.csv` with the repo's own tool
(`plaque_stats/agreement/agreement.py`), so the archived figures match the archived data exactly:

- `agreement_diameter.*` — method-comparison scatter + Bland–Altman (diameter; the headline)
- `agreement_area.*` — the same, on area
- `*_A_method_comparison.*` · `*_B_bland_altman.*` — each panel on its own
- `agreement_stats_*.csv` · `agreement_report_*.md` · `run_config_*.json` — the numbers + provenance

The same result also appears as [`docs/PlaqueToolkit_vs_Fiji_BlandAltman.png`](../docs/PlaqueToolkit_vs_Fiji_BlandAltman.png).

## Supporting — detection & sizing vs hand-labelled ground truth

`ground_truth/`:

- `labels_IMG_3907.{json,csv}`, `labels_IMG_3912.{json,csv}` — hand-corrected ground-truth plaque sets
  (schema `plaque-groundtruth-v1`; plaque positions + areas, **no image pixels**). The two dense plates
  scored in §2A of the write-up (185 + 89 plaques).
- `validate_permode.csv` — detection/sizing precision · recall · F1 · size-MAE per engine across the GT plates.
- `validate_perplate.csv` — the same, per plate.

## Reproduce

```bash
cd plaque_stats/agreement
python agreement.py ../../validation/paired_toolkit_vs_fiji.csv \
    --tool diam_tool_mm --manual diam_fiji_mm --what diameter --unit mm --out ../../validation/figures
```

…or drop `paired_toolkit_vs_fiji.csv` into the **Agreement** browser app and pick the two `diam_*` columns.
