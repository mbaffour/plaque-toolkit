# Labelling plaques for training

Accumulate hand-corrected **ground-truth labels** into a persistent store so they can be used to
**retrain the plaque classifier**. Three ways to label, one store.

## The store — `training_data\` (gitignored — it's your data)

```
training_data\
  catalog.csv          one row per labelled plate (the index for training)
  labels\<id>.json     the label set (meta + per-plaque records)
  labels\<id>.csv      the same records, flat
  images\<id>.<ext>    a copy of the source plate image
```
Location: `<repo>\training_data\` when run from source, else `~\Plaque Toolkit Training Data`.
Override with the **`PLAQUE_TRAINING_DIR`** environment variable (e.g. point it at a shared drive).

## Three ways to label — all land in the same store

1. **In the desktop app (recommended)** — open a plate, correct the detections, then
   **Export ▾ → Ground-truth labels**. It saves your file *and* auto-files a copy + metadata into the
   store. Nothing else to do.
2. **Existing `labels_*.json`** (from earlier app exports, e.g. in `Verifications\`) —
   double-click **`Ingest labels into training store.bat`** and drop a file or folder on it
   (or `python ingest_labels.py <folder>`).
3. **Hand-label in Fiji / ImageJ** — double-click **`Label in Fiji.bat`** and follow the steps:
   install `fiji_label.ijm`, draw an oval on each plaque (press `t`), save, then drop the resulting
   `plaque_labels_*.csv` on **`Import Fiji labels.bat`** (it asks for the image + mm/px).

## What's captured (metadata, per plate)

date · sample · replicate · image filename + **SHA-1** · mm-per-pixel · n plaques · n hand-edited ·
source (app / import / fiji) · engine · app version · notes.

## Use it for retraining

The store *is* the dataset. Point the classifier training at it — set `PLAQUE_TRAINING_DIR` (or copy
the `labels\` + `images\` into the training tree) and run the pipeline in `_research\clf\`
(`train_clf.py`, `loop\train_loop.py`). See [`docs/TRAINING_AND_MODELS.md`](../docs/TRAINING_AND_MODELS.md)
and [`docs/MODEL_CARD.md`](../docs/MODEL_CARD.md). *(A helper to turn the store's labels + images into
48×48 training patches can be wired on top of this when you're ready to retrain.)*

## Files

| file | what it is |
|---|---|
| `../label_store.py` | the store engine (enrich metadata, copy image, append catalog) — used by the app + the tools |
| `ingest_labels.py` + `Ingest labels into training store.bat` | file existing `labels_*.json` into the store |
| `fiji_label.ijm` | the Fiji/ImageJ macro (set up labelling · save labels) |
| `fiji_import.py` + `Import Fiji labels.bat` | file Fiji `plaque_labels_*.csv` into the store |
| `Label in Fiji.bat` | launch Fiji + the step-by-step instructions |
