# Using the toolkit in a publication

This page is deliberately blunt about what is and isn't defensible. Read it before you put any
number from this toolkit into a manuscript.

---

## The one thing to internalize

**Only the Published engine is a validated, peer-reviewed method.**

| Component | Validated? | Can you cite it as published? |
|---|---|---|
| **Published** engine | ✅ Trofimova & Jaschke 2021 | **Yes.** |
| **Current** engine | ⚠️ in-house; ≤ ~0.04 mm from Published, count unchanged on bundled plates | Cite the paper "with minor numerical-precision corrections," or run `--published` for an exact match. |
| **Sensitive** engine | ❌ in-house, not validated | **No** — validate it yourself first. |
| **Precise** engine (PST + PlaqSeg) | ❌ in-house; PlaqSeg not peer-reviewed | **No** — validate it yourself first. |
| **ML classifier** (`--clf`) | ⚠️ in-house; **locally validated** by the authors, not peer-reviewed | **No** — cite Published; validate on your own plates. |
| **Turbidity (OD)** | greyscale densitometry, not a separately validated assay | Report as relative optical density with the caveats below. |

If you used anything other than Published, you must **validate it on your own plates** and
report that validation. It does **not** inherit the published validation.

---

## How to validate the detection on your own plates

Do this once per imaging setup (camera, lighting, plate type) and report it.

### 1. Build a blinded manual ground truth
- Take a **representative subset** of your plates (spanning the density/clarity range).
- Have a person count and outline plaques **manually in Fiji/ImageJ**, **blind** to the tool's
  output.
- This manual set is your ground truth — the tool is measured *against* it, not the reverse.

### 2. Counts → precision / recall / F1
- Match tool detections to manual plaques (e.g. by centroid distance).
- Report **precision, recall, and F1** for each engine you intend to use (especially Sensitive
  and Precise, which trade precision for recall).

### 3. Sizes → agreement, not just correlation
- For matched plaques, compare tool vs manual **diameter/area** with a **Bland–Altman** plot
  (bias + limits of agreement) and an **ICC** (intraclass correlation).
- Correlation (r) alone is not enough — it hides systematic bias.

### 4. Negative control
- Image an **uninfected lawn** (no phage) and run it through your chosen engine. A defensible
  pipeline returns **~0 plaques** on it. This bounds your false-positive rate, which matters
  most for Sensitive/Precise.

---

## Statistics — avoid pseudoreplication

**The plate is the experimental unit, not the plaque.** Treating individual plaques as
independent replicates inflates your n and your significance.

- Use **≥ 3 plates per phage / condition**.
- Aggregate to **per-plate means** first. In the turbidity output use the **`*_PLATE_MEAN` /
  `*_PLATE_SD`** columns of `per_phage.csv`, **not** the pooled `*_PLAQUE_MEAN`.
- Compare conditions with a **non-parametric test on the per-plate means** (Mann–Whitney /
  Kruskal–Wallis), or a **mixed model with plate as a random effect**.
- The bundled analysis scripts already do this: `make_figure.py` / `plot_sensitive_violin.py`
  draw the pooled violin **plus per-plate medians** so the experimental-unit-level data is
  visible.

---

## Turbidity caveats (state these in Methods)

- There are **two different turbidity numbers** — use the right one:
  - `TURBIDITY_REL` (size tool / GUI) is a **within-plate** index (0 = clearest plaque on *that*
    plate, 1 = lawn). **Not comparable across plates.**
  - `OD` / `TURBIDITY` (Compare Turbidity tool) is an **(apparent) optical density**
    `OD = −log₁₀(I/I₀)` anchored to shared physical references (clear agar `I₀` and the lawn) —
    the comparable, publishable measure.
- `OD` is a **true absorbance only with radiometrically linear input** (camera RAW / linear
  TIFF, ideally with `--dark` + `--flat`). From tone-mapped iPhone **HEIC/JPEG** it is an
  **apparent** OD — a within-session relative measure. Use RAW/linear input for any absolute-OD
  claim.
- Check **`qc.csv`** every run: `POLARITY_OK = True` (clear plaques brighter than lawn),
  `FRAC_SATURATED ≈ 0` (no clipped pixels), `ILLUM_CV` low (use `--flat` if high).
- Turbidity is **greyscale densitometry, not a separately validated assay** — say so.

---

## Other caveats to put in Methods

1. **Plaque size is convex-hull area** — a slight *upper* bound that includes any halo
   (inherited from the published method).
2. **Image plates straight-on (orthographic).** A tilted phone shot makes the dish elliptical
   and biases the mm scale; the tool **warns** when the detected dish axis-ratio > 1.03.
3. **Apply `--watershed` uniformly** across all compared groups, or not at all.
4. **PFU counts are detected (accepted) plaques only** — confirm they fall in the countable
   30–300 range.
5. **For quantitative OD, use RAW/linear input** with `--dark` / `--flat`.

---

## Suggested Methods text

> Plaque detection and sizing used the validated Plaque Size Tool (Trofimova & Jaschke, 2021)
> [add "with minor numerical-precision corrections," or run `--published` for an exact match].
> Plates were imaged straight-on and calibrated from the detected Petri-dish diameter
> (XX mm). [If you used Sensitive/Precise:] Detections from the in-house [Sensitive/Precise]
> mode were validated against a blinded manual Fiji ground truth on N plates
> (precision X, recall Y, F1 Z; size agreement by Bland–Altman/ICC), with an uninfected-lawn
> negative control. Plaque turbidity was measured as transmitted-light relative optical density
> versus a cell-free agar reference; the plate (n = …) was treated as the experimental unit.

---

## Keep your provenance

The turbidity tool writes **`run_metadata.json`** (tool version, all settings, library
versions, and a hash of every input image). Keep it with your data — it is your reproducibility
record for the Methods.

---

## Cross-tool reality

ImageJ and the published ViralPlaque macro use **global** thresholding and **fail** on top-lit,
gradient-lit iPhone plates; only adaptive-local methods (PST) and the trained PlaqSeg model
handle them (see [ENGINES.md](ENGINES.md)). The real bottleneck for defensible numbers —
especially turbidity — is **imaging** (back-lit / even illumination), not the algorithm.
