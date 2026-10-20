# Validation study protocol — new plates, from scratch

A checklist for building the dataset a **methods paper** on the toolkit needs: new plates,
blind labels, a second method, and an archive a reviewer can re-run. It is written for two
people — the **experimenter** (grows, photographs and measures the plates) and the
**labeller** (marks and traces plaques without seeing any tool output). Each step says who
does it and what the deliverable is.

Why it looks the way it does: the 2026 audits ([`AUDIT-2026-09.md`](../AUDIT-2026-09.md),
[`AUDIT-2026-10.md`](../AUDIT-2026-10.md)) found that the existing validation rests on one
phage, one operator and one rig, that engine-made contours had leaked into the "manual"
label set, and that two incompatible blank-plate numbers existed with no data behind
either. Every rule below closes one of those gaps.

---

## 0. Decisions to make before the first plate (experimenter)

- [ ] **Which engines will be claimed.** Published (citable reproduction of Trofimova &
      Jaschke 2021), Precise (deep-learning assisted), or both. Current and Sensitive are
      measured too but are not the headline.
- [ ] **Which quantities will be claimed.** Size (diameter / area) is the safe claim.
      Count / titer needs the blank-plate controls in §2. Turbidity needs the references in
      §3 *and* a physical standard (§6); if that is not possible, leave turbidity out of
      the paper's claims.
- [ ] **Which tools to compare against.** At minimum two of: Plaque Size Tool (upstream
      program, via `--upstream-exact`), ViralPlaque (Fiji macro), PyPlaque, OnePetri. Decide
      now so the same photos serve all of them.
- [ ] **Tag the toolkit version** you will use and write it down. Do not update the
      software mid-study.

## 1. Plate design (experimenter)

| Item | Minimum | Better |
|---|---|---|
| Phage–host pairs | 2, with different morphologies (e.g. one large clear, one small, one turbid) | 3 |
| Plates per condition | 3 | 8 (lets the stats module use normality / variance tests) |
| Plaque density | mostly 30–300 per plate | plus 2–3 deliberately dense plates per phage for the detection benchmark |
| Negative controls | 1 blank lawn plate (host, no phage) **per batch** | 3 per batch |
| Sizes | the natural range | include a dilution that gives isolated plaques for the Fiji tracing |

- [ ] Same soft-agar volume, host density and incubation for every plate of a pair.
- [ ] Label every dish on the base, not the lid, with a code that will become the file name.

## 2. Blank plates (experimenter)

The false-positive rate per engine is a number the paper must report, and it must come from
plates that are in the archive.

- [ ] Photograph every blank plate exactly like the phage plates.
- [ ] Measure them with every engine. Record false positives per plate per engine.
- [ ] Archive the photos, the CSVs and the `run_metadata.json` files under
      `validation/negative_controls/` (see §8).

## 3. Photography (experimenter)

- [ ] **Straight on**, dish filling the frame. The tool prints a warning when the dish
      looks elliptical (axis ratio > 1.03); treat that as "re-shoot".
- [ ] **Ruler in the agar plane** in at least one photo per session, for the Fiji scale.
- [ ] **Neutral, matte background; white-balanced light; no window light.** Colour cast is
      where the Published engine diverges from the original program (up to 0.5 mm).
- [ ] **One camera, one setting, one distance** for the whole study. Phone JPEG/HEIC is
      fine for size. Write down the device and mode (e.g. "iPhone 14 Pro Max, 2.5× Portrait").
- [ ] **For turbidity only:** transmitted light (light box), and in the *same session* a
      blank agar plate (`--blank`), an empty light-box frame (`--flat`), a lens-covered frame
      (`--dark`). If the camera can save a linear 16-bit TIFF or RAW, use it; if not, say so.
- [ ] **File names:** `<phage>_<plate>.<ext>`, e.g. `T4_1.jpg`, `T4_2.jpg`, `blank_1.jpg`.
      Unique names across the whole study. One folder per session; **no nested folders
      with repeated names**, and never store photos inside an `out*` folder.

## 4. Measurement (experimenter)

- [ ] Decide the engine per run and keep it; never mix engines in one output folder.
- [ ] CLI: `python plaque_size_tool.py -d <folder> -p <dish mm> -o <out> [--published]`.
      App: the Measure tab, or the Batch tab with the **Small plaques** box **unticked** for
      Published (it is the CLI default).
- [ ] Turbidity: `python plaque_turbidity.py -d <folder> -p <dish mm> --blank B --flat F
      --dark D --group-by-prefix -o <out>` — `--dilution` is the *reciprocal* factor
      (1e6 for a 10⁻⁶ dilution).
- [ ] **Keep every `run_metadata.json`** next to its CSVs. It records the engine, flags,
      version and a digest of each image. Never re-run into a folder you will archive.
- [ ] **No hand edits** on validation plates. Edited outputs carry `edited: true` in their
      metadata and are excluded from scoring.
- [ ] Note the per-plate `mm_per_px` (in the metadata) against the ruler: a 2 % disagreement
      means the dish diameter you typed is wrong.

