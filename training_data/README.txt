Plaque Toolkit — training-data store
====================================
Ground-truth labels accumulate here for retraining the plaque classifier.

  catalog.csv        one row per labelled plate (the index for training)
  labels/<id>.json   the label set (meta + per-plaque records)
  labels/<id>.csv    the same records, flat
  images/<id>.<ext>  a copy of the source plate image

How labels get here:
  * Desktop app: Measure -> Export -> Ground-truth labels  (auto-filed here)
  * Existing labels_*.json:  labelling\Ingest labels into training store.bat
  * Fiji hand-labelling:      labelling\  (macro + importer)

This folder is YOUR data (possibly unpublished) and is gitignored — it is never committed.
Point retraining at it via the PLAQUE_TRAINING_DIR env var or _research\clf.
