# How to label your plates (to unlock detector tuning)

The autoresearch round proved it: **the tool's false‑positive rate can't be tuned down further
without labelled positive plates in *your* imaging.** Labels give the loop a two‑sided objective —
"reject bubbles/debris **while** keeping the plaques you say are real" — instead of only the
false‑positive side. This guide is the fastest way to produce them.

## The idea
You don't label from a blank slate. The app auto‑detects, and you **correct** it — remove wrong
detections, add missed ones — then export. Correcting is minutes per plate.

## Steps (in the app)
1. Open **Plaque Toolkit (full)** → **Measure** tab.
2. **Open** a plaque plate. Pick engine **Precise** (highest recall — you start with the most
   detections, so mostly you're *removing* rather than adding).
3. In the editor, make it match the truth:
   - **Erase** false positives — click bubbles, rim specks, debris, lawn‑swirl dots.
   - **Add** missed real plaques — click one to auto‑trace, or drag a circle. Use **Detect area**
     to re‑scan a crowded corner.
   - **Zoom** (scroll wheel) on faint ones before deciding.
4. When it's correct, click **⬇ Export ▾ → Ground‑truth labels**. This writes
   `labels_<image>.json` (+ a `.csv`) next to a schema the loop reads.
5. Save every `labels_*.json` into **one folder**.

## The single most important rule: define "is this a plaque?" and be consistent
This is the real scientific judgement the tool can't make for you. Pick a rule and apply it to
**every** plate identically, e.g.:
> "A plaque = a distinct clear/cleared zone with a defined edge, ≥ ~0.3 mm. Faint sub‑0.3 mm
> specks with no clear edge are NOT counted."

Write your rule down and keep it next to the labels — it becomes your Methods definition, and it's
what lets the loop learn the boundary you actually want.

## What to label (efficient, representative set)
- **~8–12 plates** — enough for an honest held‑out split (some plates train the loop, some test it).
- **Spread across density**: include sparse, medium, and dense plates.
- **Spread across phages**: a couple per phage so the model isn't tuned to one morphology.
- **Include the hard cases**: plates with bubbles/condensation (so the loop sees real plaques
  *next to* real artifacts and learns to tell them apart in context).
- (The authors built a density catalog of their own plates to pick a balanced list — their
  `_research/autoresearch/label_catalog.csv`, which is author-local and not in the public repo.
  Rank your own plates by plaque count from the Batch tab's `per_plate.csv` to do the same.)

## When you're done
1. Point the app's **Validate** tab at the labels folder → it scores every engine
   (precision / recall / F1 + size agreement) against your gold standard — your publication numbers.
2. With enough labels, a **two‑sided tuning** round becomes possible — maximize recall on the
   labelled plaques **while** minimizing the false positives measured on blank control plates.
   The authors' scripts for this (`_research/autotune/`, `_research/autoresearch/`) are
   author-local and not in the public repo; the Validate tab's per-plate scores plus a batch run
   over blank plates give the two numbers such a round needs.

## Optional: labelling in Fiji instead
If you prefer Fiji, use **Export → Cropped plate for Fiji** (calibrated TIFF), mark plaques there,
and export ROIs — but the in‑app editor is faster and writes the exact label format the loop needs,
so it's the recommended path.
