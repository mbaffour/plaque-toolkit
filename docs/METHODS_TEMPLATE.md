# Methods template — a plaque *size* study

A ready-to-adapt **Methods** section for a manuscript that **measures plaque size** (not just
counts) with this toolkit. Copy the prose below into your paper and replace every
`[SQUARE-BRACKET]` placeholder with your own specifics. The numbers already written in are the
toolkit's own verified values — do not change them; only fill the brackets.

This template is deliberately conservative about what you may claim. Read
[PUBLICATION.md](PUBLICATION.md) (what is and isn't defensible) and
[VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) (how to validate an engine on your own plates) before
you submit. It is a *template*, not a validation — the validation numbers are yours to generate
and insert.

---

## How to use this page

1. Do the imaging and calibration as described, on **your** setup.
2. Run the detection/sizing engine you actually used.
3. Perform the validation (detection precision/recall/F1, per-plaque size agreement, negative
   control) — see [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) — and drop the resulting numbers into
   the bracketed slots.
4. Keep the honest caveats. A reviewer will ask; answer up front.

---

## 1. Image acquisition

> Petri dishes were photographed with a `[CAMERA / iPhone MODEL]` under fixed, top-lit
> illumination, positioned straight-on (orthographic) directly above the plate so the dish
> appeared circular rather than elliptical. Camera height, lighting, and exposure were held
> constant across all plates in a fixed rig. `[STATE: light source, e.g. overhead LED panel;
> whether exposure/white balance were locked; background colour.]`

**Note in your Methods (and to yourself):** back-lit, evenly illuminated plates (a light box or
transilluminator with a straight-down camera and fixed exposure) are the *ideal* geometry and are
what unlock the most defensible numbers; top-lit phone photos are workable but are the real
bottleneck on image quality, not the algorithm. Tilt biases the spatial scale — the toolkit warns
when the detected dish axis-ratio exceeds 1.03; image straight-on or discard the plate.

---

## 2. Spatial calibration (mm/px)

This is the paragraph that turns pixels into millimetres. Pick **one** of the two calibration
routes and delete the other.

> **Route A — Set-plate tool (dish-based).** Spatial calibration (mm per pixel) was established
> with the toolkit's Set-plate tool: three points were clicked on the agar edge to fit the dish
> circle, and the known physical diameter of that agar circle (`[AGAR DIAMETER]` mm) was entered,
> giving `mm_per_px = plate_mm / dish_diameter_px`.

> **Route B — in-frame ruler.** A ruler was placed in-frame in the plane of the agar and the
> scale (mm per pixel) was read directly from a known distance along the ruler.

> **Validation of the scale.** The spatial calibration was validated against a physical ruler,
> which gave a true scale of **0.040 mm/px (25 px/mm)**, consistent to within **+/-1% across 6
> photographs** of the same setup.

**The calibration subtlety you must get right (state it):** the vendor's nominal "90 mm / 100 mm"
figure is the **lid** diameter, but plaques form on the **~85 mm agar base**, not the lid.
Calibrate to the **agar diameter you actually measure** — the circle the tool traces and the
plaques occupy — not the printed lid size. Using the lid diameter would scale every millimetre
value by the same wrong factor (sizes shift together, so the error can hide inside otherwise
clean-looking agreement). Enter the true agar diameter, verify the traced dish circle on the
overlay, and use that same value for every plate.

---

## 3. Plaque detection and size measurement

> Plaques were detected and sized using the **Precise** engine of the Plaque Size Tool, which
> fuses the validated PST adaptive-local detection method (Trofimova & Jaschke, 2021;
> doi:10.1016/j.virol.2021.05.011) with a PlaqSeg YOLO segmentation model. `[STATE any options,
> e.g. whether the --watershed split or the --clf classifier gate was enabled — and apply the same
> choice uniformly to every compared group.]`

**Size definition.** Plaque **size** was quantified as the **convex-hull area** of each plaque and
reported as an **area-equivalent diameter**, `d = 2*sqrt(area/pi)`. Because size is taken from the
convex hull, it **includes any surrounding halo** and is therefore a slight **upper bound** on the
sharp clear zone.

> **You must state which "size" you mean.** Say explicitly whether "plaque size" in your paper is
> **(a)** the whole clearing including any halo (the convex-hull measurement this tool reports), or
> **(b)** the sharp, fully clear zone only. Do not leave it ambiguous — the two differ, and the
> convex-hull measure is the former.

**Software provenance and modifications (state this).** Measurements were made with *Plaque Toolkit*
(nicknamed *"Frankenstein's Plaque Lab"* because it assembles several components into one interface),
built on the open-source, peer-reviewed **Plaque Size Tool** (PST; Trofimova & Jaschke, 2021;
doi:10.1016/j.virol.2021.05.011). PST's adaptive-local thresholding detector is used **unchanged** in
the **Published** mode. We combined and extended it as follows: **(i)** a maintained **Current** mode
with bug-fixes to dish detection and the pixel→millimetre calibration; **(ii)** a **Precise** mode
that **fuses** PST detections with a **PlaqSeg** YOLO-segmentation model (from the OnePetri lineage)
and an optional **ResNet-18** classifier gate that suppresses non-plaque artefacts; **(iii)** an
interactive **review/correction editor** (add, erase, re-trace, and split touching plaques by
watershed) so every reported plaque is verified or corrected **by eye**; and **(iv)** spatial
calibration through a **Set-plate** tool (three points on the agar rim plus its measured diameter) or
an in-frame ruler. Reported plaques are numbered 1..N from the top of the image. `[STATE the exact
version/commit and which detection mode you used, and apply the same mode to every compared group.]`
See [CREDITS_AND_LINEAGE.md](CREDITS_AND_LINEAGE.md) for the full component lineage and licences.

---

## 4. Validation performed on our setup

The Precise engine (PST + PlaqSeg) is an **in-house** pipeline; it is not the peer-reviewed
"Published" mode, and PlaqSeg is not itself peer-reviewed (see §6). It therefore does **not**
inherit any published validation, and must be validated on your own plates. Report that
validation — the numbers below are yours to fill in from
[VALIDATION_GUIDE.md](VALIDATION_GUIDE.md).

> **A first local validation has been recorded** in
> [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md) (2026-07-07): against hand-labelled ground truth,
> Precise scored **precision 1.00** with **diameter agreement r ≈ 0.99 (MAE ≤ 0.0025 mm)**, at
> lower recall (≈ 0.3–0.4) on very dense plates; an independent cross-check in real Fiji/ImageJ gave
> **app-vs-Fiji size agreement r = 0.9999**. Treat that as the *foundation* — it is a small sample
> (2 GT plates + 1 Fiji plate) and still needs more plates, negative controls, and plate-level
> statistics before publication (see VALIDATION_RESULTS §5).

**"Validated" here means _your own local validation_, not an independent / peer-reviewed stamp.**
Precise can reach high detection precision on a given setup — on the developers' own plates it scored
**~0.95 precision** (with lower recall on faint plaques) — but that figure is *theirs*, tied to a
specific camera / lighting / lawn, and does **not** transfer. So do **not** write that Precise "is a
validated method"; write that *you validated it locally* and report the numbers below. For a claim
you can cite **without** doing your own validation, use the **Published** engine (Trofimova &
Jaschke, 2021).

> Detection was validated on `[N]` plates from this imaging setup, spanning
> `[sparse / dense / textured lawns]`, against a blinded, hand-labelled ground truth
> `[built in the program's editor and/or cross-checked in Fiji/ImageJ]`. Against that ground
> truth the engine achieved **precision `[X]`**, **recall `[Y]`**, and **F1 `[Z]`**
> `[report as per-plate mean +/- 95% CI, n = N plates]`.
>
> Per-plaque **size agreement** between the tool and the manual ground truth was assessed on
> matched plaques by Bland-Altman analysis (bias `[B]` mm; 95% limits of agreement
> `[L1]` to `[L2]`) and by intraclass correlation (ICC `[C]`).
>
> A **false-positive / specificity control** was run on `[k]` uninfected, negative-control
> plates (no phage); the engine returned `[e.g. 0, 0, 1]` detections, bounding the false-positive
> rate.

---

## 5. Statistics

> **The plate — not the individual plaque — was treated as the biological replicate.**
> Per-plaque measurements were first aggregated to **per-plate means** (`[which summary, e.g. mean
> or median plaque size per plate]`), and all comparisons were made on these plate-level values,
> with **>= 3 plates per condition**. Conditions were compared using non-parametric tests
> (`[Mann-Whitney U for two groups / Kruskal-Wallis for more than two]`) `[or: a linear mixed model
> with plate as a random effect]`. `[STATE n plates per condition, the exact test, and the software
> / package used.]`

Treating individual plaques as independent replicates is pseudoreplication: it inflates *n* and
manufactures significance. Aggregate to the plate first.

---

## 6. Caveats and limitations (keep these in the paper)

State the relevant ones explicitly — they are the difference between a defensible Methods section
and one a reviewer rejects:

1. **Only the "Published" mode is peer-reviewed.** The Precise engine and PlaqSeg used here are
   **in-house and not independently validated**; **PlaqSeg is not peer-reviewed**. The numbers in
   §4 are *our own local validation*, not validation inherited from Trofimova & Jaschke (2021).
2. **Validated for this imaging setup only.** The validation covers this specific camera,
   lighting, plate type, and lawn. A new camera, lighting rig, plate, or lawn strain expires the
   validation — it must be re-run.
3. **Size = convex-hull area (includes any halo).** The reported area-equivalent diameter is a
   slight upper bound on the sharp clear zone; we report `[whole clearing incl. halo / sharp clear
   zone]` (see §3).
4. **Calibration is to the agar diameter, not the lid** (see §2); tilt is controlled by imaging
   straight-on (dish axis-ratio warning at 1.03).

If you used the peer-reviewed **Published** engine instead of Precise, you may cite it directly as
a validated method (Trofimova & Jaschke, 2021; doi:10.1016/j.virol.2021.05.011) — see
[ENGINES.md](ENGINES.md) — and §4's local-validation language becomes optional.

---

## 7. Worked examples (with the real calibration numbers)

Two short sentences you can adapt, using the toolkit's verified scale:

> *"At the validated scale of 0.040 mm/px (25 px/mm), a plaque with a convex-hull area of 5000 px^2
> has an area-equivalent diameter of d = 2*sqrt(5000/pi) = 79.8 px = 3.19 mm (halo included)."*

> *"The spatial calibration agreed with a physical ruler at 0.040 mm/px (25 px/mm) to within +/-1%
> across 6 photographs, so a 100 px feature corresponds to 4.0 mm with an uncertainty of about
> +/-0.04 mm."*

---

*See also: [PUBLICATION.md](PUBLICATION.md) (what is / isn't defensible),
[VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) (validate an engine on your own plates),
[ENGINES.md](ENGINES.md) (what each detection mode does), and
[USER_GUIDE.md](USER_GUIDE.md) (the imaging protocol).*
