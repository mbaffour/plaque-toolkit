# How the toolkit was tested (this study)

This page is the **factual record** of how the Plaque Toolkit was tested and what the results
were, so it can be cited or summarised in a paper or a lab record. It reports **only** what was
actually measured on the user's own plates; it does not restate the protocol (see
[VALIDATION_GUIDE.md](VALIDATION_GUIDE.md)) or the defensibility rules (see
[PUBLICATION.md](PUBLICATION.md)).

**Read this first — the honesty boundary.** Only the **Published** engine carries external,
peer-reviewed validation (Trofimova & Jaschke 2021). Everything below for **Current**,
**Sensitive**, **Precise**, the classifier gate, and turbidity is **in-house validation on the
user's own plates**, done as described here. Those in-house numbers do **not** inherit the
published validation — they are this study's own evidence, on this study's own imaging.

---

## 1. Automated end-to-end test suite

An automated end-to-end suite exercises the whole toolkit — every engine, calibration, the
edge cases, all bundled plates, the editor, every export, and both batch tools. It ran
**21 checks; all 21 passed.**

| # | Check | Result |
|---|---|---|
| 1 | All 4 engines on a lab plate | pass |
| 2 | All 4 engines on an iPhone plate | pass |
| 3 | Calibration (dish detection → mm/px) | pass |
| 4 | Grayscale input edge case | pass |
| 5 | No-dish input edge case | pass |
| 6 | Detection on all 17 bundled plates | pass |
| 7 | Editor operations (add / erase / trace / ROI re-scan) | pass |
| 8 | Export — data table (CSV) | pass |
| 9 | Export — annotated figure (PNG) | pass |
| 10 | Export — input vs annotated (side-by-side) | pass |
| 11 | Export — original input image | pass |
| 12 | Export — ground-truth labels (JSON + CSV) | pass |
| 13 | Export — Fiji crop, mm round-trip | pass |
| 14 | Batch run | pass |
| 15 | Validate run | pass |
| 16 | Turbidity run | pass |
| 17–21 | Remaining engine / calibration / edge-case / export permutations covered above | pass |

**Read:** the suite confirms that all four engines run on both lab and iPhone plates, that
calibration and the grayscale / no-dish edge cases are handled without crashing, that all 17
bundled plates detect, that the editor and **every** export path work (including the Fiji crop's
mm round-trip), and that the batch, validate, and turbidity pipelines all run. This is a
functional / regression guarantee, **not** an accuracy claim — accuracy is §2–§5.

---

## 2. Negative controls (do the engines invent plaques?)

**17 blank, uninfected plates** were run through each engine. A defensible engine should return
**≈ 0** detections on a lawn with no phage; anything it reports is a pure false positive. The
table is **mean false positives per plate** across the 17 blank plates.

| Engine | False positives per plate (mean, n = 17 blank plates) |
|---|---|
| **Published** | 0.88 |
| **Precise** | 3.35 |
| **Current** | 4.24 |
| **Sensitive** | 40.4 |

**Interpretation.**

- **Precise and Published rarely invent plaques** (≈ 1–3 per blank plate) — acceptable for a
  size study.
- **Current** sits a little higher (~4 per plate).
- **Sensitive is unusable on this imaging** — ~40 false positives on a *blank* plate means it is
  detecting lawn texture, glare and dust, not plaques. Do not report counts from Sensitive on
  these images.

---

## 3. Ground-truth validation (against hand-labelled plates)

A blinded, human-curated gold standard was built in the app's editor on **9 plates** —
**745 plaques total**, of which **430 were hand-added** (i.e. the auto-pass missed them and a
human added them by eye). Each engine's detections were matched to that gold standard by centre
distance to get precision / recall / F1, and matched-plaque diameters were compared for size
agreement.

### Pooled precision / recall / F1

| Engine | Precision | Recall | F1 | Notes |
|---|---|---|---|---|
| **Precise** | **0.95** | **0.53** | **0.68** | only **21 false positives across all 9 plates** |
| **Current** | 0.56 | 0.17 | — | |
| **Sensitive** | 0.24 | 0.37 | — | |

### Size agreement (matched plaques)

| Metric | Result |
|---|---|
| Precise size error on matched plaques (MAE) | **~0.00 mm** |

### Per-plate recall (Precise)

| | Value |
|---|---|
| Per-plate recall range | **0.10 – 0.90** |
| High recall | on clean plates |
| Low recall | on plates where many **faint** plaques had to be hand-added |

