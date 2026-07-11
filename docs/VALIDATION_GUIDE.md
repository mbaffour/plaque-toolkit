# Validation Guide — validating the Plaque Toolkit *with the toolkit itself*

This is a step-by-step, publication-grade protocol for **validating a detection engine on your
own plates, using the program's own editor and exported ground truth.** A microbiologist with no
scripting experience can follow it end to end. The output is a small table and a paragraph of
Methods text you can defend to a reviewer.

It complements [PUBLICATION.md](PUBLICATION.md) (the honesty playbook) and
[ENGINES.md](ENGINES.md) (what each engine actually does). Read those first if you have not.

---

## 0. The 90-second version

1. **Published** mode is the only peer-reviewed engine. Everything else (Current, Sensitive,
   Precise, the `--clf` classifier, turbidity OD) is **in-house and must be validated locally**
   before you report a single number from it.
2. Open each plate in the app's editor, **fix the detection by hand** (remove artifacts, add
   missed plaques), and **Export → Ground-truth labels…** to write `labels_<plate>.json` (+ `.csv`,
   schema `plaque-groundtruth-v1`). That corrected set is your **gold standard**.
3. Run each engine on the same plates, **match** its detections to your gold standard, and compute
   **precision / recall / F1** (counts) and **Bland–Altman bias + MAE + ICC** (sizes).
4. **The plate is the experimental unit.** Report **mean ± 95% CI across plates**, not pooled
   plaque totals.
5. Add a **negative control** (uninfected lawn → engine should find ≈ 0 plaques) and an
   **external cross-check** (a manual Fiji/ImageJ count on ≥ 1 clear plate).