## 5. Ground truth — blind (labeller)

This is the expensive step and the one that decides whether the paper survives review.
The labeller must **not** see any tool overlay, CSV or count before labelling.

**5a. Detection labels (which plaques exist)**

- [ ] Pick at random, per phage: ≥ 3 ordinary plates, every dense plate, and 1 blank. Aim
      for ≥ 10 plates and ≥ 500 plaques in total.
- [ ] Open the **raw photo** in the app, choose *any* engine, then **delete every detected
      plaque** before marking, or mark in Fiji with the multi-point tool on the raw image.
      The point is that every label is placed by a person, not kept from the engine.
      (In the previous dataset, engine-made contours were kept as "manual" labels, which
      made the sizing check circular.)
- [ ] Mark **every** plaque, including merged ones (one mark per plaque in a merged pair) and
      edge plaques. Note ambiguous ones in a text file; they are scored both ways.
- [ ] Export: app → *Ground-truth labels…* (`labels_<plate>.json` + `.csv`), or Fiji → save
      the point ROI set and *Measure* for centres.
- [ ] Save the labels next to a **copy of the raw image** in `validation/ground_truth/`.
      The orientation must be the one the file has on disk; do not rotate in the app first.

**5b. Size tracing (how big they are)**

- [ ] 100–150 plaques, drawn at random from all phages and the full size range, with their
      plate IDs listed before tracing starts.
- [ ] In Fiji: set the scale from the ruler photo of that session (*Analyze › Set Scale*),
      trace each plaque's outline with the freehand or oval tool, *Measure* area. Record
      `plate, plaque_id, area_fiji_mm2`.
- [ ] Trace **blind** to the tool's outline. Afterwards the experimenter pairs each traced
      plaque with the tool's plaque by position and fills `area_tool_mm2`.
- [ ] If a **second labeller** can trace the same 50 plaques, do it: that gives the
      human-vs-human floor the tool is compared against.

**5c. Turbidity reference (optional)**

- [ ] If turbidity is claimed: photograph a dilution series of a scattering standard (or
      measure the same plates on a plate reader) so OD has a physical anchor.

## 6. Scoring (experimenter)

- [ ] Detection, every engine, same scorer:
      `python app/validate.py validation/ground_truth --modes precise,current,sensitive,published --match-frac 0.5`
      → precision, recall, F1 per plate and pooled. Report **per-plate ranges**, not only
      pooled values, and report the plate(s) where recall is lowest.
- [ ] Sizing: `python plaque_stats/agreement/agreement.py validation/paired_tool_vs_fiji.csv
      --tool area_tool_mm2 --manual area_fiji_mm2 --what area --convert-area-to-diameter
      --out validation/figures` → ICC(A,1) with CI, bias, limits of agreement with CI,
      proportional-bias slope. The tool prints which two columns it compared; check them.
- [ ] Other tools: run ViralPlaque / PyPlaque / `--upstream-exact` on the **same images** and
      put their detections and sizes through the same two scorers.
- [ ] Blank plates: false positives per plate per engine from §2.
- [ ] Inter-operator (if 5b second labeller exists): the same agreement script on the two
      human tracings.

## 7. Statistics for the paper

- [ ] Plate is the experimental unit. `plaque_stats` does this by default
      (`--unit replicate`); report its test choice as it states it (parametric on plate
      means below 8 plates; Welch/Games–Howell when variances differ).
- [ ] Never pool plaques across plates for a p-value, and never pool metrics in a LONG file
      (`--value <metric>`).

## 8. Archive (experimenter) — what a reviewer must be able to download

```
validation/
  images/<session>/<phage>_<plate>.<ext>     raw photos (never edited)
  ground_truth/labels_<plate>.json|csv       blind labels + copies of their images
  paired_tool_vs_fiji.csv                    §5b table, with a header naming the operator(s)
  negative_controls/                         blank-plate photos, CSVs, run_metadata.json
  runs/<engine>/                             every CSV + run_metadata.json used in scoring
  other_tools/<tool>/                        the comparison tools' raw outputs
  figures/                                   agreement reports and stats CSVs
  README.md                                  dates, camera, operators, toolkit tag, dish sizes
```

- [ ] Tag the toolkit release used; cite the tag **and** a Zenodo DOI for the archive.
- [ ] `run_metadata.json` files must be present for every CSV in `runs/`.

## 9. What "done" looks like

- ≥ 2 phage–host pairs, ≥ 3 plates each, ≥ 10 blind-labelled plates, ≥ 100 blind-traced plaques.
- Precision / recall / F1 per engine *and* per comparison tool, per plate and pooled.
- One blank-plate false-positive table.
- Sizing agreement vs a human with CI, and vs a second human if available.
- Every number traceable to a file in `validation/` and a `run_metadata.json`.

If a line in §9 cannot be ticked, say so in the paper rather than leaving it out: the
September and October audits exist because earlier claims outran the archived data.