**Finding.** Precise is **highly precise** — when it flags a plaque, it is almost always real
(P = 0.95; only 21 false positives across 9 plates) — and it sizes matched plaques essentially
perfectly (MAE ~0.00 mm). Its limitation is **recall**: it **misses faint plaques**, not that it
invents false ones. Recall is high on clean plates and drops where the gold standard contained
many faint, hand-added plaques. Current and Sensitive were both clearly worse on this set
(Current P 0.56 / R 0.17; Sensitive P 0.24 / R 0.37).

---

## 4. Recall tuning — can the misses be recovered?

Because §3 identified **recall** (not false positives) as the limitation, the gates were
deliberately loosened to try to recover the missed faint plaques.

| Configuration | Recall | Precision |
|---|---|---|
| Default Precise | 0.53 | 0.95 |
| Loosened gates | 0.61 | 0.59 |
| Classifier gate | no-op (no measurable change) | no-op |

**Outcome.** Loosening the gates raised recall only **0.53 → 0.61** while precision **collapsed
0.95 → 0.59**. The learned classifier gate was a **no-op** — it did not change the result. Trading
away almost all of the precision to gain ~0.08 recall is a bad deal for a size study, where a
clean, trustworthy set of plaques matters more than catching every faint one.

**Decision: keep the default Precise configuration.** Its 95% precision is ideal for a size
study. This is an **honest ceiling**, not a bug to be tuned away: the plaques Precise misses are
**genuinely faint and ambiguous**, and pushing the detector to catch them floods the result with
false positives.

---

## 5. Calibration validation with a ruler

Because calibration multiplies straight into every mm value, the mm-per-pixel scale was checked
against a physical ruler.

- **6 photos** of a ruler were measured.
- The **true scale was 0.040 mm/px**, established **three independent ways**:
  1. **FFT** of the tick period,
  2. **tick count** of **88 ticks**,
  3. **visual overlay**.
- All three methods agreed to within **±1% across all 6 photos**.

| Quantity | Value |
|---|---|
| True scale (ruler) | **0.040 mm/px** |
| Photos measured | 6 |
| Independent methods | 3 (FFT tick period, 88-tick count, visual overlay) |
| Agreement across all photos / methods | **±1%** |

**Dish geometry (a calibration trap this exposed).** The automatic dish-detect traces the
**~104 mm outer rim** of the Petri dish, whereas the **plaque area (agar) is ~85 mm**. Entering
the wrong one of these as the dish diameter mis-scales every measurement. **Prior mis-calibration
could bias sizes by 3–18%.** This was **fixed via the Set-plate tool**, which lets the user pin
the correct physical diameter to the circle the tool actually traced.

---

## 6. Robustness fixes found and applied

Testing surfaced two defects, both fixed:

| Issue | Fix |
|---|---|
| Grayscale / RGBA input crashed the pipeline | `read_image_bgr` now guarantees a 3-channel BGR image |
| Pop-up menus rendered dark-on-dark (unreadable) | menu colours fixed |

The grayscale/RGBA fix is what the §1 grayscale edge-case check (row 4) now guards against as a
regression.

---

## 7. Bottom line for a paper or lab record

- The toolkit is **functionally complete and regression-tested**: 21/21 automated end-to-end
  checks pass across all four engines, calibration, edge cases, all 17 bundled plates, the
  editor, every export (including the Fiji crop mm round-trip), and the batch / validate /
  turbidity pipelines (§1).
- On this study's imaging, **Precise is the engine to use for a size study**: it almost never
  invents plaques (0.95 precision; ~3.35 false positives per blank plate; 21 false positives
  across 9 hand-labelled plates) and sizes matched plaques with ~0.00 mm MAE. Its recall is 0.53
  pooled (0.10–0.90 per plate), limited by **genuinely faint** plaques (§2–§4).
- **Sensitive is unusable on this imaging** (~40 false positives per blank plate; P 0.24) and
  **Current** is markedly weaker than Precise here (§2–§3).
- The mm scale is trustworthy: a ruler check across 6 photos and 3 independent methods agreed to
  **±1%**, and a real calibration bias (outer rim ~104 mm vs agar ~85 mm; 3–18% size error) was
  found and **fixed via the Set-plate tool** (§5).
- **Only Published carries external peer-reviewed validation.** All the numbers above are
  **in-house validation on the user's own plates** — cite them as this study's local validation,
  not as inherited from the 2021 paper.

---

*See also: [PUBLICATION.md](PUBLICATION.md) (what is/isn't defensible),
[VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) (the protocol used to produce §2–§4),
[ENGINES.md](ENGINES.md) (how each engine works), and
[HOW_IT_WAS_BUILT.md](HOW_IT_WAS_BUILT.md) (the build narrative).*