6. Fill in the [reporting table](#7-reporting-template-copy-paste) and paste the Methods sentences.

---

## 1. Why validate, and what "validated" means here

"Validated" is not a property of this software. It is a property of **a specific engine, on your
specific imaging setup (camera, lighting, plate type, lawn), measured against a human gold
standard.** A method validated on someone else's back-lit plates is **not** validated on your
top-lit iPhone plates.

| Engine | Peer-reviewed? | May you cite it as validated? |
|---|---|---|
| **Published** (Trofimova & Jaschke 2021) | ✅ Yes | **Yes** — the only mode you may cite as a published method. |
| **Current** (default) | ⚠️ In-house; ≤ ~0.04 mm from Published, count unchanged on bundled plates | Only with the caveat "with minor numerical-precision corrections," **or** run Published for an exact match. |
| **Sensitive** | ❌ In-house | **No** — validate locally first. Higher recall, more false positives. |
| **Precise** (PST + PlaqSeg) | ❌ In-house; PlaqSeg not peer-reviewed | **No** — validate locally first. |
| **`--clf`** classifier gate | ❌ Trained on detector output, not a blinded human set | **No** — validate locally first. |
| **Turbidity OD** | ❌ Greyscale densitometry, not a separately validated assay | Report as *relative/apparent optical density* with caveats. |

**What this protocol gives you.** A defensible statement of the form: *"On N plates from our own
setup, the [Sensitive/Precise] engine achieved precision X, recall Y, F1 Z against a blinded
manual gold standard, with size bias B mm (95% limits of agreement L1–L2) and ICC C; an
uninfected-lawn control returned 0 detections."* That is publishable. "We used the Plaque Size
Tool" without that, for a non-Published engine, is not.

> **Note on the in-app scorer.** The app **exports** the gold standard (`plaque-groundtruth-v1`,
> §3). Scoring an engine against it is the defined procedure in §4. If your build has a
> **Validation** panel (point it at the labels folder, tick the engines, read the table), use it —
> it implements exactly §4. If it does not, §4.6 gives the few lines to compute the same metrics
> from the exported `.csv` files. Either way the gold standard and the metrics are identical.

---

## 2. Build the ground truth IN THE APP

This is the heart of it. You are not trusting the engine — you are **correcting** it by eye and
freezing the corrected set as truth.

### 2.1 Choose representative plates

The gold standard is only as good as the plates you pick. **Do not cherry-pick clean plates.**
Span the range you will actually report on:

- [ ] **≥ 1 sparse** plate (few, well-separated plaques) — tests false positives.
- [ ] **≥ 1 dense** plate (touching/overlapping plaques, near the countable 30–300 range) — tests
      recall and merging.
- [ ] **≥ 1 textured / awkward** plate (visible lawn texture, glare, condensation, a blue label,
      dish-rim shadow) — these are where false positives come from.
- [ ] Same camera, lighting, dish, medium, and lawn strain you will use for the real experiment.

**How many plates?**

| Goal | Plates |
|---|---|
| **Validate** an engine for reporting (this guide) | **≥ 2–3** spanning sparse + dense + textured. **≥ 3 strongly preferred** so you can form a plate-level CI. |
| **Retrain** the PlaqSeg model / classifier (out of scope here) | **~10–20**, balanced across density and texture. |

### 2.2 Open, detect, and correct each plate

Open **Edit Plaques (GUI).bat** (or the app → **Measure** tab → load the image → the editor).
Enter the **true Petri-dish diameter** in mm (e.g. `100`) so sizes calibrate — see the
[calibration pitfall](#8-limitations--pitfalls).

Work through the plate methodically. The editor toolbar:

- [ ] **Detect area** — box a region the auto-pass under-detected (faint or clustered plaques) to
      re-run detection just there and **surface missed plaques**. Do this on faint patches before
      you trust the count.
- [ ] **Remove selected** — click a false detection to select it (Shift/Ctrl+drag to **box-select**
      several), then Remove. Delete everything that is **not a plaque**: lawn texture, glare,
      bubbles, dust, the **blue label**, the **dish rim/shadow**, anything outside the lawn.
- [ ] **Add** — click a plaque the program missed to **auto-trace** it, or **drag** to draw a circle
      where auto-trace fails (very faint plaques). Add every real plaque that is missing.
- [ ] **Undo** (`u`) reverts the last change. Zoom (`+` / `–` / `Fit`, or the wheel) to judge faint
      specks honestly.

**Be conservative and consistent.** Decide your rule for "is this faint speck a plaque?" *before*
you start (e.g. "a roughly circular clearing distinguishable from lawn texture at 100% zoom") and
apply it identically to every plate. Write the rule down — it goes in Methods, and it is the single
biggest source of disagreement (see §8). Ideally have a **second person** correct a subset blind,
to check agreement.

### 2.3 Export the gold standard

When the plate matches your eye, **Export (▾) → Ground-truth labels…**. This writes two files next
to each other:

- `labels_<plate>.json` — schema **`plaque-groundtruth-v1`**
- `labels_<plate>.csv` — the same per-plaque rows, for spreadsheet/stats use

Put **all** plates' labels in **one folder** (e.g. `groundtruth/`). That folder *is* your gold
standard.

**What's inside (`plaque-groundtruth-v1`):**

```jsonc
{
  "meta": {
    "image": "WT-1.heic", "image_path": "C:/.../WT-1.heic",
    "mm_per_px": 0.041,            // calibration; null if no dish diameter entered
    "n_plaques": 47,               // total in the gold standard
    "n_manual": 9,                 // hand-edited (source != "auto") — your correction effort
    "dish_diam_px": 2438.0, "dish_center_px": [1270, 1310],
    "schema": "plaque-groundtruth-v1"
  },
  "plaques": [
    { "index": 1, "x_px": 812.4, "y_px": 530.1, "r_px": 18.7, "area_px": 1099.0,
      "diam_mm": 1.531, "source": "auto", "kind": "circle" }
    // source == "auto"  -> engine-detected & you KEPT it
    // source != "auto"  -> you added/redrew it by hand (counts toward n_manual)
  ]
}
```

You score against the full `plaques` list — `x_px, y_px` give each plaque's centre (for matching)
and `diam_mm` (or `r_px` × `2 × mm_per_px`) gives its size (for agreement). `source` and `n_manual`
let you report how much manual correction the gold standard needed (a transparency metric;
*don't* score `auto`-only).

> **Why this is legitimate "in-app" ground truth.** You are not asking the engine to grade itself.
> You started from a detection, **deleted what was wrong, and added what was missing, by human eye**,
> at full zoom, by a documented rule. The result is a human-curated gold standard that happens to
> have been *assembled* in the tool. For the strongest claim, also do the **independent Fiji
> cross-check** in §6 so the gold standard is anchored to a tool-independent count.

---

## 3. Run the engines you want to validate

For **each** plate, run **each** engine (Current, Sensitive, Precise — and Published as the
reference) and keep its per-plaque output:

- **App:** load the plate, pick the engine in the dropdown, **Export → Data table (CSV)…**.
- **Launchers / CLI:** `Measure Plaques.bat` / `Precise Detect (best engine).bat`, or
  `plaque_gui.py <img> -p 100 [--sensitive]`, Precise via `precise/run_precise.py`.

Each engine CSV has `X, Y` (centre, px) and `DIAMETER_MM` per detected plaque — the same coordinate
frame as the labels, so they match directly. Keep one engine CSV per plate per engine.

**Apply settings uniformly.** If you use `--watershed`, use it for *every* compared group or none
(see ENGINES.md). Whatever calibration / dish diameter you used to build the gold standard, use the
**same** value for the engine runs.

---

## 4. Score each engine against the gold standard

### 4.1 Match detections to gold-standard plaques

For one plate and one engine: match each detection to a gold-standard plaque by **centre distance**.
A detection and a gold plaque are a **match (TP)** when their centres are within a tolerance —
use **half the gold plaque's radius**, capped (e.g. `min(0.5 · r_px, ~25 px)`), and match
**greedily nearest-first, one-to-one** (each gold plaque and each detection used at most once).

- **TP** = detection matched to a gold plaque
- **FP** = detection with no gold match (a false positive — texture, rim, label, glare)
- **FN** = gold plaque with no detection (a miss)

### 4.2 Counts → precision, recall, F1

```
precision = TP / (TP + FP)      # of what the engine flagged, how much was real
recall    = TP / (TP + FN)      # of the real plaques, how many it found
F1        = 2·precision·recall / (precision + recall)
```

**Use F1, not specificity.** Plaque detection is **open-set**: there is no finite pool of
"true negatives" (you can't enumerate every non-plaque patch of agar), so specificity and accuracy
are ill-defined. F1 — the harmonic mean of precision and recall — is the correct summary for
detection. Sensitive trades precision for recall; Precise aims to lift both; F1 captures the
trade-off in one number.

### 4.3 Per-plate and pooled (micro)

- **Per-plate:** compute P/R/F1 on each plate separately → these feed the plate-level CI in §5
  (this is what you report).
- **Pooled (micro):** sum TP/FP/FN across all plates, then compute P/R/F1 once → a single
  headline number. Report it **alongside** the per-plate mean, never instead of it.

### 4.4 Sizes → agreement, not just correlation

For **matched (TP) pairs only**, compare engine `DIAMETER_MM` vs gold `diam_mm`:

- **Bland–Altman:** **bias** = mean(engine − gold); **95% limits of agreement (LoA)** =
  bias ± 1.96·SD(differences). Bias is the systematic over/under-sizing; LoA is the spread you'd
  see on a new plaque. Plot difference vs mean to check the bias is flat across sizes.
- **MAE** = mean(|engine − gold|) in mm — a single intuitive error.
- **Agreement, not just r:** report **ICC** (two-way, agreement) and/or Lin's concordance.
  **Pearson r alone hides systematic bias** — two methods can correlate at r = 0.99 while one reads
  20% high. Report r only as a supplement to ICC + Bland–Altman.

### 4.5 Negative / specificity control (do this — §5 of PUBLICATION.md)

Image an **uninfected lawn** (no phage) under the *same* conditions and run each engine on it.
A defensible engine returns **≈ 0** detections. Any detections are pure false positives and bound
your false-positive rate — the number that matters most for Sensitive and Precise.

- [ ] Report the count per engine (ideally on ≥ 2–3 negative plates): e.g. "0, 0, 1 detections."
- [ ] If an engine lights up an uninfected lawn, **do not report counts from it** without saying so.

### 4.6 Standalone scorer (the app's **Validate** tab already does this)

The app has a built-in **Validate** tab: point it at the folder of `labels_*.json` you exported,
tick the engines to score, and click **Run validation** — it reports precision / recall / F1 and
size agreement per engine (and per plate), using `app/validate.py`. The script below is only for
when you'd rather compute the metrics yourself from the exported files. Run it from the project
root (it reads the gold-standard `labels_*.json` and one engine CSV per plate; adjust the glob):

```python
# validate_quick.py — score engine CSVs against plaque-groundtruth-v1 labels
import json, glob, os, numpy as np, pandas as pd
from scipy.spatial.distance import cdist

GT_DIR  = "groundtruth"          # holds labels_<plate>.json
ENG_DIR = "out"                  # holds <plate>.csv from the engine (cols X,Y,DIAMETER_MM)

def match(gt_xy, gt_r, det_xy):
    if len(gt_xy)==0 or len(det_xy)==0: return [], list(range(len(det_xy))), list(range(len(gt_xy)))
    D = cdist(det_xy, gt_xy)                      # detections x gold
    tol = np.minimum(0.5*gt_r, 25.0)             # per-gold tolerance (px)
    used_g, pairs = set(), []
    for di in np.argsort(D.min(axis=1)):         # nearest detections first
        gi = int(np.argmin(D[di]))
        if gi not in used_g and D[di, gi] <= tol[gi]:
            used_g.add(gi); pairs.append((di, gi))
    matched_d = {d for d,_ in pairs}
    fp = [d for d in range(len(det_xy)) if d not in matched_d]
    fn = [g for g in range(len(gt_xy))  if g not in used_g]
    return pairs, fp, fn

rows, diffs = [], []
for jf in glob.glob(os.path.join(GT_DIR, "labels_*.json")):
    gt = json.load(open(jf)); P = gt["plaques"]
    plate = os.path.splitext(gt["meta"]["image"])[0]
    csv = os.path.join(ENG_DIR, plate + ".csv")
    if not os.path.exists(csv): print("no engine CSV for", plate); continue
    det = pd.read_csv(csv); det.columns = [c.upper() for c in det.columns]
    gt_xy = np.array([[p["x_px"], p["y_px"]] for p in P], float)
    gt_r  = np.array([p["r_px"] for p in P], float)
    gt_mm = np.array([p.get("diam_mm") or np.nan for p in P], float)
    det_xy = det[["X","Y"]].to_numpy(float)
    det_mm = det["DIAMETER_MM"].to_numpy(float)
    pairs, fp, fn = match(gt_xy, gt_r, det_xy)
    tp = len(pairs)
    prec = tp/(tp+len(fp)) if tp+len(fp) else 0.0
    rec  = tp/(tp+len(fn)) if tp+len(fn) else 0.0
    f1   = 2*prec*rec/(prec+rec) if prec+rec else 0.0
    rows.append(dict(plate=plate, TP=tp, FP=len(fp), FN=len(fn),
                     precision=prec, recall=rec, f1=f1))
    for d,g in pairs:
        if np.isfinite(det_mm[d]) and np.isfinite(gt_mm[g]):
            diffs.append(det_mm[d]-gt_mm[g])

df = pd.DataFrame(rows)
print(df.round(3).to_string(index=False))
print("\nPER-PLATE  P=%.3f±%.3f  R=%.3f±%.3f  F1=%.3f±%.3f  (mean±SD, n=%d plates)"
      % (df.precision.mean(), df.precision.std(ddof=1), df.recall.mean(), df.recall.std(ddof=1),
         df.f1.mean(), df.f1.std(ddof=1), len(df)))
TP,FP,FN = df.TP.sum(), df.FP.sum(), df.FN.sum()
mp, mr = TP/(TP+FP), TP/(TP+FN)
print("POOLED(micro)  P=%.3f  R=%.3f  F1=%.3f" % (mp, mr, 2*mp*mr/(mp+mr)))
d = np.array(diffs)
if len(d):
    print("SIZE  bias=%.3f mm  LoA=[%.3f, %.3f]  MAE=%.3f mm  (n=%d matched)"
          % (d.mean(), d.mean()-1.96*d.std(ddof=1), d.mean()+1.96*d.std(ddof=1),
             np.abs(d).mean(), len(d)))
```

Run once per engine (point `ENG_DIR` at that engine's CSVs). For **ICC**, feed the matched
(engine, gold) diameter pairs to `pingouin.intraclass_corr` (ICC2/ICC3, "agreement").

---

## 5. The plate is the experimental unit

**Aggregate at the plate level. Never treat individual plaques as independent replicates** — that
is pseudoreplication; it inflates *n* and fabricates significance.

- [ ] Compute P, R, F1 **per plate** (§4.3).
- [ ] Report **mean ± 95% CI across plates** (CI = mean ± t · SD/√n_plates). With ≥ 3 plates you
      have a CI; with 2 report both plates' values explicitly and call it preliminary.
- [ ] When you later **compare conditions/phages**, use **per-plate means** and a non-parametric
      test (Mann–Whitney / Kruskal–Wallis) or a mixed model with **plate as a random effect** —
      not pooled plaque counts. (PUBLICATION.md §"Statistics"; the bundled `make_figure.py` /
      `plot_sensitive_violin.py` already overlay per-plate medians.)

The **pooled micro** F1 is a fine headline, but the **plate-level mean ± CI** is the defensible
result.

---

## 6. Cross-check against an external gold standard (Fiji / ImageJ)

In-app ground truth is human-curated, but it starts from the tool's own detection. To anchor it to
a **tool-independent** standard, do a quick manual count in Fiji/ImageJ on **≥ 1 clear plate**:

1. Open the plate in **Fiji** (`File → Open`).
2. **Set the scale** from the dish: draw a line across the Petri-dish diameter →
   `Analyze → Set Scale` → enter the **true** dish mm (e.g. 100) as "known distance."
3. **Count:** `Plugins → Analyze → Cell Counter` (or the **Multi-point** tool) — click every
   plaque once. The total is your manual count.
4. **Size (a few):** for ~5–10 plaques, draw an ROI (oval/freehand) and `Analyze → Measure` to get
   area/diameter in mm.
5. **Compare:** manual count vs the engine's accepted count on that plate (should agree within a
   plaque or two on a clear plate); manual vs engine diameters (should sit within your §4.4 LoA).

This is your independent sanity check. If the engine count and the blind Fiji count disagree
badly on a *clear* plate, fix that before reporting anything from the engine. State in Methods that
you cross-checked against a blinded Fiji count.

---

## 7. Reporting template (copy-paste)

### 7.1 Validation table

Fill one row per engine you validated (Published is the reference; its job is to anchor the table).

```markdown
| Engine     | Precision (mean±CI) | Recall (mean±CI) | F1 (mean±CI) | Size bias (mm) [95% LoA] | ICC  | Neg. control (detections) | n plates |
|------------|---------------------|------------------|--------------|--------------------------|------|---------------------------|----------|
| Published  | —                   | —                | —            | (reference)              | —    | 0 / 0 / 0                 | N        |
| Current    | 0.xx ± 0.0x         | 0.xx ± 0.0x      | 0.xx ± 0.0x  | +0.0x [−0.x, +0.x]       | 0.xx | 0 / 0 / 0                 | N        |
| Sensitive  | 0.xx ± 0.0x         | 0.xx ± 0.0x      | 0.xx ± 0.0x  | +0.0x [−0.x, +0.x]       | 0.xx | 0 / 0 / 1                 | N        |
| Precise    | 0.xx ± 0.0x         | 0.xx ± 0.0x      | 0.xx ± 0.0x  | +0.0x [−0.x, +0.x]       | 0.xx | 0 / 0 / 0                 | N        |
```

Add a note: *"P/R/F1 are per-plate means ± 95% CI (n = N plates); pooled micro-F1 = Z. Size bias =
mean(engine − manual) on matched plaques; LoA = bias ± 1.96 SD; ICC = two-way agreement. Negative
control = detections on uninfected lawns."* Also report **n_manual / n_plaques** (how much the gold
standard had to be corrected) for transparency.

### 7.2 Methods / Results sentences

> **Published mode (citable):**
> *Plaque detection and sizing used the Plaque Size Tool (Trofimova & Jaschke, 2021;
> doi:10.1016/j.virol.2021.05.011) in its validated "Published" mode. Plates were imaged
> straight-on and calibrated from the detected Petri-dish diameter (XX mm).*

> **In-house mode (honest validation statement):**
> *Counts/sizes were obtained with the toolkit's in-house [Sensitive/Precise] engine, which is not
> independently peer-reviewed. We therefore validated it on our own imaging setup against a blinded,
> human-curated gold standard built in the program's editor (artifacts removed and missed plaques
> added by eye at full zoom under a fixed inclusion rule; N plates spanning sparse, dense, and
> textured lawns; n_manual = M corrections). Detections were matched to the gold standard by centre
> distance; the engine achieved precision X (95% CI …), recall Y (…), and F1 Z (…) as per-plate
> means (pooled micro-F1 = …). Matched-plaque diameters agreed with the gold standard with a bias of
> B mm (95% limits of agreement L1 to L2; ICC = C); a tool-independent Fiji/ImageJ count on K clear
> plates agreed within … An uninfected-lawn negative control returned 0 detections. The plate was
> treated as the experimental unit (n = …); per-plate means were compared with [test].*

Keep the **honesty note** explicit: name the engine, state it is unvalidated upstream, and that the
numbers above are *your* local validation — not inherited from the 2021 paper.

---

## 8. Limitations & pitfalls (state the relevant ones in Methods)

- **Imaging is the real bottleneck, not the algorithm.** These plates are typically **top-lit,
  gradient-lit phone photos**. ImageJ and the published ViralPlaque macro use *global* thresholding
  and **fail** on them; only adaptive-local (PST) and the trained PlaqSeg model cope. **No engine
  fixes bad imaging.** Back-lit / evenly illuminated plates (light box, fixed exposure,
  straight-down camera) are what unlock defensible numbers — especially for turbidity. Validate the
  *imaging*, then the engine.
- **Calibration depends on the TRUE dish diameter.** mm values are `mm_per_px = plate_mm ÷
  detected_dish_diameter_px`. The number you type must be the diameter of the **circle the tool
  actually traced** (usually the **inner agar**, not the outer plastic lip). Type the wrong
  diameter, or let the engine trace the lip while you enter the agar size, and **every** mm value —
  gold standard *and* engine — is wrong by the same factor (sizes shift, but agreement can look
  fine). Check the overlay's dish circle; use the same value everywhere.
- **Tilt biases the scale.** A tilted (non-orthographic) shot makes the dish elliptical; the tool
  warns when the dish axis-ratio > 1.03. Image straight-on or discard the plate.
- **The irreducible "is this faint speck a plaque?" ambiguity.** Some specks are genuinely
  undecidable. Your inclusion rule and inter-observer agreement *bound* this — they do not remove
  it. Two careful people will disagree on the faintest few. Report your rule; report agreement if
  you can; don't pretend the gold standard is perfect.
- **Gold standard provenance.** It is human-*curated* but tool-*seeded*. The Fiji cross-check (§6)
  is what makes it tool-independent — don't skip it for the headline claim.
- **Apply settings uniformly.** Same engine, same `--watershed` choice, same calibration across all
  compared groups and across gold standard vs engine runs. A setting that differs between them
  silently corrupts the metrics.
- **Validate per setup.** New camera, new lighting, new plate type, or new lawn strain → the
  validation **expires**. Re-run this protocol.
- **`source` / `n_manual` are transparency, not score.** Don't compute metrics on the `auto`-only
  subset — that scores the engine against itself. Score against the **full** corrected `plaques`
  list.

---

## 9. Master checklist

- [ ] Picked **≥ 2–3** representative plates (sparse + dense + textured), same setup as the experiment.
- [ ] Entered the **true** dish diameter; verified the traced dish circle on the overlay.
- [ ] Corrected each plate in the editor (**Detect area** to surface misses, **Remove** artifacts —
      texture, label, rim — **Add/trace** missed plaques) under a written inclusion rule.
- [ ] **Export → Ground-truth labels…** → all `labels_*.json` in one `groundtruth/` folder.
- [ ] Ran **each** engine on the same plates; kept one CSV per plate per engine.
- [ ] Matched by centre distance; computed **per-plate** and **pooled** P / R / **F1**.
- [ ] Computed **Bland–Altman bias + LoA, MAE, ICC** on matched diameters (not just r).
- [ ] Ran the **uninfected-lawn negative control** for each engine.
- [ ] Did the **Fiji/ImageJ** external count on ≥ 1 clear plate.
- [ ] Aggregated at **plate level**; reported **mean ± 95% CI** (n = plates).
- [ ] Filled the [table](#71-validation-table) and pasted the [Methods sentences](#72-methods--results-sentences),
      including the **honesty statement** and the **Trofimova & Jaschke 2021** citation for Published.

---

*See also: [PUBLICATION.md](PUBLICATION.md) (what is/ isn't defensible), [ENGINES.md](ENGINES.md)
(how each engine works), [USER_GUIDE.md](USER_GUIDE.md) (the imaging protocol).*
